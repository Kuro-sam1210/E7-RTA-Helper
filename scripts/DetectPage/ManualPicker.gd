extends PanelContainer

# Hero picker for entering a draft by hand: a search box, where the chosen hero goes, undo and
# clear, and a clickable hero list. MatchSelectPage owns the draft; this only reports choices.

signal hero_chosen(code: String, target: int)
signal undo_pressed
signal clear_pressed

enum Target { DRAFT_ORDER, MY_TEAM, ENEMY_TEAM, PREBAN, BAN }
const TARGET_LABELS = ["Draft order", "My Team", "Enemy Team", "Preban", "Ban"]
const ICON_SIZE = Vector2i(44, 44)
const COLUMNS = 3

var search: LineEdit
var target_selector: OptionButton
var status: Label
var hero_list: ItemList

var heroes = [] # [name, code, icon, pick rate] most picked first, loaded the first time the picker opens
var names = {}
var used = []

func _ready():
	var background = StyleBoxFlat.new()
	background.bg_color = Color(0.09, 0.09, 0.12)
	background.set_content_margin_all(8)
	add_theme_stylebox_override("panel", background)

	var box = VBoxContainer.new()
	add_child(box)
	var row = HBoxContainer.new()
	box.add_child(row)

	search = LineEdit.new()
	search.placeholder_text = "Search hero (Enter picks the first match)"
	search.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	search.text_changed.connect(func(_text): refresh())
	search.text_submitted.connect(_on_search_submitted)
	row.add_child(search)

	target_selector = OptionButton.new()
	for label in TARGET_LABELS:
		target_selector.add_item(label)
	target_selector.tooltip_text = "Where the next hero goes. Ban marks a drafted hero as banned."
	row.add_child(target_selector)

	var undo = Button.new()
	undo.text = "Undo"
	undo.pressed.connect(func(): undo_pressed.emit())
	row.add_child(undo)

	var clear = Button.new()
	clear.text = "Clear"
	clear.pressed.connect(func(): clear_pressed.emit())
	row.add_child(clear)

	status = Label.new()
	status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(status)

	hero_list = ItemList.new()
	hero_list.size_flags_vertical = Control.SIZE_EXPAND_FILL
	hero_list.max_columns = COLUMNS
	hero_list.same_column_width = true
	hero_list.fixed_icon_size = ICON_SIZE
	hero_list.item_clicked.connect(_on_item_clicked)
	# The list has no width until it is first laid out
	hero_list.resized.connect(fit_columns)
	box.add_child(hero_list)

func open():
	if heroes.is_empty():
		load_heroes()
	search.text = ""
	refresh()
	search.grab_focus()

func load_heroes():
	var pick_rates = {}
	for stats in GlobalVars.hero_match_data:
		pick_rates[stats['Hero']] = float(stats['Pick Rate'])
	for hero in GlobalVars.hero_names:
		var code = str(hero['code'])
		var path = 'dataset/'+code+'/c.png'
		# Only heroes with a portrait are known to detection and the models
		if not FileAccess.file_exists(path):
			continue
		var icon = ImageTexture.create_from_image(Image.load_from_file(path))
		heroes.append([str(hero['name']), code, icon, pick_rates.get(code, 0.0)])
		names[code] = str(hero['name'])
	# Meta heroes on top; the rest is found with the search box
	heroes.sort_custom(func(a, b): return a[3] > b[3] if a[3] != b[3] else a[0].naturalnocasecmp_to(b[0]) < 0)

func hero_name(code) -> String:
	return names.get(str(code), str(code))

func set_status(text: String):
	status.text = text

func set_used(codes: Array):
	used = codes
	refresh()

func refresh():
	hero_list.clear()
	fit_columns()
	var query = search.text.strip_edges().to_lower()
	for hero in heroes:
		if query != "" and not hero[0].to_lower().contains(query):
			continue
		var item = hero_list.add_item(hero[0], hero[2])
		hero_list.set_item_metadata(item, hero[1])
		# Heroes already in the draft stay clickable only to be marked as banned
		if used.has(hero[1]):
			hero_list.set_item_custom_fg_color(item, Color(1, 1, 1, 0.35))

# Columns share the list's width
func fit_columns():
	var width = int(max(hero_list.size.x - 24, 300) / COLUMNS) - ICON_SIZE.x
	if hero_list.fixed_column_width != width:
		hero_list.fixed_column_width = width

func choose(item: int):
	hero_chosen.emit(str(hero_list.get_item_metadata(item)), target_selector.selected)

func _on_item_clicked(item: int, _at_position: Vector2, mouse_button: int):
	if mouse_button == MOUSE_BUTTON_LEFT:
		choose(item)

func _on_search_submitted(_text: String):
	if hero_list.item_count == 0:
		return
	choose(0)
	search.text = ""
	refresh()
