extends SceneTree

## E2E step 1 (Godot): the scene is marked as when clicking the button, saved,
## and the manifest and startup Python for Blender are exported. The state of all
## nodes is recorded so the end can verify nothing else changed.

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
	_record("7 models marked", taken.size() == 7, str(taken.size()))

	var packed: PackedScene = PackedScene.new()
	packed.pack(root)
	_record("scene saved", ResourceSaver.save(packed, SCENE) == OK, "")
	var manifest: String = BBManifest.write(root)
	_record("manifest written", manifest == "res://.pipeline/basic.json", manifest)

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
