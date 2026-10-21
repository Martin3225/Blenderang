@tool
class_name BBManifest
extends RefCounted

## Serializace rozmístění objektů Godot scény do JSON manifestu pro Blender.
##
## Manifest obsahuje pouze transformace a identity, nikdy geometrii. Nody
## vlastněné Blenderem ([BBOwnership.META_ID]) jsou editovatelné, všechno
## ostatní jde do Blenderu jako zamčená reference (proxy), aby bylo vidět,
## kde stojí hráč, terén nebo ručně skládané objekty.

const FORMAT_VERSION: int = 1
const PIPELINE_DIR: String = "res://.pipeline"

## Souřadný systém manifestu je Godot: Y nahoru, -Z dopředu, pravotočivý.
## Převod do Blenderu (Z nahoru) dělá addon na druhé straně.
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


## Zapíše manifest a vedle něj snímek stavu, proti kterému se při importu
## počítá diff. Bez snímku by nešlo odlišit „v Blenderu objekt přibyl“ od
## „v Blenderu objekt chybí, protože ho tam nikdo nikdy neměl“.
static func write(root: Node) -> String:
	var dir_err: Error = DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(PIPELINE_DIR))
	if dir_err != OK and dir_err != ERR_ALREADY_EXISTS:
		push_error("Blender Bridge: nelze vytvořit %s (%d)" % [PIPELINE_DIR, dir_err])
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
		push_error("Blender Bridge: nelze zapsat %s (%d)" % [path, FileAccess.get_open_error()])
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
		# Děti přidané ve scéně (výstroj na armatuře, marker na modelu) jsou
		# samostatné nody. Vnitřek instancovaného assetu ne — ten patří assetu.
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
	# Proxy se dál nerozbaluje, ale spravované objekty uvnitř (např. budova
	# zavěšená pod NavigationRegion3D) se najít musí. Terén taky — jeho meshe
	# jsou interní nody bez ownera a do geometrie rodiče se nedostanou.
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


## Organizační Node3D bez skriptu, bez instance a bez vlastního obsahu
## (Lighting, Models, …) se do manifestu nedostane, jen se jím projde.
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
	# Obálka slouží jako kontext při úpravě jiného assetu v jeho vlastním
	# .blend — je vidět, co stojí kolem, aniž by se cokoli importovalo.
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


## Transformace vůči kořeni scény. Počítá se ručně, aby funkce fungovala
## i na stromu, který není přidaný do SceneTree (headless export).
##
## Node s [code]top_level[/code] (např. Terrain3D) rodiče ignoruje — jeho
## transformace už je globální.
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


## Obálka celého podstromu v lokálním prostoru [param node]. Slouží
## k vygenerování zamčeného proxy tvaru v Blenderu.
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
