"""Build data/hero_official_stats.csv from our own match data.

This file used to be scraped with Selenium from the official hero record pages,
which no longer exist in that form. It is now computed from
data/epic7_match_history.csv.gz (both sides of every match, banned heroes
excluded since they did not fight), in the same format the app reads:

  Hero, Rank ("Ranking: r / n" by win rate), Win Rate (percent),
  Equipment / Equipment Win Rate (top gear sets, see below), Counters, Synergies

Counters of a hero are the enemy heroes with the best win rate against it,
Synergies the teammates with the best win rate alongside it, both requiring
MIN_PAIR_GAMES games together. Gear sets are not in the match data yet, so the
Equipment columns are carried over from the previous file where they exist.
"""
import csv
import os

import numpy as np
import pandas as pd

MATCHES = 'data/epic7_match_history.csv.gz'
OUTPUT = 'data/hero_official_stats.csv'
MIN_HERO_GAMES = 200   # to be ranked
MIN_PAIR_GAMES = 300   # for a counter or synergy (win rates over fewer games are too noisy)
TOP = 3
NO_EQUIPMENT = ("{'0': [], '1': [], '2': [], '3': [], '4': []}", "{'0': -1, '1': -1, '2': -1, '3': -1, '4': -1}")

data = pd.read_csv(MATCHES).sort_values(['Match Number', 'Team', 'Pick Order'])
if 'Banned' not in data.columns:
    data['Banned'] = 0
data = data[data.groupby('Match Number')['Hero'].transform('size') == 10]
matches = len(data) // 10

codes = sorted(data['Hero'].unique())
index = {code: i for i, code in enumerate(codes)}
heroes = len(codes)

# (matches, 2 teams, 5 heroes), teams sorted 'Enemy Team' then 'My Team'
hero_ids = data['Hero'].map(index).to_numpy().reshape(matches, 2, 5)
fought = (data['Banned'] == 0).to_numpy().reshape(matches, 2, 5)
team_won = (data['Match Result'] == 'Win').to_numpy().reshape(matches, 2, 5)[:, :, 0]

# Per hero: games and wins (fighting heroes only, both sides)
games = np.bincount(hero_ids[fought], minlength=heroes)
wins = np.bincount(hero_ids[fought], weights=np.repeat(team_won[:, :, None], 5, axis=2)[fought], minlength=heroes)

# Pairs: same team (synergy) and opposite teams (counter), fighting heroes only
synergy_games = np.zeros((heroes, heroes))
synergy_wins = np.zeros((heroes, heroes))
versus_games = np.zeros((heroes, heroes))
versus_wins = np.zeros((heroes, heroes))  # [a, b]: games a won against b
for side in (0, 1):
    a, a_fought, won = hero_ids[:, side], fought[:, side], team_won[:, side]
    b, b_fought = hero_ids[:, 1 - side], fought[:, 1 - side]
    for i in range(5):
        for j in range(5):
            if i != j:
                sel = a_fought[:, i] & a_fought[:, j]
                np.add.at(synergy_games, (a[sel, i], a[sel, j]), 1)
                np.add.at(synergy_wins, (a[sel, i], a[sel, j]), won[sel])
            sel = a_fought[:, i] & b_fought[:, j]
            np.add.at(versus_games, (a[sel, i], b[sel, j]), 1)
            np.add.at(versus_wins, (a[sel, i], b[sel, j]), won[sel])


def best(win_matrix, game_matrix, hero, expected):
    """Codes of the TOP partners whose win rate in this pairing beats what they usually get.

    Scoring against the expected rate stops generally strong heroes from topping every list.
    """
    row_games = game_matrix[hero]
    rate = np.divide(win_matrix[hero], row_games, out=np.zeros(heroes), where=row_games > 0)
    lift = np.where(row_games >= MIN_PAIR_GAMES, rate - expected, -np.inf)
    order = [j for j in np.argsort(-lift) if np.isfinite(lift[j]) and lift[j] > 0][:TOP]
    return [codes[j] for j in order]


# Previous equipment data, kept until gear sets are collected with the matches
previous = {}
if os.path.exists(OUTPUT):
    with open(OUTPUT, newline='', encoding='utf-8') as file:
        previous = {row['Hero']: (row['Equipment'], row['Equipment Win Rate']) for row in csv.DictReader(file)}

win_rate = np.divide(wins, games, out=np.zeros(heroes), where=games > 0)
ranked = [h for h in np.argsort(-win_rate) if games[h] >= MIN_HERO_GAMES]
rank_of = {h: r + 1 for r, h in enumerate(ranked)}

rows = []
for h, code in enumerate(codes):
    equipment, equipment_rate = previous.get(code, NO_EQUIPMENT)
    rows.append({
        'Hero': code,
        'Rank': f'Ranking: {rank_of[h]} / {len(ranked)}' if h in rank_of else '',
        'Win Rate': f'{win_rate[h] * 100:.2f}' if games[h] else '',
        'Equipment': equipment,
        'Equipment Win Rate': equipment_rate,
        # Counters: enemies that beat this hero more often than they beat anyone (versus_wins[enemy, hero])
        'Counters': str(best(versus_wins.T, versus_games.T, h, win_rate)),
        # Synergies: teammates who win together more than the pair's own average
        'Synergies': str(best(synergy_wins, synergy_games, h, (win_rate + win_rate[h]) / 2)),
    })

# Heroes not seen in this season's matches keep their previous row
if os.path.exists(OUTPUT):
    with open(OUTPUT, newline='', encoding='utf-8') as file:
        rows += [row for row in csv.DictReader(file) if row['Hero'] not in index]

with open(OUTPUT, 'w', newline='', encoding='utf-8') as file:
    writer = csv.DictWriter(file, fieldnames=['Hero', 'Rank', 'Win Rate', 'Equipment', 'Equipment Win Rate',
                                              'Counters', 'Synergies'], lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
print(f'Wrote {len(rows)} heroes to {OUTPUT} ({len(ranked)} ranked, from {matches} matches)')
