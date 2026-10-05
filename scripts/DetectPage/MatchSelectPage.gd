extends Node

var http_request: HTTPRequest
var misc_http_request: HTTPRequest
var ban_http_request: HTTPRequest
var thread: Thread

@onready
var EnemyPortraits = $CanvasLayer/MatchSelect/Container/ColorRect/MarginContainer2/RealTimeEnemyDetection/EnemyPortraits

@onready 
var UserPortraits = $CanvasLayer/MatchSelect/Container/ColorRect/MarginContainer2/RealTimeEnemyDetection/UserPortraits

@onready
var EnemyPickStats = $CanvasLayer/EnemyPickStats

var DetectOutput = {}
var port
var misc_port

# Check if you can make a request
var request_done = GlobalVars.request_done

# Check if you can ask for a recommendation
var can_ask_rec = true

# Check who is first pick
var is_user_first_pick = true

# Warfare rule of the match, e.g. rta_openingrule_category_4 ("" if not chosen)
var rule = ""

# Teams sent with the last recommendation request (comma separated codes)
var last_user_team = ""
var last_enemy_team = ""

# Draft memory: prebans, each team once all 5 were seen (with slot heights), and bans
var prebans = []
var full_user_team = []
var full_user_y = []
var full_enemy_team = []
var full_enemy_y = []
var user_banned = ""
var enemy_banned = ""
var draft_had_picks = false

# Frame noise: a draft only ends after several empty frames in a row, and teams are held
# through frames that lose heroes (transition animations, the splash art on the enemy's turn)
const EMPTY_FRAMES_TO_END_DRAFT = 3
const DETECTION_RETRY_DELAY_MS = 2000
var detection_retry_at = 0
var empty_frames = 0
var held_user_team = []
var held_user_y = []
var held_enemy_team = []
var held_enemy_y = []

# Check if paused
var paused = false

# Manual input: the draft is entered by hand in the picker instead of read from the screen
const ManualPicker = preload("res://scripts/DetectPage/ManualPicker.gd")
# Which of the ten picks belong to the first-pick team
const FIRST_PICK_TURNS = [true, false, false, true, true, false, false, true, true, false]
var manual_mode = false
var manual_picker
# One line under the title: where to stand each hero once the draft is complete
var formation_label: Label
# Won / Lost buttons for the last completed draft; they stay until used, since the result is
# only known after the draft has left the screen
var result_box: HBoxContainer
var result_label: Label
var result_http_request: HTTPRequest
var last_draft = {}
# Changes with every new draft, so the server's draft log can tell drafts apart
var draft_id = ""
var manual_user_team = []
var manual_enemy_team = []
var manual_history = [] # [target, hero, previously banned hero] per entry, for undo
# Ask for a recommendation even though the teams did not change (first pick, rule, bans)
var rec_forced = false

# Crop values
var CropTopValue = 1
var CropBotValue = 1
var CropRightValue = 1
var CropLeftValue = 1
var CropCenterValue = 0
var title = ""

# User Data
var user_data = {}

# Check if team changed
var old_user_team = []
var old_enemy_team = []

