extends RefCounted

## Base of the test suites. A test is a [code]test_*[/code] method that calls
## [method done] at the end. A GDScript runtime error silently ends the function;
## without [method done] a crashed test would look like a pass.

const SCENES: String = "res://fixtures/scenes/"
const PIPELINE: String = "res://.pipeline"

var tree: SceneTree
var _failures: PackedStringArray = []
var _fixtures: Array[Node] = []
var _done: bool = false
var _skip: String = ""


func done() -> void:
	_done = true


func skip(reason: String) -> void:
	_skip = reason
	_done = true


func check(condition: bool, message: String) -> void:
	if not condition:
		_failures.append(message)


func eq(actual: Variant, expected: Variant, message: String) -> void:
	if typeof(actual) != typeof(expected) or actual != expected:
		_failures.append("%s: got %s, expected %s" % [message, actual, expected])


func near(actual: Variant, expected: Variant, message: String, epsilon: float = 0.001) -> void:
	if not _near(actual, expected, epsilon):
		_failures.append("%s: got %s, expected %s" % [message, actual, expected])


func _near(a: Variant, b: Variant, epsilon: float) -> bool:
	match typeof(a):
		TYPE_FLOAT, TYPE_INT:
			return absf(float(a) - float(b)) <= epsilon
		TYPE_VECTOR3:
			return (a as Vector3).distance_to(b) <= epsilon
		TYPE_BASIS:
			return _near(a.x, b.x, epsilon) and _near(a.y, b.y, epsilon) and _near(a.z, b.z, epsilon)
		TYPE_TRANSFORM3D:
			return _near(a.basis, b.basis, epsilon) and _near(a.origin, b.origin, epsilon)
	return a == b


## Instance of a test scene added to the tree (Terrain3D doesn't bake without a tree).
func scene(name: String) -> Node:
	var path: String = SCENES + name + ".tscn"
	var root: Node = (load(path) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	root.scene_file_path = path
	tree.root.add_child(root)
	_fixtures.append(root)
	return root


## Marks art instances like the editor does on the first "Open in Blender", only
## with readable ids so tests can find them.
func mark_props(root: Node) -> Array[Node]:
	var marked: Array[Node] = []
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		for child: Node in node.get_children():
			stack.push_back(child)
		if node != root and BBOwnership.is_auto_markable(node, root):
			node.set_meta(BBOwnership.META_ID, "id_" + str(node.name).to_snake_case())
			marked.append(node)
	return marked


func entry(manifest: Dictionary, name: String) -> Dictionary:
	for item: Variant in manifest.get("nodes", []):
		if item is Dictionary and item.get("name") == name:
			return item
	return {}


func origin_of(entry_data: Dictionary) -> Vector3:
	var x: Array = entry_data.get("xform", [])
	return Vector3(x[9], x[10], x[11]) if x.size() == 12 else Vector3.INF


func clear_pipeline() -> void:
	var absolute: String = ProjectSettings.globalize_path(PIPELINE)
	if not DirAccess.dir_exists_absolute(absolute):
		return
	for file: String in DirAccess.get_files_at(absolute):
		DirAccess.remove_absolute(absolute.path_join(file))


func write_file(path: String, content: String) -> void:
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	file.store_string(content)
	file.close()


func remove_file(path: String) -> void:
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))


# Called by the runner.

func _begin() -> void:
	_failures = []
	_done = false
	_skip = ""


func _finish() -> Dictionary:
	for node: Node in _fixtures:
		if is_instance_valid(node):
			node.get_parent().remove_child(node)
			node.free()
	_fixtures.clear()
	if _skip != "":
		return {"status": "skip", "message": _skip}
	if not _done:
		_failures.append("test did not finish (runtime error, see log)")
	if _failures.is_empty():
		return {"status": "pass"}
	return {"status": "fail", "message": "; ".join(_failures)}
