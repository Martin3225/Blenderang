@tool
class_name BBManifest
extends RefCounted

## Serializes the layout of a Godot scene into a JSON manifest for Blender.
##
## The manifest holds only transforms and identities, never geometry. Nodes
## owned by Blender ([BBOwnership.META_ID]) are editable; everything else
## goes to Blender as a locked reference (proxy), so you can see where the
## player, the terrain or hand-assembled objects are.

const FORMAT_VERSION: int = 1
const PIPELINE_DIR: String = "res://.pipeline"

## The manifest's coordinate system is Godot's: Y up, -Z forward, right-handed.
## Conversion to Blender (Z up) is done by the add-on on the other side.
const COORD_SYSTEM: String = "godot_y_up"


class Walk extends RefCounted:
	var nodes: Array = []
	var duplicates: Array[Node] = []


static func export_scene(root: Node) -> Dictionary:
	var walk: Walk = Walk.new()
	BBOwnership.collect_ids(root, walk.duplicates)
	_walk_children(root, root, walk)
	return {
		"format": FORMAT_VERSION,
		"coord_system": COORD_SYSTEM,
		"scene": root.scene_file_path,
		"root_name": root.name,
		"nodes": walk.nodes,
	}


static func manifest_path(root: Node) -> String:
	var base: String = root.scene_file_path.get_file().get_basename()
	if base.is_empty():
		base = str(root.name).to_snake_case()
	return "%s/%s.json" % [PIPELINE_DIR, base]


static func baseline_path(root: Node) -> String:
	return manifest_path(root).get_basename() + ".last.json"


## Writes the manifest and next to it a snapshot of the state that the import
## diffs against. Without the snapshot you couldn't tell "an object was added in
## Blender" from "the object is missing in Blender because nobody ever had it there".
static func write(root: Node) -> String:
	var dir_err: Error = DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(PIPELINE_DIR))
	if dir_err != OK and dir_err != ERR_ALREADY_EXISTS:
		push_error("Blenderang: cannot create %s (%d)" % [PIPELINE_DIR, dir_err])
		return ""
	_ensure_gdignore()
	var manifest: Dictionary = export_scene(root)
	var path: String = manifest_path(root)
	var context: String = BBContext.write(root, manifest, path)
	if not context.is_empty():
		manifest["context_glb"] = context.trim_prefix("res://")
	var payload: String = JSON.stringify(manifest, "\t")
	if not store(path, payload) or not store(baseline_path(root), payload):
		return ""
	return path


static func store(path: String, payload: String) -> bool:
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Blenderang: cannot write %s (%d)" % [path, FileAccess.get_open_error()])
		return false
	file.store_string(payload)
	file.close()
	return true


static func _ensure_gdignore() -> void:
	var marker: String = "%s/.gdignore" % PIPELINE_DIR
	if FileAccess.file_exists(marker):
		return
	var file: FileAccess = FileAccess.open(marker, FileAccess.WRITE)
	if file != null:
		file.close()


static func _walk_children(node: Node, root: Node, walk: Walk) -> void:
	for child: Node in node.get_children():
		_visit(child, root, walk)


static func _visit(node: Node, root: Node, walk: Walk) -> void:
	if BBOwnership.is_blender_owned(node):
		walk.nodes.append(_prop_entry(node, root))
		# Children added in the scene (gear on an armature, a marker on a model) are
		# separate nodes. The inside of an instanced asset isn't; that belongs to the asset.
		for child: Node in node.get_children():
			if child.owner == root:
				_visit(child, root, walk)
		return
	if not node is Node3D:
		_walk_children(node, root, walk)
		return
	if BBOwnership.is_layout_root(node) or _is_container(node):
		_walk_children(node, root, walk)
		return
	walk.nodes.append(_proxy_entry(node as Node3D, root))
	# A proxy isn't expanded further, but managed objects inside it (e.g. a building
	# under NavigationRegion3D) must be found. The terrain too: its meshes are
	# internal nodes without an owner and won't get into the parent's geometry.
	if _contains_own_entries(node):
		_walk_children(node, root, walk)


static func _contains_own_entries(node: Node) -> bool:
	var stack: Array[Node] = [node]
	while not stack.is_empty():
		var current: Node = stack.pop_back()
		for child: Node in current.get_children():
			if BBOwnership.is_blender_owned(child) or _is_terrain(child):
				return true
			stack.push_back(child)
	return false


