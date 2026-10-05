"""Train the win model: data/win_model.h5 + data/win_model_heroes.json.

Predicts P(team A wins) at any point of a match:
  - during the draft (phase 0): the heroes each team has picked so far (0-5 each)
  - after the bans (phase 1): the four heroes per team that actually fight
from the two teams, whether team A picked first, and the warfare rule.

search_server.py uses it for the win bar while drafting, and (through
win_model.py) for ban suggestions: the enemy hero whose ban gives us the best
worst-case win rate, and the hero of ours they will most likely ban.

Each team is five slots; slots not picked yet (or banned) hold a learned
"empty" hero, and slots are averaged so pick order within a team does not
matter. Every match gives one example per draft step plus one after bans, seen
from both sides. Uses only standard layers so the model loads in the app's
TensorFlow 2.13.

Reads data/epic7_match_history.csv.gz (needs the Banned and Rule columns from get_matches.py).
"""
import argparse
import json

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, Model
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

TEAM_SIZE = 5
PICKS = 10
MIN_HERO_MATCHES = 30  # rarer heroes share the 'unknown' embedding

parser = argparse.ArgumentParser()
parser.add_argument('--matches', default='data/epic7_match_history.csv.gz')
parser.add_argument('--output-dir', default='data')
parser.add_argument('--epochs', type=int, default=30)
parser.add_argument('--old-before', help='matches before this day (YYYY-MM-DD, e.g. a balance patch) count as old')
parser.add_argument('--old-weight', type=float, default=1.0, help='training weight of old matches (0 drops them)')
parser.add_argument('--test-from', help='validate on matches from this day on instead of a random tenth')
args = parser.parse_args()
MODEL_PATH = f'{args.output_dir}/win_model.h5'
HEROES_PATH = f'{args.output_dir}/win_model_heroes.json'

data = pd.read_csv(args.matches)
if 'Banned' not in data.columns:
    raise SystemExit('epic7_match_history.csv.gz has no Banned column, re-run get_matches.py')
data['Rule'] = data['Rule'].fillna('') if 'Rule' in data.columns else ''
data = data.sort_values(['Match Number', 'Pick Order'])

# Complete matches only: 10 picks, 5 per team, exactly one banned hero per team
per_match = data.groupby('Match Number').agg(picks=('Pick Order', 'nunique'), mine=('Team', lambda t: (t == 'My Team').sum()),
                                             bans=('Banned', 'sum'))
valid = per_match.index[(per_match['picks'] == PICKS) & (per_match['mine'] == TEAM_SIZE) & (per_match['bans'] == 2)]
data = data[data['Match Number'].isin(valid)]
num_matches = len(data) // PICKS

# Vocabularies: 0 = empty slot, 1 = unknown (rare) hero; rules: 0 = unknown
counts = data['Hero'].value_counts()
heroes = ['empty', 'unknown'] + sorted(counts[counts >= MIN_HERO_MATCHES].index)
hero_index = {hero: i for i, hero in enumerate(heroes)}
rules = ['unknown'] + sorted(r for r in data['Rule'].unique() if str(r).startswith('rta_openingrule'))
rule_index = {rule: i for i, rule in enumerate(rules)}

# (matches, 10) arrays in draft order
hero_ids = data['Hero'].map(lambda h: hero_index.get(h, 1)).to_numpy().reshape(num_matches, PICKS)
is_mine = (data['Team'] == 'My Team').to_numpy().reshape(num_matches, PICKS)
banned = (data['Banned'] == 1).to_numpy().reshape(num_matches, PICKS)
my_first = data['First Pick'].to_numpy().reshape(num_matches, PICKS)[is_mine].reshape(num_matches, TEAM_SIZE)[:, 0]
my_win = (data['Match Result'] == 'Win').to_numpy().reshape(num_matches, PICKS)[is_mine].reshape(num_matches, TEAM_SIZE)[:, 0]
match_rule = data['Rule'].map(lambda r: rule_index.get(r, 0)).to_numpy().reshape(num_matches, PICKS)[:, 0]
# Day of each match ('' when unknown, which counts as old)
match_date = (data['Date'].fillna('').astype(str).to_numpy().reshape(num_matches, PICKS)[:, 0]
              if 'Date' in data.columns else np.full(num_matches, ''))
if (args.old_before or args.test_from) and 'Date' not in data.columns:
    raise SystemExit('the match file has no Date column, rebuild it with get_matches.py --csv-only')
match_weight = np.where(match_date < args.old_before, args.old_weight, 1.0) if args.old_before else np.ones(num_matches)

# Each team's heroes in its own pick order, and how many each team has after k picks
my_heroes = hero_ids[is_mine].reshape(num_matches, TEAM_SIZE)
enemy_heroes = hero_ids[~is_mine].reshape(num_matches, TEAM_SIZE)
my_banned = banned[is_mine].reshape(num_matches, TEAM_SIZE)
enemy_banned = banned[~is_mine].reshape(num_matches, TEAM_SIZE)
my_counts = np.cumsum(is_mine, axis=1)
slots = np.arange(TEAM_SIZE)

team_a, team_b, phase, stage = [], [], [], []
for picks in range(1, PICKS + 1):
    mine = my_counts[:, picks - 1][:, None]
    theirs = picks - mine
    team_a.append(np.where(slots < mine, my_heroes, 0))
    team_b.append(np.where(slots < theirs, enemy_heroes, 0))
    phase.append(np.zeros(num_matches))
    stage.append(np.full(num_matches, picks))