func _ready():
	"""
	GlobalVars.user_data = { "character_stats": { "c1117": { "losses": 1, "wins": 0 }, "c1134": { "losses": 0, "wins": 1 }, "c1144": { "losses": 0, "wins": 1 }, "c1151": { "losses": 1, "wins": 2 }, "c1156": { "losses": 0, "wins": 4 }, "c1159": { "losses": 1, "wins": 2 }, "c2008": { "losses": 1, "wins": 1 }, "c2016": { "losses": 1, "wins": 5 }, "c2039": { "losses": 1, "wins": 2 }, "c2042": { "losses": 2, "wins": 6 }, "c2066": { "losses": 0, "wins": 2 }, "c2090": { "losses": 3, "wins": 5 }, "c2109": { "losses": 1, "wins": 2 }, "c2111": { "losses": 0, "wins": 1 }, "c5082": { "losses": 1, "wins": 1 }, "c6037": { "losses": 1, "wins": 0 }, "c6062": { "losses": 1, "wins": 0 } }, "hero_data": [{ "code": "c1159", "losses": "184L", "name": "Laia", "win_rate": "(71.29%)", "wins": "457W" }, { "code": "c2090", "losses": "169L", "name": "Death Dealer Ray", "win_rate": "(71.88%)", "wins": "432W" }, { "code": "c2008", "losses": "157L", "name": "Crimson Armin", "win_rate": "(71.25%)", "wins": "389W" }, { "code": "c2042", "losses": "154L", "name": "Ambitious Tywin", "win_rate": "(71.32%)", "wins": "383W" }, { "code": "c2016", "losses": "118L", "name": "Abyssal Yufine", "win_rate": "(74.68%)", "wins": "348W" }], "player_has_data": true }	
	var test = { "character_stats": { "c1117": { "losses": 1, "wins": 0 }, "c1134": { "losses": 0, "wins": 1 }, "c1144": { "losses": 0, "wins": 1 }, "c1151": { "losses": 1, "wins": 2 }, "c1156": { "losses": 0, "wins": 4 }, "c1159": { "losses": 1, "wins": 2 }, "c2008": { "losses": 1, "wins": 1 }, "c2016": { "losses": 1, "wins": 5 }, "c2039": { "losses": 1, "wins": 2 }, "c2042": { "losses": 2, "wins": 6 }, "c2066": { "losses": 0, "wins": 2 }, "c2090": { "losses": 3, "wins": 5 }, "c2109": { "losses": 1, "wins": 2 }, "c2111": { "losses": 0, "wins": 1 }, "c5082": { "losses": 1, "wins": 1 }, "c6037": { "losses": 1, "wins": 0 }, "c6062": { "losses": 1, "wins": 0 } }, "hero_data": [{ "code": "c1159", "losses": "184L", "name": "Laia", "win_rate": "(71.29%)", "wins": "457W" }, { "code": "c2090", "losses": "169L", "name": "Death Dealer Ray", "win_rate": "(71.88%)", "wins": "432W" }, { "code": "c2008", "losses": "157L", "name": "Crimson Armin", "win_rate": "(71.25%)", "wins": "389W" }, { "code": "c2042", "losses": "154L", "name": "Ambitious Tywin", "win_rate": "(71.32%)", "wins": "383W" }, { "code": "c2016", "losses": "118L", "name": "Abyssal Yufine", "win_rate": "(74.68%)", "wins": "348W" }], "player_has_data": true }
	var test_arr = test['character_stats']
	$CanvasLayer/UserPickData.emit_signal('show_counters', 'c6062')
	$CanvasLayer/UserPickData.emit_signal('show_synergies', 'c0002')
	$CanvasLayer/UserPickData.emit_signal('show_recommendation', ['c1117', 'c1134', 'c2066', 'c0002', 'c1001', 'c1004'])
	
	$CanvasLayer/EnemyPickStats.emit_signal('char_picked','c1117')
	$CanvasLayer/UserStats.emit_signal('_update_most_picks', GlobalVars.recommend_top_characters(test_arr))
	$CanvasLayer/UserStats.emit_signal('_update_recent_picks')
	"""
	
	# make http request for character detection
	http_request = HTTPRequest.new()
	add_child(http_request)
	http_request.request_completed.connect(self._on_detection_completed)

	# make http request for misc server
	misc_http_request = HTTPRequest.new()
	add_child(misc_http_request)
	misc_http_request.request_completed.connect(self._on_misc_server_completed)

	# make http request for post-draft ban suggestions
	ban_http_request = HTTPRequest.new()
	add_child(ban_http_request)
	ban_http_request.request_completed.connect(self._on_ban_suggestions_completed)

	# Manual input: a toggle in the top right corner, and the picker over the user stats
	var manual_toggle = CheckButton.new()
	manual_toggle.text = "Manual input"
	manual_toggle.anchor_left = 0.78
	manual_toggle.anchor_top = 0.015
	manual_toggle.anchor_right = 0.968
	manual_toggle.anchor_bottom = 0.045
	manual_toggle.toggled.connect(self._on_manual_toggled)
	$CanvasLayer.add_child(manual_toggle)

	manual_picker = ManualPicker.new()
	manual_picker.visible = false
	manual_picker.anchor_left = 0.04
	manual_picker.anchor_top = 0.085
	manual_picker.anchor_right = 0.968
	manual_picker.anchor_bottom = 0.437
	manual_picker.hero_chosen.connect(self._on_manual_hero_chosen)
	manual_picker.undo_pressed.connect(self._on_manual_undo)
	manual_picker.next_pressed.connect(self._on_manual_next)
	# In manual input, clicking a suggestion enters it
	$CanvasLayer/UserPickData.hero_clicked.connect(self._on_suggestion_clicked)
	manual_picker.clear_pressed.connect(self._on_manual_clear)
	$CanvasLayer.add_child(manual_picker)
	$CanvasLayer.move_child(manual_picker, $CanvasLayer/PauseScreen.get_index())

	result_http_request = HTTPRequest.new()
	add_child(result_http_request)
	result_box = HBoxContainer.new()
	result_box.visible = false
	result_box.anchor_left = 0.09
	result_box.anchor_top = 0.012
	result_box.anchor_right = 0.34
	result_box.anchor_bottom = 0.048
	result_label = Label.new()
	result_label.text = "Last game:"
	result_label.add_theme_font_size_override("font_size", 13)
	result_box.add_child(result_label)
	for outcome in [["Won", "win"], ["Lost", "loss"]]:
		var button = Button.new()
		button.text = outcome[0]
		button.pressed.connect(self._on_result_pressed.bind(outcome[1]))
		result_box.add_child(button)
	$CanvasLayer.add_child(result_box)
	$CanvasLayer.move_child(result_box, $CanvasLayer/PauseScreen.get_index())

	formation_label = Label.new()
	formation_label.anchor_left = 0.04
	formation_label.anchor_top = 0.05
	formation_label.anchor_right = 0.968
	formation_label.anchor_bottom = 0.086
	formation_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	formation_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	formation_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	formation_label.add_theme_font_size_override("font_size", 12)
	formation_label.add_theme_constant_override("line_spacing", -2)
	$CanvasLayer.add_child(formation_label)
	$CanvasLayer.move_child(formation_label, $CanvasLayer/PauseScreen.get_index())

	#print(await GlobalVars.get_user_data('khhm'))
	
	new_draft_id()
	SettingManager.update_data()
	CropTopValue = str(SettingManager.CropTopValue)
	CropBotValue = str(SettingManager.CropBotValue)
	CropRightValue = str(SettingManager.CropRightValue)
	CropLeftValue = str(SettingManager.CropLeftValue)
	CropCenterValue = str(SettingManager.CropCenterValue)
	title = SettingManager.WindowTitle
	user_data = SettingManager.UserData

	# Display user stats
	if user_data.size() != 0:
		GlobalVars.user_data = user_data
		$CanvasLayer/UserStats.emit_signal('_update_most_picks')	
		$CanvasLayer/UserStats.emit_signal('_update_recent_picks',GlobalVars.recommend_top_characters(user_data['character_stats']))
		
