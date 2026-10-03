import os
import socket
import cv2
import logging
from flask import Flask, jsonify, request

import numpy as np
import win32gui
import pandas as pd
from CaptureScreen import capture_screen

import time
import e7_api

# recommender imports
from tensorflow.keras.preprocessing.sequence import pad_sequences
import pickle
import tensorflow as tf
from attention import Attention
import ast
from win_model import WinModel

# For updating
from packaging.version import Version
import json
import requests
import git
import shutil
import os
import stat
from os import path

app = Flask(__name__)

# Configure logging
logging.basicConfig(filename='server.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Where data updates come from (the maintained fork of SamTheCoder777/E7-RTA-Helper)
UPDATE_REPO = 'Kuro-sam1210/E7-RTA-Helper'
UPDATE_BRANCH = 'main'

def fetch_json_from_github():
    url = f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}/versions.json"
    response = requests.get(url)
    
    if response.status_code == 200:
        json_data = response.json()  # Parse the response as JSON
        return json_data
    else:
        raise Exception(f"Failed to fetch file from GitHub. Status code: {response.status_code}")
    
def update():
    repo_url = f'https://github.com/{UPDATE_REPO}.git'
    clone_dir = './repo'
    folders_to_move = ['CharacterUI', 'dataset', 'data', 'detection']
    destination = './'

    if os.path.exists(clone_dir):
        for root, dirs, files in os.walk(clone_dir):
            for dir in dirs:
                os.chmod(path.join(root, dir), stat.S_IRWXU)
            for file in files:
                os.chmod(path.join(root, file), stat.S_IRWXU)
        shutil.rmtree(clone_dir)

    # Download only the latest version of the data folders, not the whole repository
    # (which includes ~1 GB of bundled Python)
    try:
        repo = git.Repo.clone_from(repo_url, clone_dir, depth=1, branch=UPDATE_BRANCH,
                                   multi_options=['--filter=blob:none', '--no-checkout'])
        repo.git.sparse_checkout('set', '--no-cone', *[f'/{folder}/' for folder in folders_to_move])
        repo.git.checkout(UPDATE_BRANCH)
    except git.GitCommandError as e:
        # sparse-checkout --no-cone needs Git 2.35+; older Git downloads the whole latest version
        logging.error(f"Sparse update failed ({e}), downloading the full latest version instead")
        shutil.rmtree(clone_dir, ignore_errors=True)
        git.Repo.clone_from(repo_url, clone_dir, depth=1, branch=UPDATE_BRANCH)

    for folder in folders_to_move:
        # Full path of the folder to move
        folder_path = os.path.join(clone_dir, folder)

        # Destination path where the folder will be moved
        dest_path = os.path.join(destination, folder)

        # Remove destination folder if it exists (overwrite)
        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)

        # Move the folder to the destination
        shutil.move(folder_path, destination)
    
    # Delete the repo
    for root, dirs, files in os.walk(clone_dir):  
            for dir in dirs:
                os.chmod(path.join(root, dir), stat.S_IRWXU)
            for file in files:
                os.chmod(path.join(root, file), stat.S_IRWXU)
    shutil.rmtree(clone_dir)


@app.route('/check_update', methods=['GET'])
def check_update():
    try:
        server_json = fetch_json_from_github()

        server_data_version = server_json['data_version']
        server_program_version = server_json['program_version']

        #open versions.json
        with open('versions.json') as f:
            data = json.load(f)
            current_data_version = data['data_version']
            current_program_version = data['program_version']
            

        # Convert strings to Version objects
        current_data_version_obj = Version(current_data_version)
        server_data_version_obj = Version(server_data_version)

        current_program_version_obj = Version(current_program_version)
        server_program_version_obj = Version(server_program_version)

        is_data_updated = False
        is_program_updated = False

        # Compare the versions
        if current_data_version_obj < server_data_version_obj:
            print(f"New version: {server_data_version}is found. Updating...")
            
            update()

            data['data_version'] = server_data_version
            with open('versions.json', 'w') as f:
                json.dump(data, f)
            
            is_data_updated = True
        else:
            print(f"{current_data_version} is up to date")

        if current_program_version_obj < server_program_version_obj:
            print(f"New program version: {server_program_version}is found. Updating...")
            is_program_updated = True
        
        return jsonify({"data_updated": is_data_updated, "program_updated": is_program_updated}), 200
    
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return 'Error could not check for update', 500

