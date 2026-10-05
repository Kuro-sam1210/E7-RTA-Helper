"""Download every hero's current kit from CeciliaBot (https://ceciliabot.github.io) -> data/hero_kits.json.

The site's API has, per hero, the skill descriptions as they are in game now, the buffs and
debuffs each skill applies, and "common" traits such as buff dispel, cleanse, AoE, Combat
Readiness push or ignoring Effect Resistance, plus a changelog of balance adjustments. That is
what the pick explanations need to say why a hero fits a draft.

Responses are cached in match_histories/kits/ so a re-run only fetches heroes whose entry
changed (updated_dt) or is missing. Use --refresh to fetch everything again, e.g. after a
balance patch.

Usage:
  python workflow_scripts/get_hero_kits.py
"""
import argparse
import json
import os
import time

import requests

API = 'https://cecilia-bot-api.vercel.app/api/v1'
CACHE_DIR = 'match_histories/kits'
OUTPUT = 'data/hero_kits.json'

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})


def get(path):
    for attempt in range(4):
        try:
            response = session.get(API + path, timeout=60)
            if response.status_code == 200:
                return response.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(5 * (attempt + 1))
    return None


def tag_ids(tags):
    return [tag['_id'] if isinstance(tag, dict) else tag for tag in tags or []]


def kit(entry):
    """The parts of a hero entry the helper uses."""
    return {
        'name': entry.get('name'), 'role': entry.get('role'), 'attribute': entry.get('attribute'),
        'buffs': tag_ids(entry.get('buff')), 'debuffs': tag_ids(entry.get('debuff')), 'traits': tag_ids(entry.get('common')),
        'updated': entry.get('updated_dt') or entry.get('created_dt') or 0,
        'changelog': entry.get('changelog') or [],
        'skills': [{
            'name': skill.get('name'), 'description': skill.get('description'), 'passive': bool(skill.get('passive')),
            'cooldown': skill.get('cooldown'), 'soulburn': skill.get('soul_description') or '',
            'buffs': tag_ids(skill.get('buff')), 'debuffs': tag_ids(skill.get('debuff')), 'traits': tag_ids(skill.get('common')),
        } for skill in entry.get('skills') or []],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--refresh', action='store_true', help='fetch every hero again')
    parser.add_argument('--delay', type=float, default=0.5, help='seconds between requests')
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    open(os.path.join('match_histories', '.gdignore'), 'a').close()
    heroes = get('/getList?list=hero')
    if not heroes:
        raise SystemExit('could not download the hero list')

    kits, fetched, failed = {}, 0, []
    for number, hero in enumerate(heroes):
        code, cache_path = hero['id'], os.path.join(CACHE_DIR, hero['id'] + '.json')
        entry = None
        if os.path.exists(cache_path) and not args.refresh:
            with open(cache_path, encoding='utf-8') as file:
                entry = json.load(file)
            # the list carries each hero's last update, so a changed kit is fetched again
            if (entry.get('updated_dt') or 0) != (hero.get('updated_dt') or 0):
                entry = None
        if entry is None:
            entry = get(f"/getItem?list=hero&id={hero['_id']}")
            time.sleep(args.delay)
            if not entry:
                failed.append(hero['name'])
                continue
            fetched += 1
            with open(cache_path, 'w', encoding='utf-8') as file:
                json.dump(entry, file, ensure_ascii=False)
            if fetched % 25 == 0:
                print(f'{number + 1}/{len(heroes)} heroes', flush=True)
        kits[code] = kit(entry)

    with open(OUTPUT, 'w', encoding='utf-8') as file:
        json.dump({'source': 'https://ceciliabot.github.io', 'heroes': kits}, file, ensure_ascii=False, separators=(',', ':'))
    print(f'{len(kits)} heroes -> {OUTPUT} ({fetched} downloaded)' + (f'; failed: {failed}' if failed else ''))
