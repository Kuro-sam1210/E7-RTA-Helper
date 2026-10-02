"""Build data/hero_code_to_name.csv and the dataset/ portrait templates.

Hero list: the official E7 hero JSON (same file epic7.onstove.com/en/gg uses).
Portraits: official hero thumbnails, with E7 Codex (https://e7codex.com) as a
fallback and as the source for skin portraits (it replaces the closed E7 Vault;
its skin faces are byte-identical to the ones previously stored here).

Each hero folder gets c.png (base) plus c_1.png, c_2.png, ... (skins), and a
horizontally flipped copy of each, which is what server.py loads for SIFT.
"""
import csv
import io
import os
import time

import requests
from PIL import Image

HERO_JSON_URL = 'https://static-pubcomm.onstove.com/gameRecord/epic7/epic7_hero.json'
OFFICIAL_PORTRAIT_URL = 'https://static-pubcomm.onstove.com/event/live/epic7/guide/images/hero/{code}_s.png'
CODEX_UNITS_URL = 'https://e7codex.com/data/units.json'
CODEX_ASSET_URL = 'https://e7codex.com/{path}'

DATASET_DIR = 'dataset'
CSV_FILE = 'data/hero_code_to_name.csv'

session = requests.Session()
session.headers['User-Agent'] = 'E7-RTA-Helper data updater'


def get(url, retries=3):
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                return response
            if response.status_code in (403, 404):
                return None
        except requests.RequestException as e:
            print(f'Request failed ({attempt + 1}/{retries}) for {url}: {e}')
        time.sleep(2)
    return None


def load_existing_names():
    if not os.path.exists(CSV_FILE):
        return {}
    with open(CSV_FILE, newline='', encoding='utf-8') as file:
        return {row['code']: row['name'] for row in csv.DictReader(file)}


def get_official_heroes():
    heroes = get(HERO_JSON_URL).json()['en']
    return {hero['code']: hero['name'] for hero in heroes}


def get_codex_portraits():
    """Map hero code -> {'base': path or None, 'skins': [paths sorted by variant]}."""
    response = get(CODEX_UNITS_URL)
    if response is None:
        print('Could not load E7 Codex units, skins will not be updated')
        return {}

    portraits = {}
    for unit in response.json():
        if unit.get('kind') != 'unit':
            continue
        code = unit['base_id'].split('_')[0]
        variant = unit.get('variant') or ''
        entry = portraits.setdefault(code, {'base': None, 'skins': []})
        # Only the plain face thumbnail; _sd (chibi emote) and _su/_l faces are not draft portraits
        face_name = f'face_{code}_{variant}_s.png' if variant else f'face_{code}_s.png'
        face = next((a for a in unit.get('artworks', []) if a.endswith('/' + face_name)), None)
        if face is None:
            continue
        if variant:
            entry['skins'].append((variant, face))
        else:
            entry['base'] = face

    for entry in portraits.values():
        entry['skins'] = [path for _, path in sorted(entry['skins'])]
    return portraits


def write_if_changed(path, content):
    if os.path.exists(path):
        with open(path, 'rb') as file:
            if file.read() == content:
                return False
    with open(path, 'wb') as file:
        file.write(content)
    return True


def save_template(hero_dir, suffix, content):
    image_path = os.path.join(hero_dir, f'c{suffix}.png')
    flipped_path = os.path.join(hero_dir, f'c{suffix}_flipped.png')
    changed = write_if_changed(image_path, content)
    if changed or not os.path.exists(flipped_path):
        with Image.open(io.BytesIO(content)) as img:
            img.transpose(Image.FLIP_LEFT_RIGHT).save(flipped_path)
    return changed


def main():
    os.makedirs(DATASET_DIR, exist_ok=True)

    existing = load_existing_names()
    official = get_official_heroes()
    codex = get_codex_portraits()

    # Keep every hero we already track, then add new ones. The official list also
    # contains alternate codes for the same hero (e.g. Mercedes c0001/c1005 vs c0002),
    # which never show up in RTA records, so skip new codes whose name we already have.
    heroes = dict(existing)
    known_names = set(existing.values())
    for code, name in official.items():
        if code in heroes:
            continue
        if name in known_names:
            print(f'Skipping duplicate hero code {code} ({name})')
            continue
        heroes[code] = name
        known_names.add(name)
        print(f'New hero: {code} - {name}')

    updated, missing = [], []
    for code in sorted(heroes):
        hero_dir = os.path.join(DATASET_DIR, code)
        os.makedirs(hero_dir, exist_ok=True)
        entry = codex.get(code, {'base': None, 'skins': []})

        response = get(OFFICIAL_PORTRAIT_URL.format(code=code))
        if response is None and entry['base']:
            response = get(CODEX_ASSET_URL.format(path=entry['base']))
        if response is None:
            if not os.path.exists(os.path.join(hero_dir, 'c.png')):
                missing.append(code)
            print(f'Failed to download portrait for {code}')
        elif save_template(hero_dir, '', response.content):
            updated.append(f'{code}/c.png')

        for i, skin_path in enumerate(entry['skins'], start=1):
            response = get(CODEX_ASSET_URL.format(path=skin_path))
            if response is None:
                print(f'Failed to download skin {skin_path}')
                continue
            if save_template(hero_dir, f'_{i}', response.content):
                updated.append(f'{code}/c_{i}.png')

    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['code', 'name'], lineterminator='\n')
        writer.writeheader()
        writer.writerows({'code': code, 'name': heroes[code]} for code in sorted(heroes))

    print(f'Saved {len(heroes)} heroes to {CSV_FILE}')
    print(f'Updated {len(updated)} portrait files')
    if missing:
        print(f'Heroes without any portrait: {missing}')


if __name__ == '__main__':
    main()
