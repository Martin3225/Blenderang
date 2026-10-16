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

	_rescue_children(root, result, incoming, by_id)
	return result


## V Blenderu po smazání rodiče děti zůstanou, v Godotu by zmizely s ním.
## Takové děti se přidají znovu pod nejbližšího předka, který zůstává.
static func _rescue_children(root: Node, result: Plan, incoming: Dictionary, by_id: Dictionary) -> void:
	if result.removed.is_empty():
		return
	for id: String in incoming:
		var node: Node = by_id.get(id)
		if node == null or result.removed.has(node) or not _under_removed(node.get_parent(), root, result.removed):
			continue
		var keeper: Node = node.get_parent()
		while keeper != root and _under_removed(keeper, root, result.removed):
			keeper = keeper.get_parent()
		var entry: Dictionary = (incoming[id] as Dictionary).duplicate(true)
		entry["parent"] = str(root.get_path_to(keeper))
		result.added.append(entry)
		for index: int in range(result.moved.size() - 1, -1, -1):
			if result.moved[index]["node"] == node:
				result.moved.remove_at(index)


static func _under_removed(node: Node, root: Node, removed: Array[Node]) -> bool:
	var current: Node = node
	while current != null and current != root:
		if removed.has(current):
			return true
		current = current.get_parent()
	return false


## Převede plán na seznam konkrétních operací nad scénou. Nic nemění —
## samotný zápis dělá [method commit].
static func operations(root: Node, plan_data: Plan) -> Array[Dictionary]:
	var ops: Array[Dictionary] = []
	# Nové světové transformace všech přesouvaných nodů. Lokální transformace
	# dítěte se musí počítat vůči NOVÉ pozici rodiče — v Blenderu se dítě
	# s rodičem posunulo, takže by se jinak posunulo dvakrát.
	var targets: Dictionary = {}
	for move: Dictionary in plan_data.moved:
		targets[move["node"]] = move["xform"]
	for move: Dictionary in plan_data.moved:
		var node: Node3D = move["node"]
		ops.append({
			"kind": "transform",
			"node": node,
			"to": _to_local(node, root, move["xform"], targets),
			"from": node.transform,
		})
	for entry: Dictionary in plan_data.added:
		var op: Dictionary = _build_add(root, entry, plan_data, targets)
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


## Zavěsí operace do undo historie scény jako jedinou akci.
##
## Kontext historie je kořen scény: operace se volají na pomocném objektu,
## podle kterého by editor akci zařadil do globální historie a Ctrl+Z ve
## scéně by ji nevrátil. Scéna se tím zároveň označí jako neuložená.
static func commit(root: Node, ops: Array[Dictionary], undo: EditorUndoRedoManager) -> void:
	if ops.is_empty():
		return
	var runner: BBApply = BBApply.new()
	undo.create_action("Blender Bridge: import z Blenderu", UndoRedo.MERGE_DISABLE, root)
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


static func _build_add(root: Node, entry: Dictionary, plan_data: Plan, targets: Dictionary) -> Dictionary:
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
		node3d.transform = _to_local_under(parent, root, _deserialize(entry.get("xform", [])), targets)
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
## takže se musí odečíst transformace rodičovského řetězce — kromě nodu
## s [code]top_level[/code], jehož transformace už globální je.
static func _to_local(node: Node3D, root: Node, world: Transform3D, targets: Dictionary) -> Transform3D:
	if node.top_level:
		return world
	return _to_local_under(node.get_parent(), root, world, targets)


static func _to_local_under(parent: Node, root: Node, world: Transform3D, targets: Dictionary) -> Transform3D:
	return _planned_global(parent, root, targets).affine_inverse() * world


## Světová transformace nodu po provedení plánu: přesouvané nody mají
## novou, ostatní skládají rodiče (včetně těch přesouvaných).
static func _planned_global(node: Node, root: Node, targets: Dictionary) -> Transform3D:
	if node == null or node == root:
		return Transform3D.IDENTITY
	if targets.has(node):
		return targets[node]
	var spatial: Node3D = node as Node3D
	if spatial == null:
		return _planned_global(node.get_parent(), root, targets)
	if spatial.top_level:
		return spatial.transform
	return _planned_global(node.get_parent(), root, targets) * spatial.transform
