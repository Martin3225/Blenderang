@tool
class_name BBApply
extends RefCounted

## Zápis manifestu upraveného v Blenderu zpět do Godot scény.
##
## Mění se jen transformace nodů s [code]bb_id[/code], přidávají se nové
## instance a mažou ty, které v Blenderu zmizely. Gameplay nody, Terrain3D
## ani cokoli bez [code]bb_id[/code] se nedotkne.

class Plan extends RefCounted:
	var moved: Array[Dictionary] = []
	var added: Array[Dictionary] = []
	var removed: Array[Node] = []
	var pinned: Array[String] = []
	var unresolved: Array[String] = []

	func is_empty() -> bool:
		return moved.is_empty() and added.is_empty() and removed.is_empty()

	func summary() -> String:
		return "přesunuto %d, přidáno %d, smazáno %d, zamčeno %d, nevyřešeno %d" % [
			moved.size(), added.size(), removed.size(), pinned.size(), unresolved.size(),
		]


static func read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	return parsed if parsed is Dictionary else {}


## Spočítá, co by se ve scéně změnilo. Nic nemění — plán jde ukázat
## uživateli dřív, než se do scény sáhne.
static func plan(root: Node, manifest: Dictionary, baseline: Dictionary) -> Plan:
	var result: Plan = Plan.new()
	var duplicates: Array[Node] = []
	var by_id: Dictionary = BBOwnership.collect_ids(root, duplicates)
	var incoming: Dictionary = _index(manifest)

	for id: String in incoming:
		var entry: Dictionary = incoming[id]
		var node: Node = by_id.get(id)
		if node == null:
			result.added.append(entry)
			continue
		if BBOwnership.is_pinned(node):
			result.pinned.append(str(node.name))
			continue
		var target: Transform3D = _deserialize(entry.get("xform", []))
		var node3d: Node3D = node as Node3D
		if node3d == null:
			result.unresolved.append("%s není Node3D" % node.name)
			continue
		if BBManifest.global_xform(node3d, root).is_equal_approx(target):
			continue
		result.moved.append({"node": node3d, "xform": target})

	for id: String in _index(baseline):
		if incoming.has(id) or not by_id.has(id):
			continue
		result.removed.append(by_id[id])

	return result


## Převede plán na seznam konkrétních operací nad scénou. Nic nemění —
## samotný zápis dělá [method commit].
static func operations(root: Node, plan_data: Plan) -> Array[Dictionary]:
	var ops: Array[Dictionary] = []
	for move: Dictionary in plan_data.moved:
		var node: Node3D = move["node"]
		ops.append({
			"kind": "transform",
			"node": node,
			"to": _to_local(node, root, move["xform"]),
			"from": node.transform,
		})
	for entry: Dictionary in plan_data.added:
		var op: Dictionary = _build_add(root, entry, plan_data)
		if not op.is_empty():
			ops.append(op)
	for node: Node in plan_data.removed:
		ops.append({"kind": "remove", "node": node, "parent": node.get_parent(), "owner": root})
	return ops


## Provede operace. Instanční metoda, aby šla zavěsit do undo historie.
func execute(ops: Array[Dictionary]) -> void:
	for op: Dictionary in ops:
		match op["kind"]:
			"transform":
				op["node"].transform = op["to"]
			"add":
				op["parent"].add_child(op["node"])
				op["node"].owner = op["owner"]
			"remove":
				op["parent"].remove_child(op["node"])


func revert(ops: Array[Dictionary]) -> void:
	for op: Dictionary in ops:
		match op["kind"]:
			"transform":
				op["node"].transform = op["from"]
			"add":
				op["parent"].remove_child(op["node"])
			"remove":
				op["parent"].add_child(op["node"])
				op["node"].owner = op["owner"]


## Zavěsí operace do editorové undo historie jako jedinou akci.
static func commit(ops: Array[Dictionary], undo: EditorUndoRedoManager) -> void:
	if ops.is_empty():
		return
	var runner: BBApply = BBApply.new()
	undo.create_action("Blender Bridge: import z Blenderu")
	undo.add_do_method(runner, &"execute", ops)
	undo.add_undo_method(runner, &"revert", ops)
	undo.add_do_reference(runner)
	# Odpojené nody drží jen operace; bez reference by je uvolnil GC.
	for op: Dictionary in ops:
		if op["kind"] == "add":
			undo.add_do_reference(op["node"])
		elif op["kind"] == "remove":
			undo.add_undo_reference(op["node"])
	undo.commit_action()


static func _build_add(root: Node, entry: Dictionary, plan_data: Plan) -> Dictionary:
	var source: String = str(entry.get("src", ""))
	var packed: PackedScene = load(source) as PackedScene
	if packed == null:
		plan_data.unresolved.append("nelze načíst %s" % source)
		return {}
	var parent: Node = root.get_node_or_null(NodePath(str(entry.get("parent", "."))))
	if parent == null:
		parent = root
	var node: Node = packed.instantiate()
	node.name = str(entry.get("name", "BlenderProp"))
	node.set_meta(BBOwnership.META_ID, str(entry.get("bb_id", "")))
	var node3d: Node3D = node as Node3D
	if node3d != null:
		node3d.transform = _to_local_under(parent, root, _deserialize(entry.get("xform", [])))
	return {"kind": "add", "node": node, "parent": parent, "owner": root}


static func _index(manifest: Dictionary) -> Dictionary:
	var result: Dictionary = {}
	for entry: Variant in manifest.get("nodes", []):
		if entry is Dictionary and entry.get("owner") == "blender":
			result[str(entry.get("bb_id", ""))] = entry
	result.erase("")
	return result


static func _deserialize(xform: Array) -> Transform3D:
	if xform.size() != 12:
		return Transform3D.IDENTITY
	return Transform3D(
		Vector3(xform[0], xform[1], xform[2]),
		Vector3(xform[3], xform[4], xform[5]),
		Vector3(xform[6], xform[7], xform[8]),
		Vector3(xform[9], xform[10], xform[11]),
	)


## Manifest nese transformaci vůči kořeni scény. Node ale drží lokální,
## takže se musí odečíst transformace rodičovského řetězce.
static func _to_local(node: Node3D, root: Node, world: Transform3D) -> Transform3D:
	return _to_local_under(node.get_parent(), root, world)


static func _to_local_under(parent: Node, root: Node, world: Transform3D) -> Transform3D:
	var parent3d: Node3D = parent as Node3D
	if parent3d == null or parent == root:
		return world
	return BBManifest.global_xform(parent3d, root).affine_inverse() * world