# Check for key press
func _input(event):
	# Escape	
	if event.is_action_pressed("ui_cancel"):
		paused = !paused
		
		if paused: # Pause
			# Display pause screen
			$CanvasLayer/PauseScreen.visible = true
			
			# Cancel all requests and stop them
			if http_request.get_http_client_status() != 0:
				http_request.cancel_request()
			GlobalVars.request_done = false
			
			if misc_http_request.get_http_client_status() != 0:
				misc_http_request.cancel_request()
			if ban_http_request.get_http_client_status() != 0:
				ban_http_request.cancel_request()
			can_ask_rec = false
			print('status: paused')
			
		else: # Resume
			# Stop displaying pause screen
			$CanvasLayer/PauseScreen.visible = false
			
			# Resume all requests
			GlobalVars.request_done = true
			can_ask_rec = true
			print('status: resumed')
			
func _process(_delta):
	# Update request_done
	request_done = GlobalVars.request_done

	if manual_mode:
		return

	# Request char detection (after a failed capture, e.g. the game is closed, wait a moment
	# instead of retrying every frame)
	if request_done and Time.get_ticks_msec() >= detection_retry_at:
		# Reset DetectOutput
		DetectOutput = {}
		var url = "http://127.0.0.1:"+str(GlobalVars.port)+"/detect_enemy?title="+title.uri_encode()+"&crops="+CropTopValue+","+CropBotValue+","+CropRightValue+","+CropLeftValue+","+CropCenterValue
		# Preban detection is the slow part; skip it once all four are known, or once picks
		# are under way (by then prebans are as settled as they will get)
		if prebans.size() >= 4 or held_user_team.size() + held_enemy_team.size() >= 3:
			url += "&skip_prebans=1"
		if http_request.get_http_client_status() == 0:
			http_request.request(url)
			request_done = false # Stop request call until the detection finishes