@app.route('/search', methods=['GET'])
def search():
    """Set User Data: a player's most used heroes this season and results of their recent battles.

    Params: name (in-game nickname, or player number) and server (Global, Korea, Asia, Europe, Japan).
    """
    try:
        nick_no, world = e7_api.find_player(request.args.get('name', ''), request.args.get('server', ''))
        hero_names = dict(pd.read_csv('data/hero_code_to_name.csv').values)
        return jsonify(e7_api.player_stats(nick_no, world, hero_names))
    except e7_api.PlayerNotFound as e:
        return jsonify({"message": f"Error: {str(e)}"}), 404
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({"message": f"Error: {str(e)}"}), 500


# Function to recommend a hero
win_rates = {}

@app.route('/init_recommender', methods=['GET'])
def init_recommender():
    global type_encoder, hero_encoder, max_sequence_length, model, hero_types, hero_type_dict, available_heroes, most_picked, win_model, rule_encoder
    try:
        # Optional win model (win bar and ban suggestions); picks still work without it
        try:
            win_model = WinModel.load_if_available()
        except Exception as e:
            logging.error(f"Could not load win model: {str(e)}")
            win_model = None

        with open('data/rec_variables.pkl', 'rb') as f:
            variables = pickle.load(f)
        # Newer models also take the warfare rule (a fourth, optional entry)
        type_encoder, hero_encoder, max_sequence_length = variables[:3]
        rule_encoder = variables[3] if len(variables) > 3 else None
        model = tf.keras.models.load_model('data/rec_model.h5', custom_objects={'Attention': Attention})
        hero_types = pd.read_csv('data/hero_types.csv')
        hero_types['type_list'] = hero_types['type'].apply(ast.literal_eval)

        # Before the first pick there is nothing for the model to read, so suggest the most
        # common openers in order (first picks are far more concentrated than picks overall;
        # older stats files without the column fall back to the overall pick rate)
        most_picked = pd.read_csv('data/epic7_hero_stats.csv')
        opener_column = 'First Pick Rate' if 'First Pick Rate' in most_picked.columns else 'Pick Rate'
        most_picked = most_picked.sort_values(by=opener_column, ascending=False)
        most_picked = most_picked['Hero'].values[:50]

        # Transform type_list and handle multiple columns
        encoded_types = type_encoder.transform(hero_types['type_list'].tolist())
        encoded_columns = [f'encoded_type_{i}' for i in range(encoded_types.shape[1])]
        hero_types[encoded_columns] = pd.DataFrame(encoded_types, index=hero_types.index)

        # Precompute a dictionary for fast lookup
        hero_type_dict = dict(zip(hero_types['code'], encoded_types))
        hero_type_dict['unknown'] = type_encoder.transform([['Unknown']])[0]
        
        # check available heroes and store in dictionary as key
        available_heroes = {key: None for key in hero_encoder.classes_}

        # Use model.predict to initialize the model
        predict_next_hero(['unknown'], ['unknown'], 'My Team')

        return jsonify({"message": "Recommender model initialized successfully"}), 200

    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({"message": f"Error: {str(e)}"}), 500
    
