"""Train the pick recommender: data/rec_model.h5 + data/rec_variables.pkl.

Each match's 10 picks (global draft order) become 9 examples: the picks so far
predict the next pick (next_hero output) and whether the first-pick team wins
(win_output). Inputs per pick: hero, pick order, team, first pick, hero role
types and the first-pick-win flag, plus the match's warfare rule.

Preprocessing works on whole arrays (every match has exactly 10 rows) so it
scales to hundreds of thousands of matches, labels are sparse (integer) to keep
memory low, and batches are streamed with tf.data.

Usage:
  python workflow_scripts/get_rec_model.py                       # full data
  python workflow_scripts/get_rec_model.py --sample 5000 --epochs 1   # quick check
"""
import argparse
import ast
import pickle

import numpy as np
import pandas as pd
import tensorflow as tf
from attention import Attention
from sklearn.preprocessing import LabelEncoder, MultiLabelBinarizer
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from tensorflow.keras.layers import (LSTM, Concatenate, Dense, Dropout, Embedding, Flatten, Input, Masking,
                                     RepeatVector)
from tensorflow.keras.models import Model
from tensorflow.keras.regularizers import l2

parser = argparse.ArgumentParser()
parser.add_argument('--matches', default='data/epic7_match_history.csv.gz')
parser.add_argument('--sample', type=int, help='train on this many random matches (for quick checks)')
parser.add_argument('--batch-size', type=int, default=256)
parser.add_argument('--lr', type=float, default=3e-4)
parser.add_argument('--epochs', type=int, default=50)
parser.add_argument('--patience', type=int, default=1)
parser.add_argument('--output-dir', default='data')
args = parser.parse_args()
MODEL_PATH = f'{args.output_dir}/rec_model.h5'
VARIABLES_PATH = f'{args.output_dir}/rec_variables.pkl'
PICKS = 10
max_sequence_length = PICKS - 1

# Load data, one row per pick
data = pd.read_csv(args.matches)
hero_details = pd.read_csv('data/hero_types.csv')
data = data.merge(hero_details[['code', 'type']], left_on='Hero', right_on='code', how='left')
if 'Rule' not in data.columns:
    data['Rule'] = ''
data['Rule'] = data['Rule'].fillna('')
data.loc[~data['Rule'].str.startswith('rta_openingrule'), 'Rule'] = ''

# Keep complete matches (10 picks, orders 1-10) whose heroes all have role types
data = data.sort_values(['Match Number', 'Pick Order'])
per_match = data.groupby('Match Number').agg(picks=('Pick Order', 'size'), orders=('Pick Order', 'nunique'),
                                             typed=('type', lambda t: t.notna().all()))
valid = per_match.index[(per_match['picks'] == PICKS) & (per_match['orders'] == PICKS) & per_match['typed']]
print(f'Invalid Matches: {len(per_match) - len(valid)} of {len(per_match)}')
if args.sample:
    valid = np.random.default_rng(7).choice(valid, size=min(args.sample, len(valid)), replace=False)
data = data[data['Match Number'].isin(valid)].sort_values(['Match Number', 'Pick Order'])
num_matches = len(data) // PICKS
print(f'{num_matches} matches')

# Encoders (same classes as the original script, plus the warfare rule)
hero_encoder = LabelEncoder().fit(list(data['Hero'].unique()) + ['unknown'])
team_encoder = LabelEncoder().fit(data['Team'])
first_pick_encoder = LabelEncoder().fit(data['First Pick'])
type_lists = data['type'].apply(ast.literal_eval)
type_encoder = MultiLabelBinarizer().fit(list(type_lists) + [['Unknown']])
rule_encoder = LabelEncoder().fit(['unknown'] + sorted(r for r in data['Rule'].unique() if r))

# (matches, 10) arrays in draft order
heroes = hero_encoder.transform(data['Hero']).reshape(num_matches, PICKS)
orders = data['Pick Order'].to_numpy().reshape(num_matches, PICKS)
teams = team_encoder.transform(data['Team']).reshape(num_matches, PICKS)
first_picks = first_pick_encoder.transform(data['First Pick']).reshape(num_matches, PICKS)
first_pick_wins = ((data['First Pick'] == 1) & (data['Match Result'] == 'Win')).astype(int).to_numpy() \
    .reshape(num_matches, PICKS)
types = type_encoder.transform(type_lists).astype(np.uint8).reshape(num_matches, PICKS, -1)
match_rules = data['Rule'].to_numpy().reshape(num_matches, PICKS)[:, 0]
rules = rule_encoder.transform(np.where(match_rules == '', 'unknown', match_rules))
num_heroes, num_types, num_rules = len(hero_encoder.classes_), len(type_encoder.classes_), len(rule_encoder.classes_)


def build_examples(match_idx):
    """For each match, prefixes of 1..9 picks (pre-padded to 9) and the pick that follows."""
    count = len(match_idx) * max_sequence_length
    x = {name: np.zeros((count, max_sequence_length), dtype=np.int32)
         for name in ('heroes', 'orders', 'teams', 'first_picks', 'first_pick_wins')}
    x['types'] = np.zeros((count, max_sequence_length, num_types), dtype=np.uint8)
    x['rule'] = np.repeat(rules[match_idx], max_sequence_length)[:, None].astype(np.int32)
    next_hero = np.zeros(count, dtype=np.int32)
    win = np.repeat(first_pick_wins[match_idx, 0], max_sequence_length).astype(np.float32)
    for length in range(1, PICKS):
        rows = slice((length - 1) * len(match_idx), length * len(match_idx))
        for name, source in (('heroes', heroes), ('orders', orders), ('teams', teams),
                             ('first_picks', first_picks), ('first_pick_wins', first_pick_wins)):
            x[name][rows, -length:] = source[match_idx, :length]
        x['types'][rows, -length:] = types[match_idx, :length]
        next_hero[rows] = heroes[match_idx, length]
    # Same index clipping as the original script and search_server.py
    x['orders'] = np.clip(x['orders'], 0, max_sequence_length - 1)
    x['first_pick_wins'] = np.clip(x['first_pick_wins'], 0, max_sequence_length - 1)
    return x, {'next_hero': next_hero, 'win_output': win}