func _on_misc_server_completed(result, response_code, headers, body):
	print("Request recommendations")
	if response_code == 200:
		can_ask_rec = true
		var json = JSON.new()
		json.parse(body.get_string_from_utf8())
		var Recommendation = json.get_data()
		print("Rec: " + str(Recommendation))
		print("Rec: " + str(Recommendation['top_10_heroes']))
		print("Rec: " + str(Recommendation['win_prediction']))		
		
		$CanvasLayer/UserPickData.set_pick_win_rates(Recommendation.get('pick_win_rates', []), Recommendation.get('picker_is_user', true))
		$CanvasLayer/UserPickData.emit_signal('show_recommendation', Recommendation['top_10_heroes'])

		# Set Win Prediction
		$CanvasLayer/MatchSelect/Container/ColorRect/WinPredictionBar.value = float(Recommendation['win_prediction'])*100

		# Draft complete: no more picks to suggest, so ask for ban suggestions instead
		if len(Recommendation['top_10_heroes']) == 0 and last_user_team.split(",").size() >= 5 and last_enemy_team.split(",").size() >= 5:
			request_ban_suggestions()
	else:
		can_ask_rec = true	
		print('rec error: '+ body.get_string_from_utf8())	
		# If failed, then show no rec
		$CanvasLayer/UserPickData.emit_signal('show_recommendation', [])
		# Set Win Prediction to 50%
		$CanvasLayer/MatchSelect/Container/ColorRect/WinPredictionBar.value = 50.0

# How this draft reached the app, recorded with it in the server's draft log
func draft_source() -> String:
	return "manual" if manual_mode else "detect"

func _on_result_pressed(outcome: String):
	if last_draft.is_empty():
		return
	var url = "http://127.0.0.1:"+str(GlobalVars.misc_port)+"/draft_result?result="+outcome+"&user_picks="+last_draft['user']+"&enemy_picks="+last_draft['enemy']+"&first_pick_team="+last_draft['first'].uri_encode()+"&rule="+last_draft['rule']+"&source="+last_draft['source']+"&draft="+last_draft['draft']
	if result_http_request.get_http_client_status() != 0:
		result_http_request.cancel_request()
	result_http_request.request(url)
	result_box.visible = false

func request_ban_suggestions():
	if ban_http_request.get_http_client_status() != 0:
		ban_http_request.cancel_request()
	var first_pick_team = "My Team" if is_user_first_pick else "Enemy Team"
	var url = "http://127.0.0.1:"+str(GlobalVars.misc_port)+"/recommend_ban"+"?user_picks="+last_user_team+"&enemy_picks="+last_enemy_team+"&first_pick_team="+first_pick_team.uri_encode()+"&rule="+rule+"&user_banned="+user_banned+"&enemy_banned="+enemy_banned+"&source="+draft_source()+"&draft="+draft_id
	print('ban url: '+url)
	ban_http_request.request(url)

func hero_display_name(code) -> String:
	for hero in GlobalVars.hero_names:
		if hero['code'] == str(code):
			return hero['name']
	return str(code)

# Where top players stand these heroes, with how often they use that slot
func show_formation(formation: Array, assumed_ban):
	var slots = []
	for entry in formation:
		slots.append("%s: %s (%d%%)" % [entry['position'], hero_display_name(entry['hero']), round(float(entry['share']) * 100)])
	var text = "   ".join(slots)
	if text != "" and assumed_ban != null:
		text += "   [if " + hero_display_name(assumed_ban) + " is banned]"
	formation_label.text = text
	formation_label.tooltip_text = text

