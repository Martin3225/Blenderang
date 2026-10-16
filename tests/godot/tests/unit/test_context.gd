extends "res://tests/bb_test.gd"

## Geometrie kontextu (.context.glb) — co z Godotu uvidí Blender jako zamčené okolí.


func _load_context(path: String) -> Node:
	var document: GLTFDocument = GLTFDocument.new()
	var state: GLTFState = GLTFState.new()
	if document.append_from_file(ProjectSettings.globalize_path(path), state) != OK:
		return null
	var generated: Node = document.generate_scene(state)
	tree.root.add_child(generated)
	_fixtures.append(generated)
	return generated


func _meshes(node: Node) -> Array[MeshInstance3D]:
	var found: Array[MeshInstance3D] = []
	for child: Node in node.find_children("*", "MeshInstance3D", true, false):
		found.append(child)
	return found


func test_context_has_real_geometry_of_godot_nodes() -> void:
	clear_pipeline()
	var root: Node = scene("basic")
	mark_props(root)
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/basic.context.glb")
	check(context != null, "context.glb jde načíst")
	if context == null:
		done()
		return
	for name: String in ["Player", "Building", "Sphere"]:
		var unit: Node = context.find_child(name, true, false)
		check(unit != null and not _meshes(unit).is_empty(), "%s má mesh" % name)
	check(context.find_child("Helmet", true, false) == null, "výstroj modelu je v Blenderu jako model, ne kontext")
	for name: String in ["Spawn", "Sun", "Socket"]:
		check(context.find_child(name, true, false) != null, "%s je v kontextu jako prázdný node" % name)
	done()


func test_context_has_unit_world_transform() -> void:
	clear_pipeline()
	var root: Node = scene("basic")
	mark_props(root)
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/basic.context.glb")
	var building: Node3D = context.find_child("Building", true, false)
	near(building.global_position, Vector3(-10, 0, -10), "pozice Building")
	done()


func test_context_excludes_blender_owned_geometry() -> void:
	clear_pipeline()
	var root: Node = scene("basic")
	mark_props(root)
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/basic.context.glb")
	var crates: int = 0
	for mesh: MeshInstance3D in _meshes(context):
		if mesh.mesh != null and mesh.mesh.get_aabb().size.is_equal_approx(Vector3.ONE):
			crates += 1
	# Crate, InRotated a Detached jsou v Blenderu jako modely; v kontextu je jen
	# neoznačená Decoration na střeše Building.
	eq(crates, 1, "počet krychlí v kontextu")
	done()


func test_terrain_is_baked_in_world_space() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D není nainstalovaný")
		return
	clear_pipeline()
	var root: Node = scene("terrain")
	await tree.process_frame
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	near(origin_of(entry(manifest, "Terrain3D")), Vector3.ZERO, "Terrain3D je top_level, posun Nav se nepočítá")
	near(origin_of(entry(manifest, "CrateOnHill")), Vector3(128, 20, 128), "krabice na kopci")

	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	var meshes: Array[MeshInstance3D] = _meshes(context.find_child("Terrain3D", true, false))
	check(meshes.size() == 1, "terén je jeden mesh")
	eq(_meshes(context).size(), 1, "žádné interní meshe Terrain3D (MouseQuad) ani duplikáty pod Nav")
	if meshes.size() == 1:
		var aabb: AABB = meshes[0].global_transform * meshes[0].mesh.get_aabb()
		near(aabb.position.x, 0.0, "terén začíná na x=0", 0.5)
		near(aabb.end.x, 256.0, "terén končí na x=256", 16.5)
		near(aabb.end.y, 20.0, "vrchol kopce", 1.0)
	done()
