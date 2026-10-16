@tool
extends EditorPlugin

## Testy ve skutečném editoru. Řídí je runner proměnnými prostředí:
##   BB_TEST_EDITOR   fáze (open_and_watch | restart | context_menu)
##   BB_TEST_OUT      adresář pro výsledky
##   BB_FAKE_BLENDER  program, který místo Blenderu zapíše své argumenty
## Bez BB_TEST_EDITOR plugin nedělá nic, takže projekt jde normálně otevřít.

const BRIDGE_SCRIPT: String = "addons/blender_bridge/plugin.gd"
const WATCH_WAIT: float = 2.5
const DEADLINE: float = 90.0

var _results: Array = []
var _phase: String = ""
var _finished: bool = false


func _enter_tree() -> void:
	_phase = OS.get_environment("BB_TEST_EDITOR")
	if _phase.is_empty():
		return
	get_tree().create_timer(DEADLINE).timeout.connect(func() -> void:
		_record("(časový limit)", false, "fáze %s nedoběhla do %d s" % [_phase, DEADLINE])
		_finish()
	)
	_run.call_deferred()


func _run() -> void:
	var root: Node = await _wait_for_scene()
	var bridge: EditorPlugin = _find_bridge()
	_record("editor načetl scénu a plugin", root != null and bridge != null, "scéna=%s plugin=%s" % [root, bridge])
	if root == null or bridge == null:
		_finish()
		return
	EditorInterface.get_editor_settings().set_setting(
		"filesystem/import/blender/blender_path", OS.get_environment("BB_FAKE_BLENDER"))
	match _phase:
		"open_and_watch":
			await _phase_open_and_watch(bridge)
		"restart":
			await _phase_restart(bridge)
		"context_menu":
			await _phase_context_menu(bridge)
	_finish()


# ------------------------------------------------------------------ fáze


func _phase_open_and_watch(bridge: EditorPlugin) -> void:
	var button: Button = bridge.get("_toolbar_button")
	_record("tlačítko Blender je v liště 3D editoru",
		button != null and button.is_inside_tree() and button.get_parent() != null, "")

	button.pressed.emit()
	var args: PackedStringArray = await _fake_blender_args()
	var manifest: String = ProjectSettings.globalize_path("res://.pipeline/basic.json")
	_record("tlačítko spustí Blender s manifestem",
		args.size() == 2 and args[0] == "--python-expr" and args[1].contains(JSON.stringify(manifest)),
		"argumenty: %s" % [args])
	_record("startovní Python volá bb.open_from_godot", args.size() == 2 and args[1].contains("bpy.ops.bb.open_from_godot"), "")

	var root: Node = EditorInterface.get_edited_scene_root()
	var marked: PackedStringArray = []
	for node: Node in root.find_children("*", "", true, false):
		if BBOwnership.is_blender_owned(node):
			marked.append(str(node.name))
	marked.sort()
	_record("první otevření označí art instance",
		marked == PackedStringArray(["Barrel", "Character", "Crate", "Detached", "InRotated", "Tower"]), "označeno: %s" % [marked])

	var saved: String = FileAccess.get_file_as_string("res://fixtures/scenes/basic.tscn")
	_record("scéna je uložená i se značkami", saved.count("metadata/bb_id") == 6, "bb_id v souboru: %d" % saved.count("metadata/bb_id"))
	_record("vedle manifestu je geometrie kontextu", FileAccess.file_exists("res://.pipeline/basic.context.glb"), "")

	var crate: Node3D = root.get_node("Props/Crate")
	var history: UndoRedo = _history(root)
	var version: int = history.get_version()
	await get_tree().create_timer(WATCH_WAIT).timeout
	_record("vlastní zápis manifestu se nenačítá zpět", history.get_version() == version and crate.position.is_equal_approx(Vector3(2, 0, 3)),
		"verze historie %d → %d" % [version, history.get_version()])

	_move_in_manifest("res://.pipeline/basic.json", "Crate", Vector3(7, 0, 3))
	var started: int = Time.get_ticks_msec()
	while not crate.position.is_equal_approx(Vector3(7, 0, 3)) and Time.get_ticks_msec() - started < WATCH_WAIT * 1000:
		await get_tree().process_frame
	_record("změna z Blenderu se načte sama", crate.position.is_equal_approx(Vector3(7, 0, 3)),
		"pozice %s po %d ms" % [crate.position, Time.get_ticks_msec() - started])

	history.undo()
	_record("Ctrl+Z vrátí načtenou změnu jedním krokem", crate.position.is_equal_approx(Vector3(2, 0, 3)), "pozice %s" % crate.position)


