extends SceneTree

## E2E krok 1 (Godot): scéna se označí jako při kliknutí na tlačítko, uloží,
## vyexportuje se manifest a startovní Python pro Blender. Stav všech nodů
## se zapíše, aby šlo na konci ověřit, že se nic dalšího nezměnilo.

const SCENE: String = "res://fixtures/scenes/basic.tscn"

var _results: Array = []


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var out: String = _arg("--out")
	var root: Node = (load(SCENE) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	root.scene_file_path = SCENE
	get_root().add_child(root)
	await process_frame

	var taken: Dictionary = {}
	for node: Node in root.find_children("*", "", true, false):
		if BBOwnership.is_auto_markable(node, root):
			BBOwnership.assign_id(node, taken)
			taken[BBOwnership.get_id(node)] = node
	_record("označeno 6 modelů", taken.size() == 6, str(taken.size()))

	var packed: PackedScene = PackedScene.new()
	packed.pack(root)
	_record("scéna uložena", ResourceSaver.save(packed, SCENE) == OK, "")
	var manifest: String = BBManifest.write(root)
	_record("manifest zapsán", manifest == "res://.pipeline/basic.json", manifest)

	_write(out.path_join("startup_expr.py"),
		BBLauncher.startup_expression(ProjectSettings.globalize_path(manifest)))
	_write(out.path_join("e2e_before.json"), JSON.stringify(E2E.snapshot(root), "\t"))
	_write(out.path_join("e2e_prepare.json"), JSON.stringify(_results, "\t"))
	quit(0)


func _record(name: String, passed: bool, message: String) -> void:
	_results.append({"name": "godot → manifest: " + name, "status": "pass" if passed else "fail", "message": message})


func _write(path: String, content: String) -> void:
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	file.store_string(content)
	file.close()


func _arg(key: String) -> String:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var index: int = args.find(key)
	return args[index + 1] if index >= 0 else ""


const E2E = preload("res://tests/e2e/snapshot.gd")
