@tool
class_name BBOwnership
extends RefCounted

## Decides who owns a node's position. Blender may write only to nodes
## marked with the [code]bb_id[/code] metadata; everything else is a locked
## reference for it.

const META_ID: StringName = &"bb_id"
const META_PINNED: StringName = &"bb_pinned"
const META_ROOT: StringName = &"bb_root"
## All the bridge's metadata on a node.
const MARKS: Array[StringName] = [META_ID, META_PINNED, META_ROOT]

## Extensions of sources typically authored in Blender. Only a hint for
## bulk marking, not a criterion of ownership.
const ART_EXTENSIONS: PackedStringArray = ["glb", "gltf", "fbx", "blend", "obj"]


static func is_blender_owned(node: Node) -> bool:
	return node.has_meta(META_ID)


static func is_pinned(node: Node) -> bool:
	return node.get_meta(META_PINNED, false)


static func is_layout_root(node: Node) -> bool:
	return node.get_meta(META_ROOT, false)


static func get_id(node: Node) -> String:
	return str(node.get_meta(META_ID, ""))


static func generate_id() -> String:
	return "%08x%08x" % [randi(), randi()]


## Gives the node a new id. Returns [code]false[/code] if it already has one.
static func assign_id(node: Node, taken: Dictionary) -> bool:
	if is_blender_owned(node) and not taken.has(get_id(node)):
		return false
	var id: String = generate_id()
	while taken.has(id):
		id = generate_id()
	node.set_meta(META_ID, id)
	return true


## A node is a candidate for management from Blender if it's a Node3D instanced
## from an external scene whose source is an art asset.
static func looks_like_prop(node: Node) -> bool:
	if not node is Node3D:
		return false
	var src: String = node.scene_file_path
	if src.is_empty():
		return false
	return ART_EXTENSIONS.has(src.get_extension().to_lower())


## Bulk marking skips the insides of other instances and anything under a
## physics body; those are gameplay units whose composition Blender
## must not change.
static func is_auto_markable(node: Node, root: Node) -> bool:
	if not looks_like_prop(node):
		return false
	if node.owner != root:
		return false
	var parent: Node = node.get_parent()
	while parent != null and parent != root:
		if parent is CollisionObject3D:
			return false
		parent = parent.get_parent()
	return true


## Walks the tree and returns all ids already assigned. Duplicate ids (created
## by copying a node in the editor) are reported in [code]duplicates[/code].
static func collect_ids(root: Node, duplicates: Array[Node]) -> Dictionary:
	var taken: Dictionary = {}
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if is_blender_owned(node):
			var id: String = get_id(node)
			if id.is_empty() or taken.has(id):
				duplicates.append(node)
			else:
				taken[id] = node
		for child: Node in node.get_children():
			stack.push_back(child)
	return taken


## Marks of all scene nodes by path from the root. When reimporting an asset,
## Godot replaces its instances in the open scene with new nodes and drops the
## instance metadata; these let you put them back, see [method restore_marks].
static func snapshot_marks(root: Node) -> Dictionary:
	var marks: Dictionary = {}
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		var meta: Dictionary = {}
		for key: StringName in MARKS:
			if node.has_meta(key):
				meta[key] = node.get_meta(key)
		if not meta.is_empty():
			marks[root.get_path_to(node)] = {"src": node.scene_file_path, "meta": meta}
		for child: Node in node.get_children():
			stack.push_back(child)
	return marks


## Gives marks back to nodes that lost them. A node must match by path and by
## asset; a node that has any mark is left untouched. Returns the number of fixed nodes.
static func restore_marks(root: Node, marks: Dictionary) -> int:
	var restored: int = 0
	for path: NodePath in marks:
		var node: Node = root.get_node_or_null(path)
		var record: Dictionary = marks[path]
		if node == null or node.scene_file_path != record["src"]:
			continue
		if MARKS.any(func(key: StringName) -> bool: return node.has_meta(key)):
			continue
		for key: StringName in record["meta"]:
			node.set_meta(key, record["meta"][key])
		restored += 1
	return restored