# After bans: four heroes each
team_a.append(np.where(my_banned, 0, my_heroes))
team_b.append(np.where(enemy_banned, 0, enemy_heroes))
phase.append(np.ones(num_matches))
stage.append(np.full(num_matches, PICKS + 1))
steps = len(team_a)
team_a, team_b = np.concatenate(team_a), np.concatenate(team_b)
phase, stage = np.concatenate(phase), np.concatenate(stage)
a_first = np.tile(my_first, steps)
a_win = np.tile(my_win, steps).astype(np.float32)
rule = np.tile(match_rule, steps)
match_of = np.tile(np.arange(num_matches), steps)

# Split by match, then add every example from the other side as well
is_val = np.zeros(num_matches, dtype=bool)
if args.test_from:
    is_val = match_date >= args.test_from
else:
    is_val[np.random.default_rng(7).permutation(num_matches)[: num_matches // 10]] = True


def both_sides(sel):
    x = {
        'team_a': np.concatenate([team_a[sel], team_b[sel]]).astype(np.int32),
        'team_b': np.concatenate([team_b[sel], team_a[sel]]).astype(np.int32),
        'a_first_pick': np.concatenate([a_first[sel], 1 - a_first[sel]])[:, None].astype(np.float32),
        'rule': np.concatenate([rule[sel], rule[sel]])[:, None].astype(np.int32),
        'post_ban': np.concatenate([phase[sel], phase[sel]])[:, None].astype(np.float32),
    }
    return x, np.concatenate([a_win[sel], 1 - a_win[sel]]), np.concatenate([stage[sel], stage[sel]]), \
        np.concatenate([a_first[sel], 1 - a_first[sel]])


val_sel = is_val[match_of]
train_sel = ~val_sel & (match_weight[match_of] > 0)
x_train, y_train, _, _ = both_sides(train_sel)
w_train = np.tile(match_weight[match_of][train_sel], 2).astype(np.float32)
x_val, y_val, val_stage, val_first = both_sides(val_sel)
print(f'{num_matches} matches, {len(y_train)} training / {len(y_val)} validation examples, '
      f'{len(heroes) - 2} heroes, rules {rules[1:]}')

# Model: shared hero embedding, each team averaged with the rule and phase, then an MLP
# over both teams and their element-wise interaction
inputs = {
    'team_a': layers.Input(shape=(TEAM_SIZE,), dtype='int32', name='team_a'),
    'team_b': layers.Input(shape=(TEAM_SIZE,), dtype='int32', name='team_b'),
    'a_first_pick': layers.Input(shape=(1,), name='a_first_pick'),
    'rule': layers.Input(shape=(1,), dtype='int32', name='rule'),
    'post_ban': layers.Input(shape=(1,), name='post_ban'),
}
embedding = layers.Embedding(len(heroes), 64, name='hero_embedding')
rule_vec = layers.Flatten()(layers.Embedding(len(rules), 16, name='rule_embedding')(inputs['rule']))
context = layers.Concatenate()([rule_vec, inputs['post_ban']])
team_tower = tf.keras.Sequential([layers.Dense(128, activation='relu'), layers.Dense(64, activation='relu')],
                                 name='team_tower')
vec_a = team_tower(layers.Concatenate()([layers.GlobalAveragePooling1D()(embedding(inputs['team_a'])), context]))
vec_b = team_tower(layers.Concatenate()([layers.GlobalAveragePooling1D()(embedding(inputs['team_b'])), context]))

hidden = layers.Concatenate()([vec_a, vec_b, layers.Multiply()([vec_a, vec_b]), layers.Subtract()([vec_a, vec_b]),
                               inputs['a_first_pick'], inputs['post_ban']])
hidden = layers.Dropout(0.3)(layers.Dense(128, activation='relu')(hidden))
hidden = layers.Dense(32, activation='relu')(hidden)
output = layers.Dense(1, activation='sigmoid', name='win')(hidden)

model = Model(inputs, output)
model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss='binary_crossentropy',
              metrics=['accuracy', tf.keras.metrics.AUC(name='auc')])
model.fit(x_train, y_train, sample_weight=w_train, validation_data=(x_val, y_val), batch_size=1024,
          epochs=args.epochs, verbose=2,
          callbacks=[EarlyStopping(monitor='val_loss', patience=2, restore_best_weights=True),
                     ModelCheckpoint(MODEL_PATH, monitor='val_loss', save_best_only=True)])

model = tf.keras.models.load_model(MODEL_PATH)
predictions = model.predict(x_val, batch_size=4096, verbose=0)[:, 0]
correct = (predictions > 0.5) == (y_val == 1)
baseline = (val_first == 1) == (y_val == 1)  # always pick the first-pick team
print('stage            | accuracy | first-pick baseline')
for s in range(1, PICKS + 2):
    sel = val_stage == s
    label = f'{s} picks' if s <= PICKS else 'after bans'
    print(f'{label:16s} | {correct[sel].mean():.3f}    | {baseline[sel].mean():.3f}')
clipped = np.clip(predictions, 1e-6, 1 - 1e-6)
log_loss = -np.mean(y_val * np.log(clipped) + (1 - y_val) * np.log(1 - clipped))
print(f'overall: accuracy {correct.mean():.4f}, log loss {log_loss:.4f}')
tf.keras.models.save_model(model, MODEL_PATH, include_optimizer=False)

with open(HEROES_PATH, 'w', encoding='utf-8') as file:
    json.dump({'heroes': heroes, 'rules': rules, 'team_size': TEAM_SIZE}, file)
print(f'Saved {MODEL_PATH} and {HEROES_PATH}')
