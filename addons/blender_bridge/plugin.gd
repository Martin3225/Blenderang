@tool
extends EditorPlugin

## Ovládání mostu Godot ↔ Blender.
##
## Hlavní cesta má jeden klik na každé straně: [i]Otevřít v Blenderu[/i]
## tady (tlačítko v liště 3D editoru, pravé tlačítko na tabu scény nebo na
## [code].tscn[/code] ve FileSystemu), [i]Odeslat do Godotu[/i] v Blenderu.
## Změny z Blenderu se do otevřené scény načtou samy.

const MENU_NAME: String = "Blender Bridge"
const WATCH_INTERVAL: float = 1.0

enum Action {
	OPEN_IN_BLENDER,
	MARK_SELECTION,
	UNMARK_SELECTION,
	MARK_PROPS,
	PICK_SOURCE,
	EXPORT_MANIFEST,
	IMPORT_MANIFEST,
}

var _menu: PopupMenu
var _toolbar_button: Button
var _context_menus: Array[EditorContextMenuPlugin] = []
var _watch: Timer
## Poslední obsah manifestu, o kterém plugin ví (zapsal ho sám, nebo ho už
## naimportoval). Jiný obsah na disku znamená změnu z Blenderu.
var _known_md5: Dictionary = {}


func _enter_tree() -> void:
	_menu = PopupMenu.new()
	_menu.add_item("Otevřít scénu v Blenderu", Action.OPEN_IN_BLENDER)
	_menu.add_separator("Pokročilé")
	_menu.add_item("Označit výběr jako Blender-owned", Action.MARK_SELECTION)
	_menu.add_item("Zrušit označení výběru", Action.UNMARK_SELECTION)
	_menu.add_item("Označit všechny art instance ve scéně", Action.MARK_PROPS)
	_menu.add_item("Vybrat zdrojový .blend pro výběr…", Action.PICK_SOURCE)
	_menu.add_separator()
	_menu.add_item("Jen exportovat manifest", Action.EXPORT_MANIFEST)
	_menu.add_item("Ručně načíst změny z Blenderu", Action.IMPORT_MANIFEST)
	_menu.id_pressed.connect(_on_action)
	add_tool_submenu_item(MENU_NAME, _menu)

	_toolbar_button = Button.new()
	_toolbar_button.text = "Blender"
	_toolbar_button.icon = BBIcons.blender()
	_toolbar_button.flat = true
	_toolbar_button.tooltip_text = "Otevřít scénu v Blenderu"
	_toolbar_button.pressed.connect(_on_toolbar_pressed)
	add_control_to_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_button)

	for slot: int in [
		EditorContextMenuPlugin.CONTEXT_SLOT_SCENE_TABS,
		EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM,
	]:
		var menu: EditorContextMenuPlugin = preload("bb_context_menu.gd").new(open_scene_in_blender)
		add_context_menu_plugin(slot, menu)
		_context_menus.append(menu)

	_watch = Timer.new()
	_watch.wait_time = WATCH_INTERVAL
	_watch.timeout.connect(_poll_manifest)
	add_child(_watch)
	_watch.start()


func _exit_tree() -> void:
	remove_tool_menu_item(MENU_NAME)
	_menu = null
	remove_control_from_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_button)
	_toolbar_button.queue_free()
	_toolbar_button = null
	for menu: EditorContextMenuPlugin in _context_menus:
		remove_context_menu_plugin(menu)
	_context_menus.clear()
	_watch.queue_free()
	_watch = null


func _on_toolbar_pressed() -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null:
		push_warning("Blender Bridge: není otevřená žádná scéna.")
		return
	_open_in_blender(root)


## Vstup z kontextových menu. Scénu, která není v editoru aktivní, nejdřív
## otevře — manifest i značky bb_id se berou z otevřeného stromu.
func open_scene_in_blender(path: String) -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path != path:
		EditorInterface.open_scene_from_path(path)
		root = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path != path:
		push_error("Blender Bridge: scénu %s se nepodařilo otevřít." % path)
		return
	_open_in_blender(root)


func _on_action(id: int) -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null:
		push_warning("Blender Bridge: není otevřená žádná scéna.")
		return
	match id:
		Action.OPEN_IN_BLENDER:
			_open_in_blender(root)
		Action.MARK_SELECTION:
			_mark(EditorInterface.get_selection().get_selected_nodes(), root)
		Action.UNMARK_SELECTION:
			_unmark(EditorInterface.get_selection().get_selected_nodes())
		Action.MARK_PROPS:
			_mark(_find_props(root), root)
		Action.PICK_SOURCE:
			_pick_source()
		Action.EXPORT_MANIFEST:
			_export(root)
		Action.IMPORT_MANIFEST:
			_import(root, false)


## Celá cesta Godot → Blender jedním klikem. Při prvním použití na scéně
## označí art instance sám, aby nebylo nutné nic připravovat.
func _open_in_blender(root: Node) -> void:
	var duplicates: Array[Node] = []
	if BBOwnership.collect_ids(root, duplicates).is_empty():
		_mark(_find_props(root), root)
	if root.scene_file_path.is_empty():
		push_warning("Blender Bridge: scénu nejdřív ulož, manifest se pojmenuje podle ní.")
		return
	# Značky bb_id musí být na disku, jinak by je import nenašel.
	if EditorInterface.save_scene() != OK:
		push_error("Blender Bridge: scénu se nepodařilo uložit.")
		return
	var path: String = _export(root)
	if path.is_empty():
		return
	if BBLauncher.launch(ProjectSettings.globalize_path(path)) == OK:
		print("Blender Bridge: Blender se spouští se scénou %s." % root.scene_file_path.get_file())


