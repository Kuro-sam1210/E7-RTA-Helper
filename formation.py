"""Formation suggestions: where top players stand each hero (front, middle, back).

Built from the positions in official battle records (see workflow_scripts/get_hero_positions.py).
Some heroes depend on their slot (Boss Arunka in front, Requiem Roana at the back) and some on who
stands in a slot, so a hero's position counts are combined with the counts seen next to each of
its current teammates, and the four heroes are then assigned the most likely arrangement.
"""
import itertools
import json
import math
import os

POSITIONS_FILE = 'data/hero_positions.json'
# Battle records number the slots 1-4: 1 is the front, 4 the back, 2 and 3 the middle pair
POSITION_NAMES = {1: 'Front', 2: 'Middle', 3: 'Middle', 4: 'Back'}
SLOTS = (1, 2, 3, 4)
# How many games the hero's overall habits count for next to the teammate-specific games
PRIOR_GAMES = 10
SMOOTHING = 0.5


class Formation:
    def __init__(self, path=POSITIONS_FILE):
        with open(path, encoding='utf-8') as file:
            self.heroes = json.load(file)['heroes']

    @classmethod
    def load_if_available(cls, path=POSITIONS_FILE):
        return cls(path) if os.path.exists(path) else None

    def slot_shares(self, hero, teammates):
        """Estimated share of games `hero` stands in each slot when fielded with `teammates`."""
        entry = self.heroes.get(hero)
        if entry is None:
            return [1 / len(SLOTS)] * len(SLOTS)
        total = sum(entry['n']) or 1
        counts = [PRIOR_GAMES * games / total + SMOOTHING for games in entry['n']]
        for mate in teammates:
            for slot, games in enumerate(entry['with'].get(mate, [])):
                counts[slot] += games
        return [count / sum(counts) for count in counts]

    def suggest(self, team):
        """Most likely arrangement of the four fielded heroes: [{hero, slot, position, share}]."""
        team = list(team)[:len(SLOTS)]
        if len(team) < len(SLOTS):
            return []
        shares = {hero: self.slot_shares(hero, [mate for mate in team if mate != hero]) for hero in team}
        best = max(itertools.permutations(SLOTS),
                   key=lambda slots: sum(math.log(shares[hero][slot - 1]) for hero, slot in zip(team, slots)))
        formation = [{'hero': hero, 'slot': slot, 'position': POSITION_NAMES[slot],
                      'share': round(shares[hero][slot - 1], 3)} for hero, slot in zip(team, best)]
        return sorted(formation, key=lambda entry: entry['slot'])
