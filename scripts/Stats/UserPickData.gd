extends Node

@onready var portrait1 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer/PortraitDisplay
@onready var portrait2 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer2/PortraitDisplay
@onready var portrait3 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer3/PortraitDisplay
@onready var portrait4 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer4/PortraitDisplay
@onready var portrait5 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer5/PortraitDisplay
@onready var portrait6 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer/PortraitDisplay
@onready var portrait7 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer2/PortraitDisplay
@onready var portrait8 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer3/PortraitDisplay
@onready var portrait9 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer4/PortraitDisplay
@onready var portrait10 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer5/PortraitDisplay
@onready var portraits = [portrait1, portrait2, portrait3, portrait4, portrait5, portrait6, portrait7, portrait8, portrait9, portrait10]

@onready var label1 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer/Label
@onready var label2 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer2/Label
@onready var label3 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer3/Label
@onready var label4 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer4/Label
@onready var label5 = $VBoxContainer/HBoxContainer/VBoxContainer/HBoxContainer5/Label
@onready var label6 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer/Label
@onready var label7 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer2/Label
@onready var label8 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer3/Label
@onready var label9 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer4/Label
@onready var label10 = $VBoxContainer/HBoxContainer/VBoxContainer2/HBoxContainer5/Label
@onready var labels = [label1, label2, label3, label4, label5, label6, label7, label8, label9, label10]

@onready var counter_portrait1 = $VBoxContainer/VBoxContainer2/Counters/PortraitDisplay
@onready var counter_portrait2 = $VBoxContainer/VBoxContainer2/Counters/PortraitDisplay2
@onready var counter_portrait3 = $VBoxContainer/VBoxContainer2/Counters/PortraitDisplay3
@onready var counter_portraits = [counter_portrait1, counter_portrait2, counter_portrait3]

@onready var synergy_portrait1 = $VBoxContainer/VBoxContainer2/Synergies/PortraitDisplay
@onready var synergy_portrait2 = $VBoxContainer/VBoxContainer2/Synergies/PortraitDisplay2
@onready var synergy_portrait3 = $VBoxContainer/VBoxContainer2/Synergies/PortraitDisplay3
@onready var synergy_portraits = [synergy_portrait1, synergy_portrait2, synergy_portrait3]

@onready var char_match_stats = GlobalVars.hero_match_data
@onready var hero_data = GlobalVars.hero_data

signal show_recommendation(recommendation: Array)
signal show_ban_suggestions(ban_suggestions: Array, likely_enemy_bans: Array)
signal show_counters(character: String)
signal show_synergies(character: String)

func set_hero_portrait(portrait, hero: String):
	var image = Image.load_from_file('dataset/'+hero+'/c.png')
	if image == null:
		portrait.texture = load('res://UI/MatchSelect/unknown_hero.png')
		return
	var texture = ImageTexture.create_from_image(image)
	texture.resource_name = 'dataset/'+hero+'/c.png'
	portrait.texture = texture

# After the draft the pick grid is free: the left column shows which enemy hero to ban
# (our worst-case win rate if we ban it), the right column which of our heroes they will
# likely ban (our win rate if they do)
func on_show_ban_suggestions(ban_suggestions: Array, likely_enemy_bans: Array):
	for portrait in portraits:
		portrait.texture = load('res://UI/MatchSelect/unknown_hero.png')
	for label in labels:
		label.text = ""
	for i in range(min(5, len(ban_suggestions))):
		set_hero_portrait(portraits[i], str(ban_suggestions[i]['hero']))
		labels[i].text = "BAN  WR %.1f%%" % (float(ban_suggestions[i]['worst_case_win_rate']) * 100)
	for i in range(min(5, len(likely_enemy_bans))):
		set_hero_portrait(portraits[i + 5], str(likely_enemy_bans[i]['hero']))
		labels[i + 5].text = "RISK WR %.1f%%" % (float(likely_enemy_bans[i]['win_rate']) * 100)

func on_show_recommendation(recommendation: Array):
	# First reset all portraits and labels
	for portrait in portraits:
		portrait.texture = load('res://UI/MatchSelect/unknown_hero.png')
	for label in labels:
		label.text = ""
	print('rec len: ' + str(len(recommendation)))
	# Now show recommendations. Every recommended hero is drawn, even without a stats row
	# (new heroes would otherwise be skipped and leave gaps in the grid)
	var i = 0
	for rec in recommendation:
		# If rec is more than what we can handle, break
		if i >= len(portraits):
			break
		set_hero_portrait(portraits[i], str(rec))
		labels[i].text = "WR —"
		for chars in hero_data:
			if chars['Hero'] == rec and str(chars['Win Rate']).is_valid_float():
				labels[i].text = "WR " + str(chars['Win Rate'])+"%"
		i += 1
	
func on_show_counters(character: String):
	#First set all portraits as unknown hero
	for portrait in counter_portraits:
		portrait.texture = load("res://UI/MatchSelect/unknown_hero.png")
	
	for chars in hero_data:
		if chars['Hero'] == character:
			#var counters = chars['Counters'].replace('\'','').replace('[', '').replace(']','').replace(' ','').split(',')
			var regex = RegEx.new()
			regex.compile('c\\d{4}')
			var counters = []
			for result in regex.search_all(chars['Counters']):
				counters.append(result.get_string())
			var i = 0
			for counter in counters:
				var image = Image.load_from_file('dataset/'+str(counter)+'/c.png')
				var texture = ImageTexture.create_from_image(image)
				texture.resource_name = 'dataset/'+str(counter)+'/c.png'				
				counter_portraits[i].texture = texture
				#counter_portraits[i].texture = load('dataset/'+str(counter)+'/c.png')
				i+=1
	
func on_show_synergies(character: String):
	#First set all portraits as unknown hero
	for portrait in synergy_portraits:
		portrait.texture = load("res://UI/MatchSelect/unknown_hero.png")
	
	for chars in hero_data:
		if chars['Hero'] == character:
			var regex = RegEx.new()
			regex.compile('c\\d{4}')
			var synergies = []
			for result in regex.search_all(chars['Synergies']):
				synergies.append(result.get_string())
			var i = 0
			for synergy in synergies:
				#synergy_portraits[i].texture = load('dataset/'+str(synergy)+'/c.png')
				var image = Image.load_from_file('dataset/'+str(synergy)+'/c.png')
				var texture = ImageTexture.create_from_image(image)
				texture.resource_name = 'dataset/'+str(synergy)+'/c.png'								
				synergy_portraits[i].texture = texture
				i+=1
	
# Called when the node enters the scene tree for the first time.
func _ready():
	pass # Replace with function body.


# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta):
	pass