func _phase_restart(bridge: EditorPlugin) -> void:
	# Runner před startem posunul Crate v manifestu na (9, 0, 3).
	var root: Node = EditorInterface.get_edited_scene_root()
	var crate: Node3D = root.get_node("Props/Crate")
	await get_tree().create_timer(WATCH_WAIT).timeout
	_record("starý manifest se po startu editoru nenačte naslepo", crate.position.is_equal_approx(Vector3(2, 0, 3)), "pozice %s" % crate.position)

	bridge.call("_import", root, false)
	_record("ruční načtení změn funguje", crate.position.is_equal_approx(Vector3(9, 0, 3)), "pozice %s" % crate.position)


func _phase_context_menu(bridge: EditorPlugin) -> void:
	var opened: Array[String] = []
	var menu: EditorContextMenuPlugin = load("res://addons/blender_bridge/bb_context_menu.gd").new(
		func(path: String) -> void: opened.append(path))
	menu.call("_on_pressed", PackedStringArray(["res://fixtures/scenes/second.tscn"]))
	menu.call("_on_pressed", EditorInterface.get_edited_scene_root())
	_record("kontextové menu pozná cestu ze souboru i z tabu scény",
		opened == ["res://fixtures/scenes/second.tscn", "res://fixtures/scenes/basic.tscn"], "dostal %s" % [opened])

	bridge.call("open_scene_in_blender", "res://fixtures/scenes/second.tscn")
	var args: PackedStringArray = await _fake_blender_args()
	var root: Node = EditorInterface.get_edited_scene_root()
	_record("neaktivní scéna se nejdřív otevře", root != null and root.scene_file_path == "res://fixtures/scenes/second.tscn",
		"aktivní: %s" % (root.scene_file_path if root else "nic"))
	_record("Blender dostane manifest druhé scény", args.size() == 2 and args[1].contains("second.json"), "argumenty: %s" % [args])
	_record("druhá scéna je uložená se značkou",
		FileAccess.get_file_as_string("res://fixtures/scenes/second.tscn").count("metadata/bb_id") == 1, "")


# --------------------------------------------------------------- pomůcky


func _wait_for_scene() -> Node:
	for _attempt: int in 600:
		var root: Node = EditorInterface.get_edited_scene_root()
		if root != null:
			await get_tree().process_frame
			return root
		await get_tree().process_frame
	return null


func _find_bridge() -> EditorPlugin:
	for node: Node in EditorInterface.get_base_control().get_tree().root.find_children("*", "EditorPlugin", true, false):
		var script: Script = node.get_script()
		if script != null and script.resource_path.ends_with(BRIDGE_SCRIPT):
			return node
	return null


func _history(root: Node) -> UndoRedo:
	var manager: EditorUndoRedoManager = EditorInterface.get_editor_undo_redo()
	return manager.get_history_undo_redo(manager.get_object_history_id(root))


func _fake_blender_args() -> PackedStringArray:
	var record: String = OS.get_environment("BB_TEST_OUT").path_join("fake_blender_args.txt")
	for _attempt: int in 300:
		if FileAccess.file_exists(record):
			await get_tree().create_timer(0.2).timeout
			var lines: PackedStringArray = FileAccess.get_file_as_string(record).strip_edges().split("\n")
			DirAccess.remove_absolute(record)
			# Python výraz je víceřádkový; první řádek je přepínač, zbytek výraz.
			return PackedStringArray([lines[0], "\n".join(lines.slice(1))]) if lines.size() > 1 else lines
		await get_tree().create_timer(0.05).timeout
	return PackedStringArray()


func _move_in_manifest(path: String, name: String, origin: Vector3) -> void:
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	for item: Dictionary in manifest["nodes"]:
		if item.get("name") == name:
			item["xform"][9] = origin.x
			item["xform"][10] = origin.y
			item["xform"][11] = origin.z
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	file.store_string(JSON.stringify(manifest, "\t"))
	file.close()


func _record(name: String, passed: bool, message: String) -> void:
	_results.append({"name": "%s: %s" % [_phase, name], "status": "pass" if passed else "fail", "message": "" if passed else message})


func _finish() -> void:
	if _finished:
		return
	_finished = true
	var out: String = OS.get_environment("BB_TEST_OUT").path_join("editor_%s.json" % _phase)
	var file: FileAccess = FileAccess.open(out, FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(_results, "\t"))
		file.close()
	get_tree().quit()
