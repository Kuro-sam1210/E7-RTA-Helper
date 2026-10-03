"""Collect where top players stand each hero, for the formation suggestions (formation.py).

Battle records give every hero a position: 1 front, 2 and 3 the middle pair, 4 back (0 = banned).
This samples the battles of the top players of each server, caches the teams in
match_histories/positions_<season>.jsonl (re-running adds new battles) and writes
data/hero_positions.json: per hero the games in each slot, overall ("n") and next to each
frequent teammate ("with").

Usage:
  python workflow_scripts/get_hero_positions.py                  # 25 players per server
  python workflow_scripts/get_hero_positions.py --players 100    # about 0.6 MB of download per player
  python workflow_scripts/get_hero_positions.py --build-only     # rebuild from the cache, with an accuracy check
"""
import argparse
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
import get_matches

MIN_PAIR_GAMES = 15
OUTPUT = 'data/hero_positions.json'


def load_teams(cache_path):
    teams = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding='utf-8') as file:
            for line in file:
                row = json.loads(line)
                teams[row['id']] = row['team']
    return teams


def crawl(season, servers, players, delay, cache_path, teams):
    with open(cache_path, 'a', encoding='utf-8') as cache:
        for server in servers:
            for nick_no in get_matches.get_top_players(server, season, delay)[:players]:
                value = get_matches.call_api('getBattleList', delay, nick_no=nick_no, world_code=server,
                                             season_code=season)
                for raw in (value or {}).get('result_body', {}).get('battle_list') or []:
                    # Both players of a battle report it; each side is stored once
                    sides = (('teamBettleInfo', raw.get('nicknameno')), ('teamBettleInfoenemy', raw.get('enemy_nick_no')))
                    for key, player in sides:
                        team_id = f"{raw.get('battle_seq')}:{player}"
                        if team_id in teams:
                            continue
                        try:
                            heroes = json.loads('{' + raw[key] + '}')['my_team']
                        except (KeyError, ValueError, TypeError):
                            continue
                        team = {h['hero_code'].split('_')[0]: h.get('position') for h in heroes}
                        # Only teams that were fielded: four heroes in slots 1-4
                        if sorted(p for p in team.values() if p) != [1, 2, 3, 4]:
                            continue
                        teams[team_id] = team
                        cache.write(json.dumps({'id': team_id, 'team': team}) + '\n')
            print(f'{server}: {len(teams)} teams so far')


def build(teams):
    heroes = {}
    pairs = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0, 0]))
    for team in teams:
        fielded = {hero: slot for hero, slot in team.items() if slot}
        for hero, slot in fielded.items():
            heroes.setdefault(hero, {'n': [0, 0, 0, 0]})['n'][slot - 1] += 1
            for mate in fielded:
                if mate != hero:
                    pairs[hero][mate][slot - 1] += 1
    for hero, entry in heroes.items():
        entry['with'] = {mate: counts for mate, counts in pairs[hero].items() if sum(counts) >= MIN_PAIR_GAMES}
    return {'teams': len(teams), 'heroes': heroes}


def evaluate(teams, test_share=0.2):
    """Hold out part of the teams and see how often the suggested arrangement matches the player's."""
    from formation import Formation
    teams = list(teams)
    random.Random(0).shuffle(teams)
    split = int(len(teams) * test_share)
    model = Formation.__new__(Formation)
    model.heroes = build(teams[split:])['heroes']
    front = back = whole = 0
    for team in teams[:split]:
        actual = {hero: slot for hero, slot in team.items() if slot}
        guess = {entry['hero']: entry['slot'] for entry in model.suggest(list(actual))}
        front += guess.get(next(h for h, s in actual.items() if s == 1)) == 1
        back += guess.get(next(h for h, s in actual.items() if s == 4)) == 4
        # The two middle slots are interchangeable
        whole += all((guess[h] in (2, 3)) == (s in (2, 3)) and (guess[h] == s or s in (2, 3)) for h, s in actual.items())
    print(f'Held-out check on {split} teams: front hero matched {front / split:.1%}, back hero {back / split:.1%}, '
          f'whole formation {whole / split:.1%} (random: 25%, 25%, 8%)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--season', help='season code (default: current season)')
    parser.add_argument('--servers', nargs='+', default=get_matches.SERVERS)
    parser.add_argument('--players', type=int, default=25, help='top players to sample per server')
    parser.add_argument('--delay', type=float, default=0.8, help='seconds between API calls')
    parser.add_argument('--build-only', action='store_true', help='no API calls: rebuild from the cache')
    args = parser.parse_args()

    season = args.season or get_matches.get_current_season(args.delay)
    cache_path = f'match_histories/positions_{season}.jsonl'
    teams = load_teams(cache_path)
    if not args.build_only:
        crawl(season, args.servers, args.players, args.delay, cache_path, teams)
    evaluate(teams.values())
    with open(OUTPUT, 'w', encoding='utf-8') as file:
        json.dump(build(teams.values()), file, separators=(',', ':'))
    print(f'{len(teams)} teams -> {OUTPUT}')