def process_picks(first_team_picks, non_first_team_picks):
    # Define the maximum picks allowed at each stage based on the first team's picks
    max_non_first_team_picks = [0, 2, 2, 4, 4, 5]
    max_first_team_picks = [1, 1, 3, 3, 5, 5, 5]

    len_first_team_picks = len(first_team_picks)
    len_non_first_team_picks = len(non_first_team_picks)

    # Limit the non-first team's picks according to the first team's picks
    if len_first_team_picks < 6:
        non_first_team_picks = non_first_team_picks[:max_non_first_team_picks[len_first_team_picks]]

    # Limit the first team's picks according to the non-first team's picks
    if len_non_first_team_picks < 6:
        first_team_picks = first_team_picks[:max_first_team_picks[len_non_first_team_picks]]

    # Ensure both lists have a maximum of 6 elements
    first_team_picks = first_team_picks[:5]
    non_first_team_picks = non_first_team_picks[:5]

    return first_team_picks, non_first_team_picks

def predict_next_hero(enemy_team_picks, user_team_picks, first_pick_team, prebans=(), rule=None):
    # Picks as detected, before heroes the pick model does not know become 'unknown'
    win_model_teams = ([h for h in user_team_picks if h][:5], [h for h in enemy_team_picks if h][:5])
    combined_sequence = []
    combined_types = []
    first_pick_index = [0, 3, 4, 7, 8]
    enemy_index = 0
    user_index = 0

    # Filter out unavailable heroes
    for i, hero in enumerate(user_team_picks):
        if hero not in available_heroes.keys():
            print(f"Hero {hero} not found in available heroes. Removing from user picks.")
            user_team_picks[i] = 'unknown'
            
    for i, hero in enumerate(enemy_team_picks):
        if hero not in available_heroes.keys():
            print(f"Hero {hero} not found in available heroes. Removing from enemy picks.")
            enemy_team_picks[i] = 'unknown'

    # When the first-pick team has not picked yet, return the most common openers
    if first_pick_team == 'My Team' and len(user_team_picks) == 0:
        most_picks = [h for h in most_picked if h not in prebans][:10]
        return jsonify({
        'top_10_heroes': most_picks,
        'win_prediction': str(0.5)
        }), 200

    elif first_pick_team == 'Enemy Team' and len(enemy_team_picks) == 0:
        most_picks = [h for h in most_picked if h not in prebans][:10]
        return jsonify({
        'top_10_heroes': most_picks,
        'win_prediction': str(0.5)
        }), 200

    # Get only the first 5 in enemy and user picks
    enemy_team_picks = enemy_team_picks[:5]
    user_team_picks = user_team_picks[:5]

    # Determine the pick limits based on who picks first
    if first_pick_team == 'My Team':
        user_team_picks, enemy_team_picks = process_picks(user_team_picks, enemy_team_picks)
    else:
        enemy_team_picks, user_team_picks = process_picks(enemy_team_picks, user_team_picks)
    
    
    # Vectorized and Precomputed Lookup
    if first_pick_team == 'My Team':
        for i in range(len(user_team_picks) + len(enemy_team_picks)):
            if i in first_pick_index:
                combined_sequence.append(user_team_picks[user_index])
                combined_types.append(hero_type_dict[user_team_picks[user_index]])
                #print(f"User :" + hero_type_dict[user_team_picks[user_index]].as_string())
                user_index += 1
            else:
                combined_sequence.append(enemy_team_picks[enemy_index])
                combined_types.append(hero_type_dict[enemy_team_picks[enemy_index]])
                #print(f"Enemy :" + hero_type_dict[enemy_team_picks[enemy_index]].as_string())
                enemy_index += 1
    else:
        for i in range(len(user_team_picks) + len(enemy_team_picks)):
            if i in first_pick_index:
                combined_sequence.append(enemy_team_picks[enemy_index])
                combined_types.append(hero_type_dict[enemy_team_picks[enemy_index]])
                #print(f"Enemy :" + hero_type_dict[enemy_team_picks[enemy_index]].as_string())
                enemy_index += 1
            else:
                combined_sequence.append(user_team_picks[user_index])
                combined_types.append(hero_type_dict[user_team_picks[user_index]])
                #print(f"User :" + hero_type_dict[user_team_picks[user_index]].as_string())
                user_index += 1

    picks_sequence_encoded = hero_encoder.transform(combined_sequence)
    padded_sequence = pad_sequences([picks_sequence_encoded], maxlen=max_sequence_length, padding='pre')

    # Per-pick sequences built exactly like get_rec_model.py's training examples, from the
    # picks made so far (right-aligned, zero-padded):
    #   team:            1 = our pick, 0 = enemy pick (LabelEncoder order: 'Enemy Team', 'My Team')
    #   first pick:      1 if the pick belongs to the first-pick team
    #   first pick win:  1 on the first-pick team's picks when that team is us, i.e. the
    #                    suggestions are conditioned on our team winning
    user_is_first = first_pick_team == 'My Team'
    pick_count = len(combined_sequence)
    is_first_team = np.array([i in first_pick_index for i in range(pick_count)])
    full_pick_order_sequence = np.arange(1, pick_count + 1)
    full_team_sequence = (is_first_team == user_is_first).astype(int)
    first_pick_sequence = is_first_team.astype(int)
    first_pick_win_sequences = (is_first_team & user_is_first).astype(int)

    # Ensure that the sequences do not contain any out-of-range indices before padding
    padded_sequence = np.clip(padded_sequence, 0, len(hero_encoder.classes_) - 1)
    full_pick_order_sequence = np.clip(full_pick_order_sequence, 0, max_sequence_length - 1)
    combined_types = [np.clip(seq, 0, 1) for seq in combined_types]  # Assuming combined_types are multi-hot vectors

    padded_order_sequence = pad_sequences([full_pick_order_sequence], maxlen=max_sequence_length, padding='pre')
    padded_team_sequence = pad_sequences([full_team_sequence], maxlen=max_sequence_length, padding='pre')
    padded_first_pick_sequence = pad_sequences([first_pick_sequence], maxlen=max_sequence_length, padding='pre')
    padded_types_sequence = pad_sequences([combined_types], maxlen=max_sequence_length, padding='pre', dtype=object, value=[0]*len(type_encoder.classes_))
    padded_types_sequence = np.array([np.stack(x) for x in padded_types_sequence], dtype=np.float32)
    X_first_pick_wins = pad_sequences([first_pick_win_sequences], maxlen=max_sequence_length, padding='pre')
    
    print(f"Max sequence length: {max_sequence_length}")

    print("Shapes before filtering:")
    print("padded_sequence:", padded_sequence.shape)
    print("padded_order_sequence:", padded_order_sequence.shape)
    print("padded_team_sequence:", padded_team_sequence.shape)
    print("padded_first_pick_sequence:", padded_first_pick_sequence.shape)
    print("padded_types_sequence:", padded_types_sequence.shape)

    valid_indices = np.all(padded_order_sequence < max_sequence_length, axis=1)
    padded_sequence = padded_sequence[valid_indices]
    padded_order_sequence = padded_order_sequence[valid_indices]
    padded_team_sequence = padded_team_sequence[valid_indices]
    padded_first_pick_sequence = padded_first_pick_sequence[valid_indices]
    padded_types_sequence = padded_types_sequence[valid_indices]

    print("Shapes after filtering:")
    print("padded_sequence:", padded_sequence.shape)
    print("padded_order_sequence:", padded_order_sequence.shape)
    print("padded_team_sequence:", padded_team_sequence.shape)
    print("padded_first_pick_sequence:", padded_first_pick_sequence.shape)
    print("padded_types_sequence:", padded_types_sequence.shape)
    
    model_inputs = [padded_sequence, padded_order_sequence, padded_team_sequence, padded_first_pick_sequence, padded_types_sequence, X_first_pick_wins]
    # Models trained with the warfare rule take it as a seventh input
    if len(model.inputs) > len(model_inputs):
        known_rule = rule if rule_encoder is not None and rule in rule_encoder.classes_ else 'unknown'
        model_inputs.append(np.array([[rule_encoder.transform([known_rule])[0] if rule_encoder is not None else 0]]))
    prediction, win_prediction = model.predict(model_inputs)

    # Picked and prebanned heroes (prebans remove a hero for both players) cannot be suggested
    combined_hero_indices = set(picks_sequence_encoded)
    combined_hero_indices.update(hero_encoder.transform([h for h in prebans if h in available_heroes]))
    top_10_indices = np.argsort(prediction[0])[::-1]
    filtered_top_10_indices = [idx for idx in top_10_indices if idx not in combined_hero_indices][:10]

    top_10_heroes = hero_encoder.inverse_transform(filtered_top_10_indices)

    # Our win rate: from the win model when available, else the pick model's own win output
    if win_model is not None:
        user_win = win_model.win_rate(*win_model_teams, first_pick_team == 'My Team', rule)
    else:
        user_win = win_prediction[0][0] if first_pick_team == 'My Team' else 1.0 - win_prediction[0][0]

    # if both are full, return only win prediction
    if len(user_team_picks) >= 5 and len(enemy_team_picks) >= 5:
        return jsonify({
        'top_10_heroes': [],
        'win_prediction': str(user_win)
        }), 200

    return jsonify({
        'top_10_heroes': top_10_heroes.tolist(),
        'win_prediction': str(user_win)
    }), 200

