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


## Terén pod NavigationRegion3D, ve kterém není žádný model (všechno
## neoznačené). Nav je jako proxy jeden celek, terén ale musí dostat vlastní
## záznam — vnitřní meshe Terrain3D nemají ownera a do celku Nav se nedostanou.
func test_terrain_under_unmarked_parent_is_kept() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D není nainstalovaný")
		return
	clear_pipeline()
	var root: Node = scene("terrain")
	await tree.process_frame
	var manifest: Dictionary = BBManifest.export_scene(root)
	eq(entry(manifest, "Terrain3D").get("kind"), "terrain", "terén má záznam")
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	eq(_meshes(context.find_child("Terrain3D", true, false)).size(), 1, "terén v kontextu")
	eq(_meshes(context).size(), 2, "terén a krabice, nic dvakrát")
	done()


func _terrain_root() -> Node:
	var root: Node = scene("terrain")
	await tree.process_frame
	mark_props(root)
	return root


func _pixel(image: Image, world_x: int, world_z: int) -> Color:
	# Region je 0–256 m a textura má 1 px na metr.
	return image.get_pixel(world_x, world_z)


func test_terrain_has_baked_material() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D není nainstalovaný")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	var meshes: Array[MeshInstance3D] = _meshes(context.find_child("Terrain3D", true, false))
	check(meshes.size() == 1, "terén v kontextu")
	if meshes.size() == 1:
		var material: StandardMaterial3D = meshes[0].get_active_material(0) as StandardMaterial3D
		check(material != null and material.albedo_texture != null, "terén má materiál s texturou")
		var arrays: Array = meshes[0].mesh.surface_get_arrays(0)
		check(arrays[Mesh.ARRAY_TEX_UV] != null, "terén má UV")
	done()


func test_terrain_colors_follow_painting() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D není nainstalovaný")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	BBManifest.write(root)
	var image: Image = Image.load_from_file(ProjectSettings.globalize_path("res://.pipeline/terrain.terrain.png"))
	check(image != null, "upečená textura je v cache")
	if image == null:
		done()
		return
	eq(image.get_size(), Vector2i(256, 256), "1 px na metr u malého terénu")
	var sand: Color = Color(0.8, 0.7, 0.4)
	near(_vec(_pixel(image, 64, 200)), _vec(sand), "ručně malovaný písek", 0.03)
	near(_vec(_pixel(image, 10, 10)), _vec(sand * Color(1, 0.5, 0.5)), "barevná mapa obarví písek", 0.03)
	var flat: Color = _pixel(image, 240, 10)
	near(_vec(flat), Vector3(0.2, 0.6, 0.2), "auto shader: rovina je tráva", 0.03)
	var slope: Color = _pixel(image, 150, 110)
	var rock: Vector3 = Vector3(0.5, 0.5, 0.5)
	check(_vec(slope).distance_to(rock) < _vec(flat).distance_to(rock) - 0.05,
		"auto shader: svah je víc skála než rovina (%s vs %s)" % [slope, flat])
	done()


func test_terrain_bake_is_cached() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D není nainstalovaný")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	var terrain: Node3D = root.get_node("Nav/Terrain3D")
	var aabb: AABB = (terrain.call("bake_mesh", 4, 0) as Mesh).get_aabb()
	var base: String = "res://.pipeline/cache_test"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://.pipeline"))
	BBTerrain.albedo(terrain, aabb, base)
	var signature: String = FileAccess.get_file_as_string(base + ".terrain.sig")
	write_file(base + ".terrain.png.marker", "")
	# Cache: druhé volání se stejným terénem nepeče znovu.
	var image: Image = Image.create_empty(1, 1, false, Image.FORMAT_RGB8)
	image.save_png(ProjectSettings.globalize_path(base + ".terrain.png"))
	eq(BBTerrain.albedo(terrain, aabb, base).get_size(), Vector2i(1, 1), "beze změny terénu se vezme cache")
	# Změna materiálu (auto shader) cache zneplatní.
	terrain.get("material").call("set_shader_param", "auto_slope", 3.0)
	eq(BBTerrain.albedo(terrain, aabb, base).get_size(), Vector2i(256, 256), "po změně materiálu se peče znovu")
	check(FileAccess.get_file_as_string(base + ".terrain.sig") != signature, "nový podpis")
	done()


func _vec(color: Color) -> Vector3:
	return Vector3(color.r, color.g, color.b)
