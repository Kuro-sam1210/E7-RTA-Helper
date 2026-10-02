"""Collect high-ranked RTA matches into data/epic7_match_history.csv.gz.

Uses the JSON API behind https://epic7.onstove.com/en/gg (no login needed):
  - getWorldUserRankingDetail: per-server leaderboard (top 100, 10 per page)
  - getBattleList: a player's last 100 battles for a season

Players are crawled outward from every server's leaderboard: each battle names
the opponent and their rank, and opponents at --min-grade or above are queued
in turn, until --max-players have been fetched.

Outputs:
  data/epic7_match_history.csv.gz  Match Number, Pick Order (1-10, global draft order),
                                   Match Result, Team, Hero, First Pick, Banned,
                                   Rule (warfare rule, e.g. rta_openingrule_category_4)
  data/epic7_match_prebans.csv.gz  Match Number, Team, Hero (2 prebans per team)

Battles are cached in match_histories/battles_v2_<season>.jsonl, so re-running
during the season keeps adding new battles, an interrupted run resumes without
re-fetching players done that day, and the same battle seen from both players'
histories is only counted once.

Usage:
  python workflow_scripts/get_matches.py                     # current season, Champion+
  python workflow_scripts/get_matches.py --season pvp_rta_ss20 --max-players 1000
"""
import argparse
import csv
import gzip
import json
import os
import time
from collections import deque
from datetime import datetime, timezone

import requests

API_URL = 'https://e7api.onstove.com/gameApi/'
SERVERS = ['world_global', 'world_kor', 'world_asia', 'world_eu', 'world_jpn']
RANKING_PAGES = 10  # leaderboard is top 100, 10 players per page
GRADES = ['bronze', 'silver', 'gold', 'master', 'challenger', 'champion', 'warlord', 'emperor', 'legend']

# Global draft order: the first-pick team picks 1, 4-5, 8-9; the other team 2-3, 6-7, 10
FIRST_PICK_ORDER = [1, 4, 5, 8, 9]
SECOND_PICK_ORDER = [2, 3, 6, 7, 10]

session = requests.Session()
session.headers.update({
    'Content-Type': 'application/json;charset=UTF-8',
    'Origin': 'https://epic7.onstove.com',
    'Referer': 'https://epic7.onstove.com/',
    'User-Agent': 'E7-RTA-Helper data updater',
})


def call_api(endpoint, delay, retries=4, **params):
    for attempt in range(retries):
        try:
            response = session.post(API_URL + endpoint, params={'lang': 'en', **params}, timeout=30)
            data = response.json()
            if data.get('code') == 0:
                time.sleep(delay)
                return data['value']
            print(f'{endpoint} returned {data.get("code")}: {data.get("message")}')
        except (requests.RequestException, ValueError) as e:
            print(f'{endpoint} failed ({attempt + 1}/{retries}): {e}')
        time.sleep(delay * (2 ** (attempt + 1)))
    return None


def get_current_season(delay):
    seasons = call_api('getSeasonList', delay)['result_body']
    return next(s['season_code'] for s in seasons if s['is_now_season'] == 1)


def get_top_players(server, season, delay):
    players = []
    for page in range(1, RANKING_PAGES + 1):
        value = call_api('getWorldUserRankingDetail', delay, world_code=server,
                         season_code=season, current_page=page)
        if not value or not value['result_body']:
            break
        players.extend(p['nick_no'] for p in value['result_body'])
    return players


def hero_code(code):
    return code.split('_')[0]


def parse_fragment(fragment, key):
    """Several fields are JSON fragments such as '"my_team":[...]' or '"preban_list":[...]'."""
    return json.loads('{' + fragment + '}')[key]


def parse_team(team_info):
    heroes = parse_fragment(team_info, 'my_team')
    return [hero_code(h['hero_code']) for h in sorted(heroes, key=lambda h: h['pick_order'])]


def banned_hero(deck):
    return next((hero_code(h['hero_code']) for h in deck['hero_list'] if h.get('ban') == 1), None)


def parse_battle(battle):
    """Reduce an API battle to the fields we keep, or None if it is incomplete."""
    try:
        my_team = parse_team(battle['teamBettleInfo'])
        enemy_team = parse_team(battle['teamBettleInfoenemy'])
        my_prebans = [hero_code(c) for c in parse_fragment(battle['prebanList'], 'preban_list')]
        enemy_prebans = [hero_code(c) for c in parse_fragment(battle['prebanListEnemy'], 'preban_list')]
        my_deck, enemy_deck = battle['my_deck'], battle['enemy_deck']
    except (KeyError, TypeError, ValueError):
        return None
    if len(my_team) != 5 or len(enemy_team) != 5 or battle.get('iswin') not in (1, 2):
        return None

    my_first = any(h.get('first_pick') == 1 for h in my_deck['hero_list'])
    enemy_first = any(h.get('first_pick') == 1 for h in enemy_deck['hero_list'])
    if my_first == enemy_first:
        return None

    return {
        'battle_seq': battle['battle_seq'],
        'date': battle.get('battle_day'),
        'win': battle['iswin'] == 1,
        'my_first_pick': my_first,
        'my_team': my_team,
        'enemy_team': enemy_team,
        # the hero of that team that the other side banned after the draft
        'my_banned': banned_hero(my_deck),
        'enemy_banned': banned_hero(enemy_deck),
        'my_prebans': my_prebans,
        'enemy_prebans': enemy_prebans,
        'rule': battle.get('opening_rule_title'),
        'my_grade': battle.get('grade_code'),
        'enemy_grade': battle.get('enemy_grade_code'),
    }


