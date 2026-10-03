"""Build my_roster.json from a Fribbels-format gear export, so suggestions only use heroes you have built.

The export is the JSON the Fribbels Epic 7 Optimizer imports (keys "heroes" and "items"), e.g. the
gear_<date>.txt written by a gear scanner. A hero counts as built when it is 6 stars with all six
gear slots filled. search_server.py reads my_roster.json if it exists and, on your turns, suggests
only built heroes. The roster is personal: my_roster.json is gitignored.

Heroes built after the export was taken can be added by code; they are stored as "manual_built" in
my_roster.json (which can also be edited by hand) and kept when a newer export is imported.

Usage:
  python import_roster.py path/to/gear_export.txt [hero codes built since, e.g. c5147]
"""
import collections
import json
import sys
from datetime import date

GEAR_SLOTS = 6
ROSTER_FILE = 'my_roster.json'


def build_roster(export):
    heroes, items = export['heroes'], export['items']
    hero_ids = {hero['id'] for hero in heroes}
    equipped = collections.defaultdict(list)
    for item in items:
        if item.get('p') in hero_ids:
            equipped[item['p']].append(item)

    owned, built, gear_speed = set(), set(), {}
    for hero in heroes:
        code = hero['code']
        owned.add(code)
        pieces = equipped.get(hero['id'], [])
        if hero.get('stars') == 6 and len(pieces) >= GEAR_SLOTS:
            built.add(code)
            # substat entries are [stat, value, ...]; keep the fastest copy of a duplicated hero
            speed = sum(op[1] for item in pieces for op in item.get('op', []) if op[0] == 'speed')
            gear_speed[code] = max(gear_speed.get(code, 0), round(speed))
    return {'created': date.today().isoformat(), 'owned': sorted(owned), 'built': sorted(built),
            'gear_speed': gear_speed}


def load_manual_built():
    """Hero codes the player added by hand ("manual_built"), kept across re-imports."""
    try:
        with open(ROSTER_FILE, encoding='utf-8') as file:
            return json.load(file).get('manual_built', [])
    except (OSError, ValueError):
        return []


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding='utf-8') as file:
        roster = build_roster(json.load(file))
    # Heroes built since the export was taken: kept from the previous roster, plus any given here
    roster['manual_built'] = sorted(set(load_manual_built()) | set(sys.argv[2:]))
    with open(ROSTER_FILE, 'w', encoding='utf-8') as file:
        json.dump(roster, file, indent=1)
    print(f'{len(roster["owned"])} heroes owned, {len(roster["built"])} built '
          f'(+{len(roster["manual_built"])} added by hand) -> {ROSTER_FILE}')