func _on_ban_suggestions_completed(result, response_code, headers, body):
	if response_code != 200:
		# Ban model missing or teams incomplete: keep the pick view as is
		print('ban suggestion error: '+ body.get_string_from_utf8())
		return
	var json = JSON.new()
	json.parse(body.get_string_from_utf8())
	var Bans = json.get_data()
	$CanvasLayer/UserPickData.emit_signal('show_ban_suggestions', Bans['ban_suggestions'], Bans['likely_enemy_bans'])
	show_formation(Bans.get('formation', []), Bans.get('formation_assumed_ban'))
	# Expected win rate once both sides make their best ban
	$CanvasLayer/MatchSelect/Container/ColorRect/WinPredictionBar.value = float(Bans['win_prediction'])*100

# The hero whose slot height is closest to the BANNED stamp
func hero_at_height(team: Array, heights: Array, y) -> String:
	var best = ""
	var best_distance = 1.0
	for i in range(min(team.size(), heights.size())):
		var distance = abs(float(heights[i]) - float(y))
		if distance < best_distance:
			best_distance = distance
			best = str(team[i])
	return best

func new_draft_id():
	draft_id = str(Time.get_unix_time_from_system()).replace(".", "") + str(randi() % 1000)

func reset_draft_memory():
	new_draft_id()
	draft_had_picks = false
	held_user_team = []
	held_user_y = []
	held_enemy_team = []
	held_enemy_y = []
	prebans = []
	full_user_team = []
	full_user_y = []
	full_enemy_team = []
	full_enemy_y = []
	user_banned = ""
	enemy_banned = ""

# [team, heights] to use for this frame: the held team when the frame only shows a subset of it
func hold_team(team: Array, heights: Array, held: Array, held_heights: Array) -> Array:
	if team.size() < held.size():
		var subset = true
		for hero in team:
			if not held.has(hero):
				subset = false
		if subset:
			return [held, held_heights]
	return [team, heights]

# Fill in what the current frame cannot show: prebans seen earlier in the draft, and a
# banned hero whose slot the BANNED stamp now hides. Returns true when the bans changed.
func apply_draft_memory(output: Dictionary) -> bool:
	var user_team = output['user_team']
	var enemy_team = output['enemy_team']
	var seen_prebans = output.get('user_prebans', []) + output.get('enemy_prebans', [])
	var no_picks = user_team.is_empty() and enemy_team.is_empty()
	empty_frames = empty_frames + 1 if no_picks else 0

	# Left the draft screen: forget this draft. Once the server stops looking for prebans (all
	# four known, or picks under way), only picks disappearing (after there were some) ends it.
	# Either way it takes several empty frames in a row, so one bad frame cannot end it.
	var draft_over = no_picks and seen_prebans.is_empty()
	if prebans.size() >= 4:
		draft_over = no_picks and draft_had_picks
	draft_over = draft_over and empty_frames >= EMPTY_FRAMES_TO_END_DRAFT
	if not no_picks:
		draft_had_picks = true
	if draft_over:
		reset_draft_memory()
		return false

	if seen_prebans.size() > prebans.size():
		prebans = seen_prebans

	# A team never loses heroes during a draft (a banned one is handled below), so a frame
	# showing only some of the heroes we already have keeps the fuller team
	var held = hold_team(user_team, output['user_team_y'], held_user_team, held_user_y)
	held_user_team = held[0]
	held_user_y = held[1]
	output['user_team'] = held_user_team
	output['user_team_y'] = held_user_y
	held = hold_team(enemy_team, output['enemy_team_y'], held_enemy_team, held_enemy_y)
	held_enemy_team = held[0]
	held_enemy_y = held[1]
	output['enemy_team'] = held_enemy_team
	output['enemy_team_y'] = held_enemy_y
	user_team = held_user_team
	enemy_team = held_enemy_team

	if user_team.size() >= 5:
		full_user_team = user_team.slice(0, 5)
		full_user_y = output['user_team_y'].slice(0, 5)
	if enemy_team.size() >= 5:
		full_enemy_team = enemy_team.slice(0, 5)
		full_enemy_y = output['enemy_team_y'].slice(0, 5)

	var new_user_banned = user_banned
	var new_enemy_banned = enemy_banned
	if output.get('user_banned_y') != null and full_user_team.size() == 5:
		new_user_banned = hero_at_height(full_user_team, full_user_y, output['user_banned_y'])
		output['user_team'] = full_user_team
	if output.get('enemy_banned_y') != null and full_enemy_team.size() == 5:
		new_enemy_banned = hero_at_height(full_enemy_team, full_enemy_y, output['enemy_banned_y'])
		output['enemy_team'] = full_enemy_team

	var changed = new_user_banned != user_banned or new_enemy_banned != enemy_banned
	user_banned = new_user_banned
	enemy_banned = new_enemy_banned
	return changed

