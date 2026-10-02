"""Player lookups on the official E7 battle record site (https://epic7.onstove.com/en/gg).

Uses the same public JSON the site uses, no login or browser needed:
  - epic7_user_<server>.json: every ranked player's name and number on a server
    (a few MB; cached in cache/ and refreshed at most once a day)
  - getUserInfoSeason: a player's most used heroes this season with wins/losses
  - getBattleList: a player's last 100 battles this season
"""
import json
import os
import time

import requests

API_URL = 'https://e7api.onstove.com/gameApi/'
USER_LIST_URL = 'https://static-pubcomm.onstove.com/gameRecord/epic7/epic7_user_{world}.json'
CACHE_DIR = 'cache'
USER_LIST_MAX_AGE = 24 * 3600

# Server names as shown in the app's Set User Data page
WORLD_CODES = {'global': 'world_global', 'korea': 'world_kor', 'asia': 'world_asia',
               'europe': 'world_eu', 'japan': 'world_jpn'}

session = requests.Session()
session.headers.update({
    'Content-Type': 'application/json;charset=UTF-8',
    'Origin': 'https://epic7.onstove.com',
    'Referer': 'https://epic7.onstove.com/',
})


class PlayerNotFound(Exception):
    pass


def call_api(endpoint, **params):
    response = session.post(API_URL + endpoint, params={'lang': 'en', **params}, timeout=30)
    data = response.json()
    if data.get('code') != 0:
        raise RuntimeError(f'{endpoint} returned {data.get("code")}: {data.get("message")}')
    return data['value']


def current_season():
    seasons = call_api('getSeasonList')['result_body']
    return next(s['season_code'] for s in seasons if s['is_now_season'] == 1)


def _user_list(world):
    """The server's player list, from the cache when it is less than a day old."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    gdignore = os.path.join(CACHE_DIR, '.gdignore')  # keep Godot from importing the cache
    if not os.path.exists(gdignore):
        open(gdignore, 'w').close()

    path = os.path.join(CACHE_DIR, f'epic7_user_{world}.json')
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < USER_LIST_MAX_AGE
    if not fresh:
        try:
            # Streamed so the server sends it compressed
            with session.get(USER_LIST_URL.format(world=world), stream=True, timeout=(30, 300)) as response:
                response.raise_for_status()
                content = b''.join(response.iter_content(256 * 1024))
            json.loads(content)  # only replace the cache with a complete file
            with open(path, 'wb') as file:
                file.write(content)
        except (requests.RequestException, ValueError):
            if not os.path.exists(path):
                raise
            # Fall back to the older cached list
    with open(path, encoding='utf-8') as file:
        return json.load(file)['users']


def find_player(name, server):
    """(nick_no, world_code) for a player name, or a player number typed directly."""
    world = WORLD_CODES.get(str(server).lower())
    if world is None:
        raise PlayerNotFound(f'Unknown server: {server}')
    name = name.strip()
    try:
        users = _user_list(world)
    except (requests.RequestException, ValueError):
        users = []
    matches = [u for u in users if u['nick_nm'].lower() == name.lower()]
    if matches:
        return int(matches[0]['nick_no']), world
    if name.isdigit():
        return int(name), world
    raise PlayerNotFound(f'No ranked player named "{name}" on {server}')


def player_stats(nick_no, world, hero_names):
    """The Set User Data payload: most used heroes this season and per-hero results of recent battles."""
    season = current_season()
    season_info = call_api('getUserInfoSeason', nick_no=nick_no, world_code=world, season_code=season)['result_body']
    # New or inactive players get placeholder rows with no hero and no games
    heroes = [h for h in season_info.get('hero_list') or []
              if h.get('hero_code') and (h.get('win_score') or 0) + (h.get('lose_score') or 0) > 0]
    heroes = sorted(heroes, key=lambda h: h.get('oftenSortNo', 99))[:5]
    hero_data = [{
        'code': h['hero_code'].split('_')[0],
        'name': hero_names.get(h['hero_code'].split('_')[0], h['hero_code']),
        # Same text format the old web scraper produced, which UserStats.gd parses
        'wins': f"{h['win_score']}W",
        'losses': f"{h['lose_score']}L",
        'win_rate': f"({float(h['win_rate']):.2f}%)",
    } for h in heroes]

    character_stats = {}
    battles = call_api('getBattleList', nick_no=nick_no, world_code=world, season_code=season)['result_body']
    for battle in battles.get('battle_list') or []:
        if battle.get('iswin') not in (1, 2):
            continue
        result = 'wins' if battle['iswin'] == 1 else 'losses'
        team = json.loads('{' + battle['teamBettleInfo'] + '}')['my_team']
        for hero in team:
            code = hero['hero_code'].split('_')[0]
            stats = character_stats.setdefault(code, {'wins': 0, 'losses': 0})
            stats[result] += 1

    return {
        'hero_data': hero_data,
        'character_stats': character_stats,
        'player_has_data': bool(hero_data or character_stats),
    }
