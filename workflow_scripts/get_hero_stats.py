import pandas as pd
from collections import defaultdict

# Load your CSV data into a DataFrame
df = pd.read_csv('data/epic7_match_history.csv.gz')

# Function to calculate winrates, counters, picks, and counters against
def calculate_winrates_counters_and_counters_against(df):
    # Initialize dictionaries to store hero statistics
    hero_stats = defaultdict(lambda: {'total_matches': 0, 'fought': 0, 'fought_wins': 0, 'counters': defaultdict(int), 'picked_with': defaultdict(int), 'countered_by': defaultdict(int)})
    if 'Banned' not in df.columns:
        df = df.assign(Banned=0)

    # Group by 'Match Number' to efficiently handle enemy and team heroes
    match_groups = df.groupby('Match Number')

    # Iterate through each match, from both teams' side (counting only the crawled player's
    # side would inflate win rates, since those players are higher ranked than their opponents)
    for match_number, match_data in match_groups:
        for team, other in (('My Team', 'Enemy Team'), ('Enemy Team', 'My Team')):
            team_rows = match_data[match_data['Team'] == team]
            team_heroes = team_rows['Hero'].values
            enemy_team_heroes = match_data[match_data['Team'] == other]['Hero'].values
            team_won = (team_rows['Match Result'] == 'Win').any()

            for hero, banned in zip(team_heroes, team_rows['Banned'].values):
                hero_stats[hero]['total_matches'] += 1
                # Win rate only from games the hero actually fought (not banned out)
                if not banned:
                    hero_stats[hero]['fought'] += 1
                    hero_stats[hero]['fought_wins'] += int(team_won)

                # Update picked_with for allies and counters for enemies
                for ally in team_heroes:
                    if ally != hero:
                        hero_stats[hero]['picked_with'][ally] += 1

                for enemy in enemy_team_heroes:
                    hero_stats[hero]['counters'][enemy] += 1
                    hero_stats[enemy]['countered_by'][hero] += 1
    
    # Calculate winrates, counters, picked_with, countered_by, and pick rates per hero
    winrates = {}
    counters = {}
    picked_with = {}
    countered_by = {}
    pick_rates = {}

    total_matches = df['Match Number'].nunique()

    for hero, stats in hero_stats.items():
        if stats['fought'] > 0:
            winrates[hero] = stats['fought_wins'] / stats['fought']
        else:
            winrates[hero] = -1
        
        pick_rates[hero] = stats['total_matches'] / total_matches
        
        # Get top 3 counters (most wins against)
        counters[hero] = sorted(stats['counters'].items(), key=lambda x: -x[1])[:3]
        counters[hero] += [(-1, -1)] * (3 - len(counters[hero]))
        
        # Get top 3 best picks (most picked with)
        picked_with[hero] = sorted(stats['picked_with'].items(), key=lambda x: -x[1])[:3]
        picked_with[hero] += [(-1, -1)] * (3 - len(picked_with[hero]))
        
        # Get top 3 countered by (most countered by)
        countered_by[hero] = sorted(stats['countered_by'].items(), key=lambda x: -x[1])[:3]
        countered_by[hero] += [(-1, -1)] * (3 - len(countered_by[hero]))
    
    # Create a DataFrame to store all data
    data = []
    for hero in winrates:
        data.append({
            'Hero': hero,
            'Winrate': winrates[hero],
            'Pick Rate': pick_rates[hero],
            'Counter1': counters[hero][0][0],
            'Counter1_Wins': counters[hero][0][1],
            'Counter2': counters[hero][1][0],
            'Counter2_Wins': counters[hero][1][1],
            'Counter3': counters[hero][2][0],
            'Counter3_Wins': counters[hero][2][1],
            'Pick1': picked_with[hero][0][0],
            'Pick1_Count': picked_with[hero][0][1],
            'Pick2': picked_with[hero][1][0],
            'Pick2_Count': picked_with[hero][1][1],
            'Pick3': picked_with[hero][2][0],
            'Pick3_Count': picked_with[hero][2][1],
            'CounteredBy1': countered_by[hero][0][0],
            'CounteredBy1_Count': countered_by[hero][0][1],
            'CounteredBy2': countered_by[hero][1][0],
            'CounteredBy2_Count': countered_by[hero][1][1],
            'CounteredBy3': countered_by[hero][2][0],
            'CounteredBy3_Count': countered_by[hero][2][1]
        })
    
    df_all_info = pd.DataFrame(data)
    
    return df_all_info

# Calculate all information
df_all_info = calculate_winrates_counters_and_counters_against(df)

# How often each hero is the very first pick of a draft: openers are far more concentrated
# than picks overall, so the app suggests first picks from this instead of the pick rate
first_pick_rate = df[df['Pick Order'] == 1]['Hero'].value_counts() / df['Match Number'].nunique()
df_all_info['First Pick Rate'] = df_all_info['Hero'].map(first_pick_rate).fillna(0)

# Save to CSV
df_all_info.to_csv('data/epic7_hero_stats.csv', index=False)

# Print confirmation
print("Data saved successfully.")