# Draw both teams and their stats, and ask for recommendations when something changed
func show_draft(user_picks: Array, enemy_picks: Array, bans_changed: bool):
	var user_team = ",".join(user_picks)
	var enemy_team = ",".join(enemy_picks)

	UserPortraits.set_portraits(user_picks)
	# Show synergies to the last user pick
	$CanvasLayer/UserPickData.emit_signal('show_synergies', str(user_picks.back()) if not user_picks.is_empty() else '')

	EnemyPortraits.set_portraits(enemy_picks)
	# Show counters to the last enemy pick, and its stats
	var last_enemy_pick = str(enemy_picks.back()) if not enemy_picks.is_empty() else ''
	$CanvasLayer/UserPickData.emit_signal('show_counters', last_enemy_pick)
	EnemyPickStats.emit_signal('char_picked', last_enemy_pick)

	# A newly completed draft: offer to record how its game went
	if user_picks.size() >= 5 and enemy_picks.size() >= 5 and (last_draft.get('user') != user_team or last_draft.get('enemy') != enemy_team):
		last_draft = {'user': user_team, 'enemy': enemy_team, 'first': "My Team" if is_user_first_pick else "Enemy Team", 'rule': rule, 'source': draft_source(), 'draft': draft_id}
		result_label.text = "Last game:"
		result_box.visible = true

	# Request recommendations
	if can_ask_rec and (rec_forced or user_picks != old_user_team or enemy_picks != old_enemy_team):
		old_user_team = user_picks
		old_enemy_team = enemy_picks
		can_ask_rec = false
		rec_forced = false
		var first_pick_team = "My Team" if is_user_first_pick else "Enemy Team"
		last_user_team = user_team
		last_enemy_team = enemy_team
		formation_label.text = ""
		var url = "http://127.0.0.1:"+str(GlobalVars.misc_port)+"/recommend"+"?user_picks="+user_team+"&enemy_picks="+enemy_team+"&first_pick_team="+first_pick_team.uri_encode()+"&rule="+rule+"&prebans="+",".join(prebans)+"&source="+draft_source()+"&draft="+draft_id
		print('url: '+url)
		misc_http_request.request(url)

	elif bans_changed and full_user_team.size() == 5 and full_enemy_team.size() == 5:
		# Bans just appeared on screen: refresh the ban view with the exact post-ban win rate
		last_user_team = ",".join(full_user_team)
		last_enemy_team = ",".join(full_enemy_team)
		request_ban_suggestions()

func _on_detection_completed(result, response_code, headers, body):
	print("Char Detection Completed!")
	if manual_mode:
		# A capture that was still running when manual input was switched on
		request_done = true
		return
	if response_code == 200:
		request_done = true # Can do request call again
		var json = JSON.new()
		json.parse(body.get_string_from_utf8())
		DetectOutput = json.get_data()
		var bans_changed = apply_draft_memory(DetectOutput)
		show_draft(DetectOutput['user_team'], DetectOutput['enemy_team'], bans_changed)
		print("Detection Success")

	else:
		request_done = true # Try again
		detection_retry_at = Time.get_ticks_msec() + DETECTION_RETRY_DELAY_MS
		can_ask_rec = true
		old_user_team = []
		old_enemy_team = []
		
		# Delete all portraits
		UserPortraits.set_portraits([])
		$CanvasLayer/UserPickData.emit_signal('show_synergies', '')
		EnemyPickStats.emit_signal('char_picked','')
		EnemyPortraits.set_portraits([])
		$CanvasLayer/UserPickData.emit_signal('show_counters', '')						
		$CanvasLayer/UserPickData.emit_signal('show_recommendation', [])		
		$CanvasLayer/MatchSelect/Container/ColorRect/WinPredictionBar.value = 50.0			

		
		var json = JSON.new()
		json.parse(body.get_string_from_utf8())
		var response = json.get_data()
		print(response)
		DetectOutput = {}
		print("Request failed with response code %d" % response_code)

