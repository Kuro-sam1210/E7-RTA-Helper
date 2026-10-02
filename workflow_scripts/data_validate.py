import pandas as pd
import logging
import json
from packaging.version import Version
logging.basicConfig(filename="workflow_scripts/readme.md", level=logging.INFO)


valid_group = []


def validate_matches():
    # Load the data
    matches = pd.read_csv('data/epic7_match_history.csv.gz')

    # Same checks as before, computed for all matches at once (a per-match loop takes
    # far too long at hundreds of thousands of matches)
    per_match = matches.groupby('Match Number').agg(
        picks=('Pick Order', 'nunique'),
        heroes=('Hero', 'nunique'),
        mine=('Team', lambda t: (t == 'My Team').sum()),
        enemy=('Team', lambda t: (t == 'Enemy Team').sum()))
    checks = {
        'does not have 10 heroes': per_match['picks'] != 10,
        'has a duplicate character': per_match['heroes'] != per_match['picks'],
        'does not have 5 characters on each teams': (per_match['mine'] != 5) | (per_match['enemy'] != 5),
    }
    invalid = pd.Series(False, index=per_match.index)
    for reason, failed in checks.items():
        for match in per_match.index[failed]:
            logging.error(f'Removing: Match {match} {reason}!\n')
        invalid |= failed

    #now save the valid groups only
    if invalid.any():
        matches = matches[~matches['Match Number'].isin(per_match.index[invalid])]
        matches.to_csv('data/epic7_match_history.csv.gz', index=False)

print('Running validation checks!')
open('workflow_scripts/readme.md', 'w').close()

logging.info('Validating matches...\n')
validate_matches()
logging.info('Validating matches complete!\n')

# Update versions.json
with open('versions.json', 'r+') as f:
    data = json.load(f)
    current_version = data['data_version']
    current_version_obj = Version(current_version)
    current_version_list = list(current_version_obj.release)
    current_version_list[-1] += 1
    data['data_version'] = '.'.join(map(str, current_version_list))
    print(data)
    f.seek(0)
    json.dump(data, f)
    f.truncate()