## Nastaví přesnou cestu ke zdrojovému .blend vybraného assetu. Zapisuje se
## do souboru vedle assetu, takže platí pro všechny jeho instance i pro
## celý tým.
func _pick_source() -> void:
	var selected: Array[Node] = EditorInterface.get_selection().get_selected_nodes()
	if selected.size() != 1 or selected[0].scene_file_path.is_empty():
		push_warning("Blender Bridge: vyber právě jeden instancovaný node.")
		return
	var asset: String = selected[0].scene_file_path
	var dialog: EditorFileDialog = EditorFileDialog.new()
	dialog.file_mode = EditorFileDialog.FILE_MODE_OPEN_FILE
	dialog.access = EditorFileDialog.ACCESS_RESOURCES
	dialog.add_filter("*.blend", "Blender soubory")
	dialog.title = "Zdrojový .blend pro %s" % asset.get_file()
	dialog.current_path = "res://" + BBPaths.expected_source_for(asset)
	dialog.file_selected.connect(func(path: String) -> void:
		if BBPaths.write_override(asset, path):
			EditorInterface.get_resource_filesystem().scan()
			print("Blender Bridge: %s → %s" % [asset.get_file(), path])
		dialog.queue_free()
	)
	dialog.canceled.connect(dialog.queue_free)
	EditorInterface.get_base_control().add_child(dialog)
	dialog.popup_centered_ratio(0.6)


func _mark(nodes: Array[Node], root: Node) -> void:
	var duplicates: Array[Node] = []
	var taken: Dictionary = BBOwnership.collect_ids(root, duplicates)
	var undo: EditorUndoRedoManager = get_undo_redo()
	undo.create_action("Blender Bridge: označit nody")
	var marked: int = 0
	for node: Node in nodes + duplicates:
		if not node is Node3D:
			continue
		if BBOwnership.is_blender_owned(node) and not duplicates.has(node):
			continue
		var id: String = BBOwnership.generate_id()
		while taken.has(id):
			id = BBOwnership.generate_id()
		taken[id] = node
		marked += 1
		undo.add_do_method(node, &"set_meta", BBOwnership.META_ID, id)
		undo.add_undo_method(node, &"remove_meta", BBOwnership.META_ID)
	undo.commit_action()
	print("Blender Bridge: označeno %d nodů." % marked)


func _unmark(nodes: Array[Node]) -> void:
	var undo: EditorUndoRedoManager = get_undo_redo()
	undo.create_action("Blender Bridge: zrušit označení")
	for node: Node in nodes:
		if not BBOwnership.is_blender_owned(node):
			continue
		var id: String = BBOwnership.get_id(node)
		undo.add_do_method(node, &"remove_meta", BBOwnership.META_ID)
		undo.add_undo_method(node, &"set_meta", BBOwnership.META_ID, id)
	undo.commit_action()


func _find_props(root: Node) -> Array[Node]:
	var found: Array[Node] = []
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		for child: Node in node.get_children():
			stack.push_back(child)
		if node != root and BBOwnership.is_auto_markable(node, root):
			found.append(node)
	return found


func _export(root: Node) -> String:
	var path: String = BBManifest.write(root)
	if path.is_empty():
		return ""
	_known_md5[path] = FileAccess.get_md5(path)
	print("Blender Bridge: manifest zapsán do %s" % path)
	return path


## Změny z Blenderu se načtou samy: Blender po „Odeslat do Godotu“ přepíše
## manifest, tady se to pozná podle změny obsahu. Kontroluje se jen manifest
## právě otevřené scény.
func _poll_manifest() -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path.is_empty():
		return
	var path: String = BBManifest.manifest_path(root)
	if not FileAccess.file_exists(path):
		return
	var md5: String = FileAccess.get_md5(path)
	if not _known_md5.has(path):
		# Manifest z dřívějška, o kterém tahle relace editoru neví — nenačítat
		# naslepo, jen si ho zapamatovat.
		_known_md5[path] = md5
		return
	if _known_md5[path] == md5:
		return
	_known_md5[path] = md5
	_import(root, true)


func _import(root: Node, automatic: bool) -> void:
	var path: String = BBManifest.manifest_path(root)
	var manifest: Dictionary = BBApply.read_json(path)
	if manifest.is_empty():
		push_warning("Blender Bridge: manifest chybí, nejdřív otevři scénu v Blenderu.")
		return
	var baseline: Dictionary = BBApply.read_json(BBManifest.baseline_path(root))
	var plan: BBApply.Plan = BBApply.plan(root, manifest, baseline)
	if plan.is_empty():
		if not automatic:
			print("Blender Bridge: žádné změny.")
		return
	BBApply.commit(BBApply.operations(root, plan), get_undo_redo())
	BBManifest.store(BBManifest.baseline_path(root), JSON.stringify(manifest, "\t"))
	_known_md5[path] = FileAccess.get_md5(path)
	print("Blender Bridge: z Blenderu %s (Ctrl+Z vrátí)" % plan.summary())
	for problem: String in plan.unresolved:
		push_warning("Blender Bridge: %s" % problem)
	for name: String in plan.pinned:
		push_warning("Blender Bridge: %s je zamčený v Godotu, změna z Blenderu ignorována." % name)