static func _is_terrain(node: Node) -> bool:
	return node.has_method("get_data_directory")


## An organisational Node3D with no script, no instance and no content of its
## own (Lighting, Models, …) isn't put into the manifest, only walked through.
static func _is_container(node: Node) -> bool:
	if node.get_class() != "Node3D":
		return false
	if node.get_script() != null:
		return false
	return node.scene_file_path.is_empty()


static func _prop_entry(node: Node, root: Node) -> Dictionary:
	var node3d: Node3D = node as Node3D
	var entry: Dictionary = {
		"bb_id": BBOwnership.get_id(node),
		"owner": "blender",
		"name": str(node.name),
		"path": str(root.get_path_to(node)),
		"parent": str(root.get_path_to(node.get_parent())),
		"src": node.scene_file_path,
		"xform": _serialize_xform(global_xform(node3d, root)),
		"tier": BBPaths.tier_for(node.scene_file_path),
	}
	# The bounding box serves as context when editing another asset in its own
	# .blend, so you can see what stands around it without importing anything.
	if node3d != null:
		entry["bounds"] = _serialize_aabb(_subtree_aabb(node3d))
	var source: String = BBPaths.source_for(node.scene_file_path)
	if source.is_empty():
		entry["src_blend_missing"] = BBPaths.expected_source_for(node.scene_file_path)
	else:
		entry["src_blend"] = source
	if BBOwnership.is_pinned(node):
		entry["pinned"] = true
	if node3d != null and not node3d.visible:
		entry["visible"] = false
	return entry


static func _proxy_entry(node: Node3D, root: Node) -> Dictionary:
	var entry: Dictionary = {
		"owner": "godot",
		"name": str(node.name),
		"path": str(root.get_path_to(node)),
		"type": node.get_class(),
		"xform": _serialize_xform(global_xform(node, root)),
		"bounds": _serialize_aabb(_subtree_aabb(node)),
	}
	if not node.scene_file_path.is_empty():
		entry["src"] = node.scene_file_path
	if _is_terrain(node):
		entry["kind"] = "terrain"
		entry["data_directory"] = node.get("data_directory")
	if not node.visible:
		entry["visible"] = false
	return entry


## Transform relative to the scene root. Computed by hand so the function also
## works on a tree that isn't added to the SceneTree (headless export).
##
## A node with [code]top_level[/code] (e.g. Terrain3D) ignores its parents; its
## transform is already global.
static func global_xform(node: Node3D, root: Node) -> Transform3D:
	if node == null:
		return Transform3D.IDENTITY
	var xform: Transform3D = Transform3D.IDENTITY
	var current: Node = node
	while current != null and current != root:
		var spatial: Node3D = current as Node3D
		if spatial != null:
			xform = spatial.transform * xform
			if spatial.top_level:
				break
		current = current.get_parent()
	return xform


## Bounding box of the whole subtree in the local space of [param node]. Used
## to generate the locked proxy shape in Blender.
static func _subtree_aabb(node: Node3D) -> AABB:
	var result: AABB = AABB()
	var found: bool = false
	var stack: Array[Node] = [node]
	while not stack.is_empty():
		var current: Node = stack.pop_back()
		for child: Node in current.get_children():
			stack.push_back(child)
		var visual: VisualInstance3D = current as VisualInstance3D
		if visual == null:
			continue
		var local: AABB = global_xform(visual, node) * visual.get_aabb()
		if found:
			result = result.merge(local)
		else:
			result = local
			found = true
	if not found:
		return AABB(Vector3(-0.5, 0.0, -0.5), Vector3.ONE)
	return result


static func _serialize_xform(xform: Transform3D) -> Array:
	var b: Basis = xform.basis
	return [
		b.x.x, b.x.y, b.x.z,
		b.y.x, b.y.y, b.y.z,
		b.z.x, b.z.y, b.z.z,
		xform.origin.x, xform.origin.y, xform.origin.z,
	]


static func _serialize_aabb(aabb: AABB) -> Dictionary:
	return {
		"position": [aabb.position.x, aabb.position.y, aabb.position.z],
		"size": [aabb.size.x, aabb.size.y, aabb.size.z],
	}
