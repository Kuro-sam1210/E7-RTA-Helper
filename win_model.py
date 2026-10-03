"""Win rates and ban suggestions from data/win_model.h5 (see workflow_scripts/get_win_model.py).

  - win_rate(): our chance to win from the heroes picked so far (the win bar while drafting)
  - recommend_bans(): after the draft each side bans one of the other's heroes (the third
    pick is ban-protected, so four are bannable). For every pair (our hero they ban, their
    hero we ban) the model predicts our win rate with the remaining four against four.
    From that 4x4 table:
      - our best ban is the enemy hero with the highest worst-case win rate, i.e.
        assuming they answer with their best ban (average shown alongside)
      - their most likely target is our hero whose loss hurts us most
"""
import json
import os

import numpy as np
import tensorflow as tf

MODEL_PATH = 'data/win_model.h5'
HEROES_PATH = 'data/win_model_heroes.json'
EMPTY, UNKNOWN = 0, 1
BAN_PROTECTED_SLOT = 2  # index of each team's third pick ("Ban Protection" in the draft screen)


class WinModel:
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
        ids = [self.hero_index.get(hero, UNKNOWN) for hero in team if hero and hero != 'unknown'][:self.team_size]
        return ids + [EMPTY] * (self.team_size - len(ids))

    def _predict(self, teams_a, teams_b, a_first_pick, rule, post_ban):
        count = len(teams_a)
        inputs = {
            'team_a': np.array([self._encode(t) for t in teams_a], dtype='int32'),
            'team_b': np.array([self._encode(t) for t in teams_b], dtype='int32'),
            'a_first_pick': np.full((count, 1), float(a_first_pick), dtype='float32'),
            'rule': np.full((count, 1), self.rule_index.get(rule, 0), dtype='int32'),
            'post_ban': np.full((count, 1), float(post_ban), dtype='float32'),
        }
        return self.model.predict(inputs, verbose=0)[:, 0]

    def win_rate(self, user_team, enemy_team, user_first_pick, rule=None):
        """Our win rate from the heroes each side has picked so far (before bans)."""
        return float(self._predict([user_team], [enemy_team], user_first_pick, rule, post_ban=0)[0])

    def recommend_bans(self, user_team, enemy_team, user_first_pick, rule=None,
                       user_banned=None, enemy_banned=None):
        if len(user_team) != 5 or len(enemy_team) != 5:
            raise ValueError('Ban suggestions need both full teams of 5 heroes')

        # Each team's third pick is ban-protected by the game, so only the other four can be banned
        ours_bannable = [h for i, h in enumerate(user_team) if i != BAN_PROTECTED_SLOT]
        theirs_bannable = [h for i, h in enumerate(enemy_team) if i != BAN_PROTECTED_SLOT]
        pairs = [(ours, theirs) for ours in ours_bannable for theirs in theirs_bannable]
        rates = self._predict(
            [[h for h in user_team if h != ours] for ours, _ in pairs],
            [[h for h in enemy_team if h != theirs] for _, theirs in pairs],
            user_first_pick, rule, post_ban=1).reshape(4, 4)  # rows: our banned hero, cols: their banned hero

        our_bans = sorted(({'hero': hero,
                            'worst_case_win_rate': float(rates[:, j].min()),
                            'win_rate': float(rates[:, j].mean())}
                           for j, hero in enumerate(theirs_bannable)),
                          key=lambda x: (-x['worst_case_win_rate'], -x['win_rate']))
        their_bans = sorted(({'hero': hero, 'win_rate': float(rates[i, :].max())}
                             for i, hero in enumerate(ours_bannable)), key=lambda x: x['win_rate'])

        # Expected result if both sides make their best ban
        best_ban = theirs_bannable.index(our_bans[0]['hero'])
        result = {
            'ban_suggestions': our_bans,       # best enemy hero to ban first
            'likely_enemy_bans': their_bans,   # our hero they most want to ban first
            'win_prediction': float(rates[:, best_ban].min()),
        }
        if user_banned in ours_bannable and enemy_banned in theirs_bannable:
            result['win_prediction'] = float(rates[ours_bannable.index(user_banned), theirs_bannable.index(enemy_banned)])
        return result
