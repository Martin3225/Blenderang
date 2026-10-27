extends SceneTree

## E2E step 3 (Godot): loads the changes from Blender, saves the scene, loads it
## again from disk and compares it with the fingerprint from step 1.

const SCENE: String = "res://fixtures/scenes/basic.tscn"
const E2E = preload("res://tests/e2e/snapshot.gd")

var _results: Array = []


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var out: String = _arg("--out")
	var root: Node = _load()
	var manifest: Dictionary = BBApply.read_json("res://.pipeline/basic.json")
	var baseline: Dictionary = BBApply.read_json("res://.pipeline/basic.last.json")
	var plan: BBApply.Plan = BBApply.plan(root, manifest, baseline)
	_record("change plan", plan.moved.size() == 4 and plan.added.size() == 1 and plan.removed.size() == 1 and plan.unresolved.is_empty(),
		plan.summary())
	BBApply.new().execute(BBApply.operations(root, plan))

	var packed: PackedScene = PackedScene.new()
	packed.pack(root)
	ResourceSaver.save(packed, SCENE)
	root.get_parent().remove_child(root)
	root.free()
	root = _load()

	_record("Crate's move is in the saved scene", _origin(root, "Props/Crate").is_equal_approx(Vector3(5, 0, 3)),
		str(_origin(root, "Props/Crate")))
	var rotated: Basis = BBManifest.global_xform(root.get_node("Rotated/InRotated"), root).basis
	var expected: Basis = Basis(Vector3.UP, deg_to_rad(135)).scaled(Vector3(2, 2, 2))
	_record("rotation under a rotated and scaled parent", _basis_near(rotated, expected), "%s vs %s" % [rotated, expected])

	var copy: Node3D = root.get_node_or_null("Props/TowerCopy")
	_record("the duplicate is a new instance under Props", copy != null and copy.scene_file_path == "res://fixtures/assets/tower.glb",
		"node: %s" % copy)
	if copy != null:
		_record("the duplicate has its own id", BBOwnership.get_id(copy) != BBOwnership.get_id(root.get_node("Props/Tower")), "")
		_record("the duplicate stands where Blender put it", _origin(root, "Props/TowerCopy").is_equal_approx(Vector3(1, 0, 1)),
			str(_origin(root, "Props/TowerCopy")))
	_record("gear moved with the model and stayed its child",
		_origin(root, "Character/Helmet").is_equal_approx(Vector3(7, 1.8, -2)), str(_origin(root, "Character/Helmet")))
	_record("deleted Barrel is gone", root.get_node_or_null("Props/Barrel") == null, "")
	_record("a helper object from Blender didn't come through", root.find_child("Helper", true, false) == null, "")

	var before: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(out.path_join("e2e_before.json")))
	var after: Dictionary = E2E.snapshot(root)
	var changed: PackedStringArray = []
	for path: String in before:
		if path.begins_with("Props/Crate") or path.begins_with("Rotated/InRotated") or path.begins_with("Props/Barrel") \
				or path.begins_with("Character"):
			continue
		if not after.has(path) or not E2E.same(before[path], after[path]):
			changed.append(path)
	_record("nothing else changed", changed.is_empty(), "changed: %s" % [changed])

	_record("loading again is a no-op",
		BBApply.plan(root, manifest, manifest).is_empty(), "")

	var fresh: Dictionary = BBManifest.export_scene(root)
	var crate: Dictionary = {}
	for item: Dictionary in fresh["nodes"]:
		if item.get("name") == "Crate":
			crate = item
	_record("Godot sees the source made in Blender", crate.get("tier") == "library"
		and crate.get("src_blend") == "fixtures/assets/crate.blend", "tier=%s" % crate.get("tier"))

	var file: FileAccess = FileAccess.open(out.path_join("e2e_verify.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(_results, "\t"))
	file.close()
	quit(0)


func _load() -> Node:
	var root: Node = (ResourceLoader.load(SCENE, "", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	root.scene_file_path = SCENE
	get_root().add_child(root)
	return root


func _origin(root: Node, path: String) -> Vector3:
	var node: Node3D = root.get_node_or_null(path)
	return BBManifest.global_xform(node, root).origin if node else Vector3.INF


func _basis_near(a: Basis, b: Basis) -> bool:
	return a.x.distance_to(b.x) < 0.001 and a.y.distance_to(b.y) < 0.001 and a.z.distance_to(b.z) < 0.001


func _record(name: String, passed: bool, message: String) -> void:
	_results.append({"name": "blender → godot: " + name, "status": "pass" if passed else "fail", "message": "" if passed else message})


func _arg(key: String) -> String:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var index: int = args.find(key)
	return args[index + 1] if index >= 0 else ""
