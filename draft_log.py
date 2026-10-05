"""A local record of the drafts the helper has seen, for reviewing games afterwards.

search_server.py appends one line to my_drafts.jsonl each time the app asks for suggestions or
ban advice: the draft so far, what was suggested and the win estimates. The file is personal and
gitignored. load_drafts() groups those lines back into drafts. Results are not known to the app
unless the player clicks Won or Lost afterwards ("result" events); otherwise a review matches
drafts to the official battle records by their ten heroes.
"""
import json
import time

LOG_FILE = 'my_drafts.jsonl'


def log_event(kind, **fields):
    """Append one event; logging must never break a suggestion."""
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as file:
            file.write(json.dumps({'time': round(time.time(), 1), 'kind': kind, **fields}) + '\n')
    except (OSError, TypeError, ValueError):
        pass


def load_events(path=LOG_FILE):
    events = []
    try:
        with open(path, encoding='utf-8') as file:
            for line in file:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return events


def continues(previous, event):
    """Is this event a later moment of the same draft as the previous one?"""
    if previous['source'] != event['source'] or previous['first_pick_team'] != event['first_pick_team']:
        return False
    for side in ('user_picks', 'enemy_picks'):
        earlier, later = previous[side], event[side]
        if later[:len(earlier)] != earlier:
            return False
    return True


def load_drafts(path=LOG_FILE, source=None):
    """Drafts in the order they were seen: the final state plus every step that led to it."""
    drafts = []
    for event in load_events(path):
        if source and event.get('source') != source:
            continue
        if event['kind'] == 'result':
            # Clicked after the game, when a newer draft may already be under way: goes with
            # the latest draft of those ten heroes
            match = next((d for d in reversed(drafts) if d['steps'][-1]['user_picks'] == event['user_picks']
                          and d['steps'][-1]['enemy_picks'] == event['enemy_picks']), None)
            if match:
                match['steps'].append(event)
            continue
        if drafts and continues(drafts[-1]['steps'][-1], event):
            drafts[-1]['steps'].append(event)
        else:
            drafts.append({'steps': [event]})
    for draft in drafts:
        last = next(step for step in reversed(draft['steps']) if step['kind'] != 'result')
        bans = [step for step in draft['steps'] if step['kind'] == 'ban']
        draft.update(started=draft['steps'][0]['time'], source=last['source'], rule=last.get('rule') or '',
                     first_pick_team=last['first_pick_team'], user_picks=last['user_picks'],
                     enemy_picks=last['enemy_picks'],
                     prebans=max((step.get('prebans') or [] for step in draft['steps']), key=len),
                     user_banned=next((step['user_banned'] for step in reversed(bans) if step.get('user_banned')), None),
                     enemy_banned=next((step['enemy_banned'] for step in reversed(bans) if step.get('enemy_banned')), None),
                     result=next((step['result'] for step in reversed(draft['steps']) if step['kind'] == 'result'), None),
                     complete=len(last['user_picks']) == 5 and len(last['enemy_picks']) == 5)
    return drafts