@app.route('/recommend', methods=['GET'])
def recommend_characters():
    try:
        recommendations = []
        try:
            enemy_picks = request.args.get('enemy_picks')
            # An empty parameter means no picks yet, not one unknown pick
            enemy_picks = [h for h in enemy_picks.split(',') if h]
            user_picks = request.args.get('user_picks')
            user_picks = [h for h in user_picks.split(',') if h]
            first_pick_team = request.args.get('first_pick_team')
        except Exception:
            return jsonify({"message": "Please provide enemy_picks and user_picks and first_pick_team"}), 400
        
        prebans =[h for h in request.args.get('prebans', '').split(',') if h]
        result = predict_next_hero(enemy_picks, user_picks, first_pick_team, prebans, request.args.get('rule'))
        return result
    
    except Exception as e:
        print('Error on recommend: ', str(e))
        logging.error(f"Error: {str(e)}")
        return jsonify({"message": f"Error: {str(e)}"}), 500


win_model = None
rule_encoder = None

@app.route('/recommend_ban', methods=['GET'])
def recommend_ban():
    """Ban suggestions once both teams have 5 picks.

    Params: user_picks, enemy_picks (comma separated), first_pick_team ('My Team' or 'Enemy Team'),
    optional rule (e.g. rta_openingrule_category_4), user_banned and enemy_banned once known.
    """
    if win_model is None:
        return jsonify({"message": "Win model is not available"}), 503
    try:
        user_picks = [h for h in request.args.get('user_picks', '').split(',') if h]
        enemy_picks = [h for h in request.args.get('enemy_picks', '').split(',') if h]
        user_first_pick = request.args.get('first_pick_team') == 'My Team'
        result = win_model.recommend_bans(
            user_picks[:5], enemy_picks[:5], user_first_pick,
            rule=request.args.get('rule'),
            user_banned=request.args.get('user_banned'),
            enemy_banned=request.args.get('enemy_banned'))
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({"message": f"Error: {str(e)}"}), 500


@app.route('/status', methods=['GET'])
def status():
    return jsonify({"message": "Server is running"}), 200

def configure_port():
    # Check if server_port.txt exists
    # Generate a new port if server_port.txt doesn't exist
    port = find_available_port()
    with open('search_server_port.txt', 'w') as f:
        f.write(str(port))
    print(f"Port {port} written to search_server_port.txt")
    return port

def find_available_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    
@app.get('/shutdown')
def shutdown():
    #shutdown_server()
    os.kill(os.getpid(), 9)
    return jsonify({"message": "Server shutting down"}), 200

if __name__ == '__main__':
    port = configure_port()
    print(f"Starting server on port {port}")
    logging.info(f"Starting server on port {port}")
    app.run(host='127.0.0.1', port=port)
