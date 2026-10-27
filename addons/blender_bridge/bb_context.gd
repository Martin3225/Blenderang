@tool
class_name BBContext
extends RefCounted

## Real geometry of everything Godot owns (player, characters, terrain, …) as
## a single [code].glb[/code] next to the manifest. Blender imports it as
## locked context, so instead of empty bounding boxes you see what's really in the scene.
##
## Contains only meshes and their materials. Scripts, collisions, lights and
## MultiMesh (grass, trees from ProtonScatter) are not transferred.

## Terrain3D is baked into a mesh with a baked colour, see BBTerrain.


static func path_for(manifest_path: String) -> String:
	return manifest_path.get_basename() + ".context.glb"


## Builds a temporary tree with copies of the meshes and saves it as glTF. Returns
## the path, or an empty string when there's nothing to export or the export fails;
## Blender then uses the bounding boxes from the manifest instead of geometry.
static func write(root: Node, manifest: Dictionary, manifest_path: String) -> String:
	var tree: Node3D = _build(root, manifest, manifest_path.get_basename())
	var path: String = path_for(manifest_path)
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
	if tree.find_children("*", "MeshInstance3D", true, false).is_empty():
		# A glTF without a single mesh has an empty buffer and Blender refuses to load it.
		tree.free()
		return ""
	# In the editor, glTF export skips nodes without an owner (like when saving
	# a scene). Outside the editor it doesn't, which is why headless tests missed it for a long time.
	for node: Node in tree.find_children("*", "", true, false):
		node.owner = tree
	var document: GLTFDocument = GLTFDocument.new()
	var state: GLTFState = GLTFState.new()
	var err: Error = document.append_from_scene(tree, state)
	if err == OK:
		err = document.write_to_filesystem(state, ProjectSettings.globalize_path(path))
	tree.free()
	if err != OK:
		push_error("Blender Bridge: could not write the scene context (%d)" % err)
		return ""
	return path


static func _build(root: Node, manifest: Dictionary, cache_base: String) -> Node3D:
	var tree: Node3D = Node3D.new()
	tree.name = "Godot"
	var units: Dictionary = {}
	for entry: Variant in manifest.get("nodes", []):
		if entry is Dictionary and entry.get("owner") == "godot":
			var node: Node3D = root.get_node_or_null(NodePath(str(entry["path"]))) as Node3D
			if node != null:
				units[node] = entry
	for node: Node3D in units:
		var entry: Dictionary = units[node]
		var unit: Node3D = Node3D.new()
		unit.name = str(entry["name"])
		unit.transform = BBManifest.global_xform(node, root)
		if entry.get("kind") == "terrain":
			_add_terrain(node, unit, cache_base)
		else:
			_add_meshes(node, unit, root, units)
		# Readable unique name: two "StaticBody3D" from different parents side by side.
		tree.add_child(unit, true)
	return tree


static func _add_terrain(terrain: Node3D, unit: Node3D, cache_base: String) -> void:
	var mesh: Mesh = BBTerrain.mesh_with_material(terrain, cache_base)
	if mesh == null:
		return
	var instance: MeshInstance3D = MeshInstance3D.new()
	instance.name = "TerrainMesh"
	instance.mesh = mesh
	# Terrain3D bakes in world coordinates; cancel out the unit's transform.
	instance.transform = unit.transform.affine_inverse()
	unit.add_child(instance)


static func _add_meshes(node: Node3D, unit: Node3D, root: Node, units: Dictionary) -> void:
	var stack: Array[Node] = [node]
	while not stack.is_empty():
		var current: Node = stack.pop_back()
		if current != node and _skip(current, root, units):
			continue
		for child: Node in current.get_children():
			stack.push_back(child)
		var source: MeshInstance3D = current as MeshInstance3D
		if source == null or source.mesh == null:
			continue
		var copy: MeshInstance3D = MeshInstance3D.new()
		copy.name = source.name
		copy.mesh = source.mesh
		copy.material_override = source.material_override
		for surface: int in source.get_surface_override_material_count():
			copy.set_surface_override_material(surface, source.get_surface_override_material(surface))
		copy.transform = BBManifest.global_xform(source, node)
		unit.add_child(copy, true)


## What doesn't belong in a unit's geometry:
## - objects owned by Blender (they go to Blender separately),
## - other context units (they have their own entry, otherwise they'd appear twice),
## - internal plugin nodes without an owner, e.g. MouseQuad inside Terrain3D.
static func _skip(node: Node, root: Node, units: Dictionary) -> bool:
	if BBOwnership.is_blender_owned(node) or units.has(node):
		return true
	return node.owner == null and node != root