def dataset(x, y, shuffle):
    ds = tf.data.Dataset.from_tensor_slices((x, y))
    if shuffle:
        ds = ds.shuffle(200_000, seed=7, reshuffle_each_iteration=True)
    ds = ds.batch(args.batch_size).map(
        lambda x, y: ({**x, 'types': tf.cast(x['types'], tf.float32)}, y), num_parallel_calls=tf.data.AUTOTUNE)
    return ds.prefetch(tf.data.AUTOTUNE)


# Split by match so a validation draft never shares prefixes with training
order = np.random.default_rng(7).permutation(num_matches)
val_matches = order[: num_matches // 5]
train_matches = order[num_matches // 5:]
train_ds = dataset(*build_examples(train_matches), shuffle=True)
val_ds = dataset(*build_examples(val_matches), shuffle=False)
print(f'{len(train_matches) * max_sequence_length} training / {len(val_matches) * max_sequence_length} '
      f'validation examples, {num_heroes} heroes, {num_types} types, rules {list(rule_encoder.classes_)}')

# Model: as before, with the warfare rule repeated across the sequence
embedding_dim = 512
input_heroes = Input(shape=(max_sequence_length,), name='heroes')
input_pick_orders = Input(shape=(max_sequence_length,), name='orders')
input_teams = Input(shape=(max_sequence_length,), name='teams')
input_first_picks = Input(shape=(max_sequence_length,), name='first_picks')
input_types = Input(shape=(max_sequence_length, num_types), name='types')
input_first_pick_wins = Input(shape=(max_sequence_length,), name='first_pick_wins')
input_rule = Input(shape=(1,), name='rule')

masking_heroes = Masking(mask_value=0.0)(Embedding(num_heroes, embedding_dim)(input_heroes))
masking_orders = Masking(mask_value=0.0)(Embedding(max_sequence_length, embedding_dim)(input_pick_orders))
masking_teams = Masking(mask_value=0.0)(Embedding(len(team_encoder.classes_), embedding_dim)(input_teams))
masking_first_picks = Masking(mask_value=0.0)(
    Embedding(len(first_pick_encoder.classes_), embedding_dim)(input_first_picks))
masking_first_pick_wins = Masking(mask_value=0.0)(Embedding(2, embedding_dim)(input_first_pick_wins))
type_embedding = Dense(embedding_dim, activation='relu')(Masking(mask_value=0.0)(input_types))
rule_embedding = RepeatVector(max_sequence_length)(Flatten()(Embedding(num_rules, 32)(input_rule)))

concatenated = Concatenate()([masking_heroes, masking_orders, masking_teams, masking_first_picks, type_embedding,
                              masking_first_pick_wins, rule_embedding])
concatenated_win = Concatenate()([masking_heroes, masking_orders, masking_teams, masking_first_picks,
                                  type_embedding, rule_embedding])

lstm_out1 = LSTM(512, return_sequences=True)(concatenated)
attention = Attention(name='attention_weight')(lstm_out1)
output = Dense(num_heroes, activation='softmax', name='next_hero')(attention)

lstm_out2 = LSTM(128, return_sequences=True)(concatenated_win)
attention_win = Attention(name='attention_win_weight')(lstm_out2)
win_hidden = Dense(64, activation='relu', kernel_regularizer=l2(0.01))(attention_win)
win_hidden = Dropout(0.5)(win_hidden)
win_output = Dense(1, activation='sigmoid', name='win_output')(win_hidden)

# Input order matches search_server.py: heroes, orders, teams, first picks, types, first pick wins, rule
model = Model([input_heroes, input_pick_orders, input_teams, input_first_picks, input_types,
               input_first_pick_wins, input_rule], [output, win_output])
model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=args.lr),
    loss={'next_hero': 'sparse_categorical_crossentropy', 'win_output': 'binary_crossentropy'},
    metrics={'next_hero': ['accuracy',
                         tf.keras.metrics.SparseTopKCategoricalAccuracy(k=3, name='top_3_accuracy'),
                         tf.keras.metrics.SparseTopKCategoricalAccuracy(k=5, name='top_5_accuracy'),
                         tf.keras.metrics.SparseTopKCategoricalAccuracy(k=10, name='top_10_accuracy')],
             'win_output': ['accuracy']})

model.fit(train_ds, validation_data=val_ds, epochs=args.epochs, verbose=2,
          callbacks=[ModelCheckpoint(MODEL_PATH, save_best_only=True, monitor='val_loss', mode='min'),
                     EarlyStopping(monitor='val_loss', patience=args.patience)])

# Save the best epoch without optimizer state (smaller file)
model = tf.keras.models.load_model(MODEL_PATH, custom_objects={'Attention': Attention})
tf.keras.models.save_model(model, MODEL_PATH, include_optimizer=False)

# Save encoders only after training succeeded, so a crashed run never leaves the model and
# encoders out of step. The rule encoder is a fourth entry (search_server.py accepts files
# with or without it).
with open(VARIABLES_PATH, 'wb') as f:
    pickle.dump([type_encoder, hero_encoder, max_sequence_length, rule_encoder], f)
print(f'Saved {MODEL_PATH} and {VARIABLES_PATH}')
