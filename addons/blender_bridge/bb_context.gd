@tool
class_name BBContext
extends RefCounted

## Skutečná geometrie všeho, co vlastní Godot (hráč, postavy, terén, …), jako
## jeden [code].glb[/code] vedle manifestu. Blender ho naimportuje jako
## zamčený kontext — místo prázdných obálek je vidět, co ve scéně opravdu je.
##
## Obsahuje jen meshe a jejich materiály. Skripty, kolize, světla ani
## MultiMesh (tráva, stromy z ProtonScatteru) se nepřenáší.

## Terrain3D se peče do meshe; LOD 4 = vrchol každých 16 m. Pro referenci
## při rozmisťování stačí a 8×4 km terén má kolem 120 tisíc vrcholů.
const TERRAIN_LOD: int = 4


static func path_for(manifest_path: String) -> String:
	return manifest_path.get_basename() + ".context.glb"


## Postaví dočasný strom s kopiemi meshů a uloží ho jako glTF. Vrací cestu,
## nebo prázdný řetězec při chybě.
static func write(root: Node, manifest: Dictionary, manifest_path: String) -> String:
	var tree: Node3D = _build(root, manifest)
	var document: GLTFDocument = GLTFDocument.new()
	var state: GLTFState = GLTFState.new()
	var path: String = path_for(manifest_path)
	var err: Error = document.append_from_scene(tree, state)
	if err == OK:
		err = document.write_to_filesystem(state, ProjectSettings.globalize_path(path))
	tree.free()
	if err != OK:
		push_error("Blender Bridge: kontext scény se nepodařilo zapsat (%d)" % err)
		return ""
	return path


static func _build(root: Node, manifest: Dictionary) -> Node3D:
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
			_add_terrain(node, unit)
		else:
			_add_meshes(node, unit, root, units)
		# Readable unique name: dva „StaticBody3D“ z různých rodičů vedle sebe.
		tree.add_child(unit, true)
	return tree


static func _add_terrain(terrain: Node3D, unit: Node3D) -> void:
	var mesh: Mesh = terrain.call("bake_mesh", TERRAIN_LOD, 0)
	if mesh == null:
		return
	var instance: MeshInstance3D = MeshInstance3D.new()
	instance.name = "TerrainMesh"
	instance.mesh = mesh
	# Terrain3D peče ve světových souřadnicích; vyrovná se transformace jednotky.
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


## Co do geometrie jednotky nepatří:
## - objekty, které vlastní Blender (přijdou do Blenderu zvlášť),
## - jiné jednotky kontextu (mají vlastní záznam, jinak by byly dvakrát),
## - interní nody pluginů bez ownera, např. MouseQuad uvnitř Terrain3D.
static func _skip(node: Node, root: Node, units: Dictionary) -> bool:
	if BBOwnership.is_blender_owned(node) or units.has(node):
		return true
	return node.owner == null and node != root
