import os
import socket
import cv2
import logging
from flask import Flask, jsonify, request

import win32gui
import numpy as np
import pandas as pd
from CaptureScreen import capture_screen

app = Flask(__name__)

# Configure logging
logging.basicConfig(filename='server.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

template_images = None
descriptor_cache = None

characters_in_match = []
positions = {}
y_coords = {}

# Draft screen layout, as fractions of the (border-cropped) capture height
TOP_BAR = 0.15         # player names and profile avatars, which are hero faces too
PREBAN_ZONE = 0.86     # the four preban icons sit below this, at the bottom centre
PREBAN_PAIR_GAP = 0.09 # icons of one side are ~0.077 apart, the two pairs ~0.105

# "BANNED" stamp drawn over a banned hero's slot after the draft
MIN_STAMP_MATCHES = 12
stamp_descriptors = None

@app.route('/set_num_threads', methods=['GET'])
def set_num_threads():
    try:
        num_threads = int(request.args.get('num_threads'))
        cv2.setNumThreads(num_threads)
        return jsonify({"message": f"Number of threads set to {num_threads}"})
    except Exception as e:
        return jsonify({"message": f"Error setting number of threads: {str(e)}"}), 500
    
def load_multiple_templates(character_folder, max_templates=3):
    templates = []
    for i in range(max_templates):
        suffix = f"_{i}" if i > 0 else ""
        normal_image_path = os.path.join(character_folder, f'c{suffix}.png')
        flipped_image_path = os.path.join(character_folder, f'c{suffix}_flipped.png')

        if os.path.exists(normal_image_path) and os.path.exists(flipped_image_path):
            normal_image = cv2.imread(normal_image_path)
            flipped_image = cv2.imread(flipped_image_path)

            if normal_image is not None and flipped_image is not None:
                normal_gray = cv2.cvtColor(normal_image, cv2.COLOR_BGR2GRAY)
                flipped_gray = cv2.cvtColor(flipped_image, cv2.COLOR_BGR2GRAY)
                templates.append((normal_gray, flipped_gray))

    return templates

def init_cache():
    global template_images, descriptor_cache
    try:
        template_images = {}
        descriptor_cache = {}

        for character in os.listdir('dataset'):
            character_folder = os.path.join('dataset', character)
            if os.path.isdir(character_folder):
                templates = load_multiple_templates(character_folder)

                if templates:
                    template_images[character] = templates
                    descriptor_cache[character] = []

                    for normal_gray, flipped_gray in templates:
                        keypoints_normal, descriptors_normal = compute_descriptors(normal_gray)
                        keypoints_flipped, descriptors_flipped = compute_descriptors(flipped_gray)
                        descriptor_cache[character].append(
                            (keypoints_normal, descriptors_normal, 
                             keypoints_flipped, descriptors_flipped)
                        )

        load_ban_stamp()
        logging.info('Cache initialized successfully')
    except Exception as e:
        logging.error(f'Error initializing cache: {str(e)}')

def load_ban_stamp():
    global stamp_descriptors
    stamp = cv2.imread('detection/banned_stamp.png', cv2.IMREAD_GRAYSCALE)
    mask = cv2.imread('detection/banned_stamp_mask.png', cv2.IMREAD_GRAYSCALE)
    if stamp is None or mask is None:
        logging.error('Ban stamp template missing, bans will not be detected')
        stamp_descriptors = None
        return
    # Only keypoints on the red stamp itself, not the hero art behind it
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    _, stamp_descriptors = cv2.SIFT_create().detectAndCompute(stamp, mask)

def good_matches(template_descriptors, target_descriptors, ratio):
    if template_descriptors is None or target_descriptors is None or len(target_descriptors) < 2:
        return []
    pairs = cv2.BFMatcher().knnMatch(template_descriptors, target_descriptors, k=2)
    return [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]

def find_ban_stamp(keypoints, descriptors, height):
    """Normalised y of the BANNED stamp among these keypoints (one half of the screen), or None."""
    good = good_matches(stamp_descriptors, descriptors, 0.75)
    if len(good) < MIN_STAMP_MATCHES:
        return None
    ys = np.array([keypoints[m.trainIdx].pt[1] for m in good])
    median = np.median(ys)
    if np.sum(np.abs(ys - median) < 0.08 * height) < MIN_STAMP_MATCHES:
        return None
    return float(median / height)

def find_prebans(band, height):
    """Prebans in the bottom band: two icons per side, ours on the left.

    The same hero can be prebanned by both sides, so each hero's matched keypoints
    are grouped into separate icons by x before splitting the icons into sides.
    """
    keypoints, descriptors = cv2.SIFT_create().detectAndCompute(band, None)
    if descriptors is None:
        return [], []

    icons = []  # (x, hero)
    for character, cached in descriptor_cache.items():
        for keypoints_normal, descriptors_normal, keypoints_flipped, descriptors_flipped in cached:
            good = good_matches(descriptors_normal, descriptors, 0.5)
            if len(good) < 4:
                good = good_matches(descriptors_flipped, descriptors, 0.5)
            if len(good) < 4:
                continue
            xs = sorted(keypoints[m.trainIdx].pt[0] for m in good)
            group = [xs[0]]
            for x in xs[1:] + [None]:
                if x is not None and x - group[-1] < PREBAN_PAIR_GAP * height / 2:
                    group.append(x)
                    continue
                if len(group) >= 3:
                    icons.append((float(np.mean(group)), character))
                group = [x]
            break

    icons.sort()
    if len(icons) >= 4:
        split = 2
    elif len(icons) == 3:
        gaps = [icons[1][0] - icons[0][0], icons[2][0] - icons[1][0]]
        split = 1 if gaps[0] > gaps[1] else 2
    elif len(icons) == 2:
        if icons[1][0] - icons[0][0] > PREBAN_PAIR_GAP * height:
            split = 1
        else:
            split = 2 if icons[1][0] < band.shape[1] / 2 else 0
    else:
        split = len([x for x, _ in icons if x < band.shape[1] / 2])
    return [hero for _, hero in icons[:split]][:2], [hero for _, hero in icons[split:]][:2]

# Preban icons are about 7% of the window height; below this height they are too small
# for the 112 px portrait templates, so the band is enlarged first
PREBAN_FULL_SIZE_HEIGHT = 1100

def find_prebans_any_size(band, height):
    """find_prebans at two zoom levels for small windows, combining what each side finds."""
    if height >= PREBAN_FULL_SIZE_HEIGHT:
        return find_prebans(band, height)
    base = PREBAN_FULL_SIZE_HEIGHT / height
    user, enemy = [], []
    # Each zoom level misses different icons, so use both
    for factor in (base, base * 1.35):
        scaled = cv2.resize(band, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        found_user, found_enemy = find_prebans(scaled, height * factor)
        user += [hero for hero in found_user if hero not in user]
        enemy += [hero for hero in found_enemy if hero not in enemy]
    return user[:2], enemy[:2]

def SIFT_feature_matching(target_gray, descriptors_target, keypoints_target, character, template_index):  
		keypoints_template_normal, descriptors_template_normal, keypoints_template_flipped, descriptors_template_flipped = descriptor_cache[character][template_index]
          
		bf = cv2.BFMatcher()
		matches = bf.knnMatch(descriptors_template_normal, descriptors_target, k=2)
		matches_flipped = bf.knnMatch(descriptors_template_flipped, descriptors_target, k=2)

		flipped = False
		good_matches = []
		for m, n in matches:
			if m.distance < 0.5 * n.distance:
				good_matches.append(m)

		min_good_matches = 4
		if len(good_matches) < min_good_matches:
			good_matches.clear()
			flipped = True
			for m, n in matches_flipped:
				if m.distance < 0.5 * n.distance:
					good_matches.append(m)

		if len(good_matches) >= min_good_matches:
			characters_in_match.append(character)

			matched_coords = [keypoints_target[m.trainIdx].pt for m in good_matches]
			avg_x = np.mean([pt[0] for pt in matched_coords])
			avg_y = np.mean([pt[1] for pt in matched_coords])

			position = 'left' if avg_x < target_gray.shape[1] / 2 else 'right'

			positions[character] = position
			y_coords[character] = avg_y
                     

def compute_descriptors(image):
		if not isinstance(image, np.ndarray):
			raise ValueError("Image must be a numpy array")
		sift = cv2.SIFT_create()
		keypoints, descriptors = sift.detectAndCompute(image, None)
		return keypoints, descriptors

@app.route('/detect_enemy', methods=['GET'])
def _test_SIFT_feature_matching():

    window_title = request.args.get('title')

    crop_top_percent = 1
    crop_bottom_percent = 1
    crop_right_percent = 1
    crop_left_percent = 1
    crop_middle = 0

    crops = request.args.get('crops')
    if crops:
        crops = crops.split(',')
        crop_top_percent, crop_bottom_percent, crop_right_percent, crop_left_percent, crop_middle = map(float, crops)


    'rta_2.jpg'
	# Capture window
    target_image = capture_screen(window_title)  # Reduce resolution

    if target_image is None:
        raise ValueError("Failed to load target image")

    height, width = target_image.shape[:2]
    crop_left = int(width * (crop_left_percent / 100))
    crop_right = int(width * (crop_right_percent / 100))
    crop_bottom = int(height * (crop_bottom_percent / 100))
    crop_top = int(height * (crop_top_percent / 100))

    target_image = target_image[crop_top:-crop_bottom, crop_left:-crop_right]
    # The app sends skip_prebans=1 once it has all four for this draft
    return jsonify(detect_draft(target_image, crop_middle, request.args.get('skip_prebans') == '1'))

def detect_draft(target_image, crop_middle=0, skip_prebans=False):
    """Heroes in each team's slots (top to bottom), banned slots and prebans on a draft screen."""
    height, width = target_image.shape[:2]

    # Prebans sit at the bottom centre, which the middle crop below removes
    user_prebans, enemy_prebans = [], []
    if not skip_prebans:
        preban_band = cv2.cvtColor(target_image[int(height * PREBAN_ZONE):], cv2.COLOR_BGR2GRAY)
        user_prebans, enemy_prebans = find_prebans_any_size(preban_band, height)

    # Crop middle
    middle = width // 2
    offset = int(width * (float(crop_middle)/100)) // 2  # 20% of the image width

    # Now crop middle
    left = target_image[:, :middle-offset]
    right = target_image[:, middle+offset:]

    # Concatenate the two parts back together
    target_image = np.concatenate((left, right), axis=1)
    target_gray = cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY)

    sift = cv2.SIFT_create()
    keypoints_target, descriptors_target = sift.detectAndCompute(target_gray, None)

    # Clear previous results
    characters_in_match.clear()
    positions.clear()
    y_coords.clear()

    for character, templates in template_images.items():
        for template_index, (normal_gray, flipped_gray) in enumerate(templates):
            SIFT_feature_matching(target_gray, descriptors_target, keypoints_target, character, template_index)

    # Only the hero slots count as picks: skip the avatars in the top bar and the prebans
    in_slots = {code for code in positions if TOP_BAR <= y_coords[code] / height < PREBAN_ZONE}
    user_team = [code for code, position in positions.items() if position == 'left' and code in in_slots]
    user_team.sort(key=lambda x: y_coords[x])
    enemy_team = [code for code, position in positions.items() if position == 'right' and code in in_slots]
    enemy_team.sort(key=lambda x: y_coords[x])

    # BANNED stamps, searched separately in each half so one cannot hide the other
    half = target_gray.shape[1] / 2
    banned_y = {}
    for side, on_side in (('user', lambda x: x < half), ('enemy', lambda x: x >= half)):
        idx = [i for i, kp in enumerate(keypoints_target) if on_side(kp.pt[0])]
        side_descriptors = descriptors_target[idx] if descriptors_target is not None and idx else None
        banned_y[side] = find_ban_stamp([keypoints_target[i] for i in idx], side_descriptors, height)

    return {
        "user_team": user_team,
        "enemy_team": enemy_team,
        # Slot heights (fraction of the screen), so a ban stamp can be matched to its slot
        "user_team_y": [y_coords[code] / height for code in user_team],
        "enemy_team_y": [y_coords[code] / height for code in enemy_team],
        "user_banned_y": banned_y['user'],
        "enemy_banned_y": banned_y['enemy'],
        "user_prebans": user_prebans,
        "enemy_prebans": enemy_prebans,
    }


@app.route('/capture_save', methods=['GET'])
def capture_save():
    try:
        window_title = request.args.get('title')

        crop_top_percent = 1
        crop_bottom_percent = 1
        crop_right_percent = 1
        crop_left_percent = 1
        crop_middle = 0
            
        image = capture_screen(window_title)

        height, width = image.shape[:2]
        crop_left = int(width * (crop_left_percent / 100))
        crop_right = int(width * (crop_right_percent / 100))
        crop_bottom = int(height * (crop_bottom_percent / 100))
        crop_top = int(height * (crop_top_percent / 100))

        target_image = image[crop_top:-crop_bottom, crop_left:-crop_right]

        # Crop middle

        height, width = target_image.shape[:2]
        middle = width // 2
        offset = int(width * (float(crop_middle)/100)) // 2  # 20% of the image width

        # Now crop middle
        left = target_image[:, :middle-offset]
        right = target_image[:, middle+offset:]

        # Concatenate the two parts back together
        target_image = np.concatenate((left, right), axis=1)
        if target_image.any():
            temp_image = target_image
            cv2.imwrite('temp.png', target_image)
            return jsonify({"message": "Image saved as temp.png successfully"})
        else:
            return jsonify({"message": "Failed to save image, Image Null"}), 500
    except Exception as e:
        return jsonify({"message": f"Error saving image: {str(e)}"}), 500

@app.route('/crop_image', methods=['GET'])
def crop_image():
    try:
        crop_top_percent = 1
        crop_bottom_percent = 1
        crop_right_percent = 1
        crop_left_percent = 1
        crop_middle = 0

        crops = request.args.get('crops')
        if crops:
            crops = crops.split(',')
            crop_top_percent, crop_bottom_percent, crop_right_percent, crop_left_percent, crop_middle = map(float, crops)

        temp_image = cv2.imread('temp.png')
        height, width = temp_image.shape[:2]
        crop_left = int(width * (crop_left_percent / 100))
        crop_right = int(width * (crop_right_percent / 100))
        crop_bottom = int(height * (crop_bottom_percent / 100))
        crop_top = int(height * (crop_top_percent / 100))

        target_image = temp_image[crop_top:-crop_bottom, crop_left:-crop_right]

        # Crop middle

        height, width = target_image.shape[:2]
        middle = width // 2
        offset = int(width * (float(crop_middle)/100)) // 2  # 20% of the image width

        # Now crop middle
        left = target_image[:, :middle-offset]
        right = target_image[:, middle+offset:]

        # Concatenate the two parts back together
        target_image = np.concatenate((left, right), axis=1)
        if target_image.any():
            cv2.imwrite('temp_cropped.png', target_image)
            return jsonify({"message": "Image cropped successfully"})
        else:
            return jsonify({"message": "Failed to crop image, Image Null"}), 500
    except Exception as e:
        return jsonify({"message": f"Error cropping image: {str(e)}"}), 500

@app.route('/get_window_titles', methods=['GET'])

def get_window_titles():
    def enum_windows_proc(hwnd, window_titles):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                window_titles.append(title)
        return True

    try:
        window_titles = []
        win32gui.EnumWindows(enum_windows_proc, window_titles)
        windows_joined = ",".join(window_titles)
        return window_titles
    except Exception as e:
        return str(e), 500


def configure_port():
    # Check if server_port.txt exists
    # Generate a new port if server_port.txt doesn't exist
    port = find_available_port()
    with open('server_port.txt', 'w') as f:
        f.write(str(port))
    print(f"Port {port} written to server_port.txt")

    return port

def find_available_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

@app.route('/init_cache', methods=['GET'])
def init_cache_route():
    try:
        init_cache()
        return jsonify({"message":len(template_images.items()) })
    except Exception as e:
          return jsonify({"message": f"Error initializing cache: {str(e)}"}),500
    
@app.route('/status', methods=['GET'])
def status():
    return jsonify({"message": "Server is running"}), 200

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