func _on_back_button_pressed():
	# Move back to front page and remove this scene
	get_tree().change_scene_to_file('res://scenes/FrontPage/FrontPage.tscn')
	self.queue_free()

# First pick selector
func _on_first_pick_selector_selected(index):
	is_user_first_pick = index == 1
	force_new_recommendation()
	if manual_mode:
		refresh_manual_draft(false)

# Warfare rule selector: item ids are the rule category numbers
func _on_rule_selector_selected(index):
	var rule_id = $CanvasLayer/RuleSelector.get_item_id(index)
	rule = "rta_openingrule_category_%d" % rule_id if rule_id > 0 else ""
	force_new_recommendation()
	if manual_mode:
		refresh_manual_draft(false)

func force_new_recommendation():
	# Cancel rec requests
	if misc_http_request.get_http_client_status() != 0:
		misc_http_request.cancel_request()
	if ban_http_request.get_http_client_status() != 0:
		ban_http_request.cancel_request()
	# Force resubmit rec
	can_ask_rec = true
	rec_forced = true
	old_user_team = []
	old_enemy_team = []

func _on_manual_toggled(enabled: bool):
	manual_mode = enabled
	manual_picker.visible = enabled
	$CanvasLayer/UserPickData.set_pick_on_click(enabled)
	if enabled:
		# Carry on from what detection has seen so far
		manual_user_team = held_user_team.duplicate()
		manual_enemy_team = held_enemy_team.duplicate()
		manual_history = []
		manual_picker.open()
		# A fresh draft starts with the prebans
		var fresh = manual_user_team.is_empty() and manual_enemy_team.is_empty() and prebans.is_empty()
		manual_picker.set_target(ManualPicker.Target.PREBAN if fresh else manual_stage_target())
		refresh_manual_draft(false)
	else:
		# Detection takes over mid-draft: it no longer looks for prebans once picks are under
		# way, so what was entered by hand stays
		var kept = [prebans, user_banned, enemy_banned]
		reset_draft_memory()
		prebans = kept[0]
		user_banned = kept[1]
		enemy_banned = kept[2]
		force_new_recommendation()

func manual_draft_complete() -> bool:
	return manual_user_team.size() + manual_enemy_team.size() >= FIRST_PICK_TURNS.size()

# Where heroes go once the prebans are done: picks until the draft is complete, then bans
func manual_stage_target() -> int:
	return ManualPicker.Target.BAN if manual_draft_complete() else ManualPicker.Target.DRAFT_ORDER

func _on_manual_next():
	manual_picker.set_target(manual_stage_target())
	manual_picker.search.grab_focus()

func _on_suggestion_clicked(code: String):
	if manual_mode:
		if manual_picker.target_selector.selected == ManualPicker.Target.PREBAN:
			manual_picker.set_target(manual_stage_target())
		_on_manual_hero_chosen(code, manual_picker.target_selector.selected)

# In draft order, does the next pick go to the user's team?
func next_manual_pick_is_users() -> bool:
	var turn = manual_user_team.size() + manual_enemy_team.size()
	if turn >= FIRST_PICK_TURNS.size():
		return false
	var users = FIRST_PICK_TURNS[turn] == is_user_first_pick
	# Teams entered out of draft order: fall back to the side that still has room
	if users and manual_user_team.size() >= 5:
		return false
	if not users and manual_enemy_team.size() >= 5:
		return true
	return users

