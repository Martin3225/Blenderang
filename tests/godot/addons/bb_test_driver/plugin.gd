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
		"reimport":
			await _phase_reimport(bridge)
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
		marked == PackedStringArray(["Barrel", "Character", "Crate", "Detached", "Helmet", "InRotated", "Tower"]), "označeno: %s" % [marked])

	var saved: String = FileAccess.get_file_as_string("res://fixtures/scenes/basic.tscn")
	_record("scéna je uložená i se značkami", saved.count("metadata/bb_id") == 7, "bb_id v souboru: %d" % saved.count("metadata/bb_id"))
	# V editoru glTF export přeskakuje nody bez ownera — tady se to projeví,
	# mimo editor ne.
	var context: Dictionary = _glb_json("res://.pipeline/basic.context.glb")
	var names: PackedStringArray = []
	for node: Dictionary in context.get("nodes", []):
		names.append(str(node.get("name", "")))
	_record("kontext z editoru obsahuje geometrii scény",
		names.has("Building") and names.has("Player") and context.get("meshes", []).size() >= 3,
		"nody: %s, meshe: %d" % [names, context.get("meshes", []).size()])

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


## Ctrl+S ve zdroji modelu přepíše jeho .glb a Godot ho reimportuje, zatímco
## je scéna otevřená. Další otevření v Blenderu musí dát stejný manifest.
func _phase_reimport(bridge: EditorPlugin) -> void:
	var button: Button = bridge.get("_toolbar_button")
	button.pressed.emit()
	await _fake_blender_args()
	var before: Dictionary = _manifest_summary("res://.pipeline/terrain.json")
	_record("první otevření: model i terén", before["models"] == ["CrateOnHill"] and before["terrain"] and before["terrain_mesh"],
		"%s" % before)

	# Co udělá Ctrl+S v Blenderu: zdroj vedle assetu a nový .glb.
	var asset: String = "res://fixtures/assets/crate.glb"
	var original: PackedByteArray = FileAccess.get_file_as_bytes(asset)
	DirAccess.copy_absolute(ProjectSettings.globalize_path("res://fixtures/assets/tower.glb"), ProjectSettings.globalize_path(asset))
	var blend: FileAccess = FileAccess.open("res://fixtures/assets/crate.blend", FileAccess.WRITE)
	blend.store_string("BLENDER")
	blend.close()
	await _reimport(asset)

	var root: Node = EditorInterface.get_edited_scene_root()
	var crate: Node = root.get_node_or_null("Nav/CrateOnHill")
	_record("model po reimportu zůstane označený", crate != null and BBOwnership.is_blender_owned(crate),
		"CrateOnHill=%s meta=%s" % [crate, crate.get_meta_list() if crate else []])

	button.pressed.emit()
	await _fake_blender_args()
	var after: Dictionary = _manifest_summary("res://.pipeline/terrain.json")
	_record("další otevření po reimportu: model i terén", after["models"] == ["CrateOnHill"] and after["terrain"] and after["terrain_mesh"],
		"%s" % after)
	# Nové id by znamenalo, že ho označil až první-otevření záchranou; ve scéně
	# s víc modely by se neoznačil vůbec a NavigationRegion3D by spolkl terén.
	_record("model si po reimportu nechá své id", after["ids"] == before["ids"], "před %s, po %s" % [before["ids"], after["ids"]])
	_record("model po reimportu je nalinkovaný ze zdroje", after["tiers"] == ["library"], "%s" % after)

	# Další sady sdílí import cache — asset musí zůstat původní.
	var file: FileAccess = FileAccess.open(asset, FileAccess.WRITE)
	file.store_buffer(original)
	file.close()
	DirAccess.remove_absolute(ProjectSettings.globalize_path("res://fixtures/assets/crate.blend"))
	await _reimport(asset)


## Reimport natvrdo: scan() by změnu ve stejné sekundě (stejný mtime)
## přehlédl a čekání by nikdy neskončilo. Jde přes stejné signály jako
## reimport po uložení z Blenderu.
func _reimport(asset: String) -> void:
	EditorInterface.get_resource_filesystem().reimport_files(PackedStringArray([asset]))
	for _frame: int in 30:
		await get_tree().process_frame


func _manifest_summary(path: String) -> Dictionary:
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	var models: Array = []
	var ids: Array = []
	var tiers: Array = []
	var terrain: bool = false
	for item: Dictionary in manifest.get("nodes", []):
		if item.get("owner") == "blender":
			models.append(item["name"])
			ids.append(item["bb_id"])
			tiers.append(item.get("tier"))
		elif item.get("kind") == "terrain":
			terrain = true
	var names: Array = []
	for node: Dictionary in _glb_json("res://" + str(manifest.get("context_glb", ""))).get("nodes", []):
		names.append(node.get("name"))
	return {"models": models, "ids": ids, "tiers": tiers, "terrain": terrain, "terrain_mesh": names.has("TerrainMesh"), "context": names}


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


## JSON část .glb souboru (bez binárního bufferu).
func _glb_json(path: String) -> Dictionary:
	var bytes: PackedByteArray = FileAccess.get_file_as_bytes(path)
	if bytes.size() < 20:
		return {}
	var length: int = bytes.decode_u32(12)
	var parsed: Variant = JSON.parse_string(bytes.slice(20, 20 + length).get_string_from_utf8())
	return parsed if parsed is Dictionary else {}


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
