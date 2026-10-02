"""Train the post-ban win model: data/ban_model.h5 + data/ban_model_heroes.json.

After the draft each side bans one of the other's five heroes, so four fight.
This model predicts P(team A wins) from the two four-hero teams, whether
team A picked first, and the warfare rule. search_server.py uses it to:
  - suggest the ban: the enemy hero whose removal gives the best average win
    rate across the bans the enemy could make on us
  - show the final win rate once both bans are known

Reads data/epic7_match_history.csv.gz (needs the Banned column from get_matches.py).
Uses only standard layers so the model loads in the app's TensorFlow 2.13.
"""
import argparse
import json

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, Model
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

TEAM_SIZE = 4
MIN_HERO_MATCHES = 30  # rarer heroes share the 'unknown' embedding

parser = argparse.ArgumentParser()
parser.add_argument('--matches', default='data/epic7_match_history.csv.gz')
parser.add_argument('--output-dir', default='data')
args = parser.parse_args()
MODEL_PATH = f'{args.output_dir}/ban_model.h5'
HEROES_PATH = f'{args.output_dir}/ban_model_heroes.json'

data = pd.read_csv(args.matches)
if 'Banned' not in data.columns:
    raise SystemExit('epic7_match_history.csv has no Banned column, re-run get_matches.py')

# Hero vocabulary; index 0 is 'unknown'
counts = data['Hero'].value_counts()
heroes = ['unknown'] + sorted(counts[counts >= MIN_HERO_MATCHES].index)
hero_index = {hero: i for i, hero in enumerate(heroes)}

# Warfare rule vocabulary (the rule changes which heroes are strong); index 0 is 'unknown'
data['Rule'] = data['Rule'].fillna('') if 'Rule' in data.columns else ''
rules = ['unknown'] + sorted(r for r in data['Rule'].unique() if r.startswith('rta_openingrule'))
rule_index = {rule: i for i, rule in enumerate(rules)}

# One row per match: the four unbanned heroes of each team, first pick, rule and result
team_a, team_b, a_first, a_win, rule = [], [], [], [], []
for _, match in data.groupby('Match Number'):
    my_team = match[(match['Team'] == 'My Team') & (match['Banned'] == 0)]
    enemy_team = match[(match['Team'] == 'Enemy Team') & (match['Banned'] == 0)]
    if len(my_team) != TEAM_SIZE or len(enemy_team) != TEAM_SIZE:
        continue
    team_a.append([hero_index.get(h, 0) for h in my_team['Hero']])
    team_b.append([hero_index.get(h, 0) for h in enemy_team['Hero']])
    a_first.append(int(my_team['First Pick'].iloc[0]))
    a_win.append(int(my_team['Match Result'].iloc[0] == 'Win'))
    rule.append(rule_index.get(my_team['Rule'].iloc[0], 0))

team_a, team_b, rule = np.array(team_a), np.array(team_b), np.array(rule)
a_first, a_win = np.array(a_first, dtype='float32'), np.array(a_win, dtype='float32')
print(f'{len(a_win)} matches, {len(heroes) - 1} heroes, rules {rules[1:]}')

# Split by match so the mirrored copy of a validation match never appears in training
rng = np.random.default_rng(7)
order = rng.permutation(len(a_win))
val_size = len(order) // 10
val, train = order[:val_size], order[val_size:]


def both_sides(idx):
    """Each match from both perspectives, so the model is symmetric."""
    x_a = np.concatenate([team_a[idx], team_b[idx]])
    x_b = np.concatenate([team_b[idx], team_a[idx]])
    first = np.concatenate([a_first[idx], 1 - a_first[idx]])[:, None]
    match_rule = np.concatenate([rule[idx], rule[idx]])[:, None]
    win = np.concatenate([a_win[idx], 1 - a_win[idx]])
    return [x_a, x_b, first, match_rule], win


x_train, y_train = both_sides(train)
x_val, y_val = both_sides(val)
print(f'first pick win rate: {a_win[a_first == 1].mean():.3f}')

# Model: shared hero embedding, each team averaged (order does not matter) together with
# the warfare rule, then an MLP over both teams and their element-wise interaction
input_a = layers.Input(shape=(TEAM_SIZE,), dtype='int32', name='team_a')
input_b = layers.Input(shape=(TEAM_SIZE,), dtype='int32', name='team_b')
input_first = layers.Input(shape=(1,), name='a_first_pick')
input_rule = layers.Input(shape=(1,), dtype='int32', name='rule')

embedding = layers.Embedding(len(heroes), 64, name='hero_embedding')
rule_vec = layers.Flatten()(layers.Embedding(len(rules), 16, name='rule_embedding')(input_rule))
team_tower = tf.keras.Sequential([layers.Dense(128, activation='relu'), layers.Dense(64, activation='relu')],
                                 name='team_tower')
# The rule goes into the team tower so each team is valued under the rule it plays in
vec_a = team_tower(layers.Concatenate()([layers.GlobalAveragePooling1D()(embedding(input_a)), rule_vec]))
vec_b = team_tower(layers.Concatenate()([layers.GlobalAveragePooling1D()(embedding(input_b)), rule_vec]))

hidden = layers.Concatenate()([vec_a, vec_b, layers.Multiply()([vec_a, vec_b]),
                               layers.Subtract()([vec_a, vec_b]), input_first])
hidden = layers.Dropout(0.3)(layers.Dense(128, activation='relu')(hidden))
hidden = layers.Dense(32, activation='relu')(hidden)
output = layers.Dense(1, activation='sigmoid', name='win')(hidden)

model = Model([input_a, input_b, input_first, input_rule], output)
model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss='binary_crossentropy',
              metrics=['accuracy', tf.keras.metrics.AUC(name='auc')])

model.fit(x_train, y_train, validation_data=(x_val, y_val), batch_size=256, epochs=50, verbose=2,
          callbacks=[EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True),
                     ModelCheckpoint(MODEL_PATH, monitor='val_loss', save_best_only=True)])

model = tf.keras.models.load_model(MODEL_PATH)
loss, accuracy, auc = model.evaluate(x_val, y_val, verbose=0)
print(f'validation: accuracy {accuracy:.4f}, AUC {auc:.4f}, loss {loss:.4f}')
tf.keras.models.save_model(model, MODEL_PATH, include_optimizer=False)

with open(HEROES_PATH, 'w', encoding='utf-8') as file:
    json.dump({'heroes': heroes, 'rules': rules, 'team_size': TEAM_SIZE}, file)
print(f'Saved {MODEL_PATH} and {HEROES_PATH}')