def load_cache(path, today):
    """Cached battles, plus players already fetched today (so a later run refreshes them)."""
    battles, done_players = {}, set()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as file:
            for line in file:
                record = json.loads(line)
                if 'done_player' in record:
                    if record.get('day') == today:
                        done_players.add(record['done_player'])
                else:
                    battles.setdefault(record['battle_seq'], record)
    return battles, done_players


def write_csvs(battles, matches_path, prebans_path):
    # Written gzip-compressed (.csv.gz) to stay under GitHub's file size limit; pandas reads it directly
    with gzip.open(matches_path, 'wt', newline='', encoding='utf-8') as matches_file, \
            gzip.open(prebans_path, 'wt', newline='', encoding='utf-8') as prebans_file:
        matches = csv.DictWriter(matches_file, lineterminator='\n', fieldnames=[
            'Match Number', 'Pick Order', 'Match Result', 'Team', 'Hero', 'First Pick', 'Banned', 'Rule'])
        prebans = csv.DictWriter(prebans_file, lineterminator='\n', fieldnames=['Match Number', 'Team', 'Hero'])
        matches.writeheader()
        prebans.writeheader()
        for match_number, battle in enumerate(sorted(battles.values(), key=lambda b: b['battle_seq'])):
            sides = [('My Team', battle['my_team'], battle['win'], battle['my_first_pick'],
                      battle['my_banned'], battle['my_prebans']),
                     ('Enemy Team', battle['enemy_team'], not battle['win'], not battle['my_first_pick'],
                      battle['enemy_banned'], battle['enemy_prebans'])]
            for team, heroes, won, first, banned, team_prebans in sides:
                order = FIRST_PICK_ORDER if first else SECOND_PICK_ORDER
                for pick_order, hero in zip(order, heroes):
                    matches.writerow({
                        'Match Number': match_number,
                        'Pick Order': pick_order,
                        'Match Result': 'Win' if won else 'Loss',
                        'Team': team,
                        'Hero': hero,
                        'First Pick': int(first),
                        'Banned': int(hero == banned),
                        'Rule': battle.get('rule') or '',
                    })
                for hero in team_prebans:
                    prebans.writerow({'Match Number': match_number, 'Team': team, 'Hero': hero})
    print(f'Wrote {len(battles)} matches to {matches_path} and {prebans_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--season', help='season code, e.g. pvp_rta_ss21 (default: current season)')
    parser.add_argument('--servers', nargs='+', default=SERVERS, help='leaderboards to start the crawl from')
    parser.add_argument('--min-grade', default='champion', choices=GRADES,
                        help='only follow opponents at this rank or above')
    parser.add_argument('--max-players', type=int, default=5000, help='players to fetch per run')
    parser.add_argument('--delay', type=float, default=1.0, help='seconds between API calls')
    parser.add_argument('--output', default='data/epic7_match_history.csv.gz')
    parser.add_argument('--prebans-output', default='data/epic7_match_prebans.csv.gz')
    parser.add_argument('--csv-only', action='store_true', help='rebuild the CSVs from the cache, no API calls')
    args = parser.parse_args()

    if args.csv_only:
        season = args.season or get_current_season(args.delay)
        battles, _ = load_cache(f'match_histories/battles_v2_{season}.jsonl', None)
        write_csvs(battles, args.output, args.prebans_output)
        return

    allowed_grades = set(GRADES[GRADES.index(args.min_grade):])
    season = args.season or get_current_season(args.delay)
    cache_path = f'match_histories/battles_v2_{season}.jsonl'
    os.makedirs('match_histories', exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    battles, done_players = load_cache(cache_path, today)
    print(f'Season {season}: {len(battles)} cached matches, {len(done_players)} players done today')

    queue, queued = deque(), set()
    for server in args.servers:
        players = get_top_players(server, season, args.delay)
        print(f'{server}: {len(players)} ranked players')
        for nick_no in players:
            if nick_no not in queued:
                queue.append((nick_no, server))
                queued.add(nick_no)

    fetched = 0
    with open(cache_path, 'a', encoding='utf-8') as cache:
        while queue and fetched < args.max_players:
            nick_no, server = queue.popleft()
            if nick_no in done_players:
                continue
            value = call_api('getBattleList', args.delay, nick_no=nick_no,
                             world_code=server, season_code=season)
            fetched += 1
            if value is None:
                print(f'Skipping player {nick_no}, will retry next run')
                continue
            new = 0
            for raw in value['result_body'].get('battle_list') or []:
                if raw.get('season_code') != season:
                    continue
                opponent = raw.get('matchPlayerNicknameno')
                if opponent and opponent not in queued and raw.get('enemy_grade_code') in allowed_grades:
                    queue.append((opponent, raw.get('enemy_world_code') or server))
                    queued.add(opponent)
                battle = parse_battle(raw)
                if battle and battle['battle_seq'] not in battles:
                    battles[battle['battle_seq']] = battle
                    cache.write(json.dumps(battle) + '\n')
                    new += 1
            cache.write(json.dumps({'done_player': nick_no, 'day': today}) + '\n')
            cache.flush()
            done_players.add(nick_no)
            print(f'{fetched}/{args.max_players} ({server}): +{new} matches '
                  f'(total {len(battles)}, queue {len(queue)})')

    write_csvs(battles, args.output, args.prebans_output)


if __name__ == '__main__':
    main()