func _on_manual_hero_chosen(code: String, target: int):
	var drafted = manual_user_team.has(code) or manual_enemy_team.has(code)
	var bans_changed = false
	if target == ManualPicker.Target.BAN:
		# Post-draft ban: only a hero that is in one of the teams
		if manual_user_team.has(code):
			manual_history.append([target, code, user_banned])
			user_banned = code
		elif manual_enemy_team.has(code):
			manual_history.append([target, code, enemy_banned])
			enemy_banned = code
		else:
			return
		bans_changed = true
	elif drafted or prebans.has(code):
		return
	elif target == ManualPicker.Target.PREBAN:
		if prebans.size() >= 4:
			return
		prebans.append(code)
		manual_history.append([target, code, ""])
	else:
		var to_user = target == ManualPicker.Target.MY_TEAM or (target == ManualPicker.Target.DRAFT_ORDER and next_manual_pick_is_users())
		var team = manual_user_team if to_user else manual_enemy_team
		if team.size() >= 5:
			return
		team.append(code)
		manual_history.append([ManualPicker.Target.MY_TEAM if to_user else ManualPicker.Target.ENEMY_TEAM, code, ""])
	# Move on by itself once a stage is full: four prebans, then ten picks
	if target == ManualPicker.Target.PREBAN and prebans.size() >= 4:
		manual_picker.set_target(manual_stage_target())
	elif target != ManualPicker.Target.PREBAN and target != ManualPicker.Target.BAN and manual_draft_complete():
		manual_picker.set_target(ManualPicker.Target.BAN)
	refresh_manual_draft(bans_changed)

func _on_manual_undo():
	if manual_history.is_empty():
		return
	var last = manual_history.pop_back()
	var hero = last[1]
	match last[0]:
		ManualPicker.Target.BAN:
			if user_banned == hero:
				user_banned = last[2]
			else:
				enemy_banned = last[2]
		ManualPicker.Target.PREBAN:
			prebans.erase(hero)
		ManualPicker.Target.MY_TEAM:
			manual_user_team.erase(hero)
		ManualPicker.Target.ENEMY_TEAM:
			manual_enemy_team.erase(hero)
	if manual_picker.target_selector.selected == ManualPicker.Target.BAN and not manual_draft_complete():
		manual_picker.set_target(ManualPicker.Target.DRAFT_ORDER)
	refresh_manual_draft(true)

func _on_manual_clear():
	reset_draft_memory()
	manual_user_team = []
	manual_enemy_team = []
	manual_history = []
	manual_picker.set_target(ManualPicker.Target.PREBAN)
	refresh_manual_draft(false)

# Redraw the hand-entered draft and ask for new suggestions
func refresh_manual_draft(bans_changed: bool):
	full_user_team = manual_user_team.duplicate() if manual_user_team.size() == 5 else []
	full_enemy_team = manual_enemy_team.duplicate() if manual_enemy_team.size() == 5 else []
	# A ban only stands while its hero is still in the team
	if not manual_user_team.has(user_banned):
		user_banned = ""
	if not manual_enemy_team.has(enemy_banned):
		enemy_banned = ""
	if bans_changed and full_user_team.size() == 5 and full_enemy_team.size() == 5:
		last_user_team = ",".join(full_user_team)
		last_enemy_team = ",".join(full_enemy_team)
		request_ban_suggestions()
	else:
		force_new_recommendation()
		# Copies, so that later picks are seen as a change
		show_draft(manual_user_team.duplicate(), manual_enemy_team.duplicate(), bans_changed)

	manual_picker.set_used(manual_user_team + manual_enemy_team + prebans)
	var notes = []
	if not prebans.is_empty():
		notes.append("Prebans: " + ", ".join(prebans.map(manual_picker.hero_name)))
	if manual_user_team.size() + manual_enemy_team.size() < 10:
		notes.append("Next in draft order: " + ("My Team" if next_manual_pick_is_users() else "Enemy Team"))
	else:
		notes.append("Draft complete. Pick the banned hero of each team")
	if user_banned != "":
		notes.append("My " + manual_picker.hero_name(user_banned) + " banned")
	if enemy_banned != "":
		notes.append("Enemy " + manual_picker.hero_name(enemy_banned) + " banned")
	manual_picker.set_status("  |  ".join(notes))
