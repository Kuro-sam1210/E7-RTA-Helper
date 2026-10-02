"""Post-draft ban suggestions from data/ban_model.h5 (see workflow_scripts/get_ban_model.py).

After the draft each side bans one of the other's five heroes. For every pair
(our hero they ban, their hero we ban) the model predicts our win rate with the
remaining four against four. From that 5x5 table:
  - our best ban is the enemy hero with the highest worst-case win rate, i.e.
    assuming they answer with their best ban (average shown alongside)
  - their most likely target is our hero whose loss hurts us most
"""
import json
import os

import numpy as np
import tensorflow as tf

MODEL_PATH = 'data/ban_model.h5'
HEROES_PATH = 'data/ban_model_heroes.json'


class BanRecommender:
    def __init__(self, model_path=MODEL_PATH, heroes_path=HEROES_PATH):
        self.model = tf.keras.models.load_model(model_path, compile=False)
        with open(heroes_path, encoding='utf-8') as file:
            meta = json.load(file)
        self.hero_index = {hero: i for i, hero in enumerate(meta['heroes'])}
        self.rule_index = {rule: i for i, rule in enumerate(meta['rules'])}
        self.team_size = meta['team_size']

    @classmethod
    def load_if_available(cls):
        if os.path.exists(MODEL_PATH) and os.path.exists(HEROES_PATH):
            return cls()
        return None

    def _encode(self, team):
        return [self.hero_index.get(hero, 0) for hero in team]

    def win_rates(self, teams_a, teams_b, a_first_pick, rule=None):
        """P(team A wins) for each pair of four-hero teams."""
        rule_id = self.rule_index.get(rule, 0)
        count = len(teams_a)
        inputs = [
            np.array([self._encode(t) for t in teams_a], dtype='int32'),
            np.array([self._encode(t) for t in teams_b], dtype='int32'),
            np.full((count, 1), float(a_first_pick), dtype='float32'),
            np.full((count, 1), rule_id, dtype='int32'),
        ]
        return self.model.predict(inputs, verbose=0)[:, 0]

    def recommend(self, user_team, enemy_team, user_first_pick, rule=None,
                  user_banned=None, enemy_banned=None):
        if len(user_team) != 5 or len(enemy_team) != 5:
            raise ValueError('Ban suggestions need both full teams of 5 heroes')

        pairs = [(ours, theirs) for ours in user_team for theirs in enemy_team]
        rates = self.win_rates(
            [[h for h in user_team if h != ours] for ours, _ in pairs],
            [[h for h in enemy_team if h != theirs] for _, theirs in pairs],
            user_first_pick, rule).reshape(5, 5)  # rows: our banned hero, cols: their banned hero

        our_bans = sorted(({'hero': hero,
                            'worst_case_win_rate': float(rates[:, j].min()),
                            'win_rate': float(rates[:, j].mean())}
                           for j, hero in enumerate(enemy_team)),
                          key=lambda x: (-x['worst_case_win_rate'], -x['win_rate']))
        their_bans = sorted(({'hero': hero, 'win_rate': float(rates[i, :].max())}
                             for i, hero in enumerate(user_team)), key=lambda x: x['win_rate'])

        # Expected result if both sides make their best ban
        best_ban = enemy_team.index(our_bans[0]['hero'])
        result = {
            'ban_suggestions': our_bans,       # best enemy hero to ban first
            'likely_enemy_bans': their_bans,   # our hero they most want to ban first
            'win_prediction': float(rates[:, best_ban].min()),
        }
        if user_banned in user_team and enemy_banned in enemy_team:
            result['win_prediction'] = float(rates[user_team.index(user_banned), enemy_team.index(enemy_banned)])
        return result
