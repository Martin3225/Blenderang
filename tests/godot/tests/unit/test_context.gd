extends "res://tests/bb_test.gd"

## Context geometry (.context.glb): what Blender sees from Godot as locked surroundings.


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
	check(context != null, "context.glb loads")
	if context == null:
		done()
		return
	for name: String in ["Player", "Building", "Sphere"]:
		var unit: Node = context.find_child(name, true, false)
		check(unit != null and not _meshes(unit).is_empty(), "%s has a mesh" % name)
	check(context.find_child("Helmet", true, false) == null, "a model's gear is a model in Blender, not context")
	for name: String in ["Spawn", "Sun", "Socket"]:
		check(context.find_child(name, true, false) != null, "%s is in the context as an empty node" % name)
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
	# Crate, InRotated and Detached are models in Blender; the context only has
	# the unmarked Decoration on the Building's roof.
	eq(crates, 1, "number of cubes in the context")
	done()


func test_terrain_is_baked_in_world_space() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
		return
	clear_pipeline()
	var root: Node = scene("terrain")
	await tree.process_frame
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	near(origin_of(entry(manifest, "Terrain3D")), Vector3.ZERO, "Terrain3D is top_level, the Nav offset doesn't count")
	near(origin_of(entry(manifest, "CrateOnHill")), Vector3(128, 20, 128), "box on the hill")

	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	var meshes: Array[MeshInstance3D] = _meshes(context.find_child("Terrain3D", true, false))
	check(meshes.size() == 1, "terrain is one mesh")
	eq(_meshes(context).size(), 1, "no internal Terrain3D meshes (MouseQuad) or duplicates under Nav")
	if meshes.size() == 1:
		var aabb: AABB = meshes[0].global_transform * meshes[0].mesh.get_aabb()
		near(aabb.position.x, 0.0, "terrain starts at x=0", 0.5)
		near(aabb.end.x, 256.0, "terrain ends at x=256", 16.5)
		near(aabb.end.y, 20.0, "vrchol kopce", 1.0)
	done()


## Terrain under a NavigationRegion3D with no model in it (everything
## unmarked). Nav is a single proxy unit, but the terrain must get its own
## entry: Terrain3D's internal meshes have no owner and don't get into the Nav unit.
func test_terrain_under_unmarked_parent_is_kept() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
		return
	clear_pipeline()
	var root: Node = scene("terrain")
	await tree.process_frame
	var manifest: Dictionary = BBManifest.export_scene(root)
	eq(entry(manifest, "Terrain3D").get("kind"), "terrain", "terrain has an entry")
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	eq(_meshes(context.find_child("Terrain3D", true, false)).size(), 1, "terrain in the context")
	eq(_meshes(context).size(), 2, "terrain and box, nothing twice")
	done()


func _terrain_root() -> Node:
	var root: Node = scene("terrain")
	await tree.process_frame
	mark_props(root)
	return root


func _pixel(image: Image, world_x: int, world_z: int) -> Color:
	# The region is 0–256 m and the texture has 1 px per metre.
	return image.get_pixel(world_x, world_z)


func test_terrain_has_baked_material() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	BBManifest.write(root)
	var context: Node = _load_context("res://.pipeline/terrain.context.glb")
	var meshes: Array[MeshInstance3D] = _meshes(context.find_child("Terrain3D", true, false))
	check(meshes.size() == 1, "terrain in the context")
	if meshes.size() == 1:
		var material: StandardMaterial3D = meshes[0].get_active_material(0) as StandardMaterial3D
		check(material != null and material.albedo_texture != null, "terrain has a material with a texture")
		var arrays: Array = meshes[0].mesh.surface_get_arrays(0)
		check(arrays[Mesh.ARRAY_TEX_UV] != null, "terrain has UVs")
	done()


func test_terrain_colors_follow_painting() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	BBManifest.write(root)
	var image: Image = Image.load_from_file(ProjectSettings.globalize_path("res://.pipeline/terrain.terrain.png"))
	check(image != null, "the baked texture is in the cache")
	if image == null:
		done()
		return
	eq(image.get_size(), Vector2i(256, 256), "1 px per metre for a small terrain")
	var sand: Color = Color(0.8, 0.7, 0.4)
	near(_vec(_pixel(image, 64, 200)), _vec(sand), "hand-painted sand", 0.03)
	near(_vec(_pixel(image, 10, 10)), _vec(sand * Color(1, 0.5, 0.5)), "colour map tints the sand", 0.03)
	var flat: Color = _pixel(image, 240, 10)
	near(_vec(flat), Vector3(0.2, 0.6, 0.2), "auto shader: flat ground is grass", 0.03)
	var slope: Color = _pixel(image, 150, 110)
	var rock: Vector3 = Vector3(0.5, 0.5, 0.5)
	check(_vec(slope).distance_to(rock) < _vec(flat).distance_to(rock) - 0.05,
		"auto shader: a slope is more rock than flat ground (%s vs %s)" % [slope, flat])
	done()


func test_terrain_bake_is_cached() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
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
	# Cache: a second call with the same terrain doesn't bake again.
	var image: Image = Image.create_empty(1, 1, false, Image.FORMAT_RGB8)
	image.save_png(ProjectSettings.globalize_path(base + ".terrain.png"))
	eq(BBTerrain.albedo(terrain, aabb, base).get_size(), Vector2i(1, 1), "without a terrain change the cache is used")
	# A material change (auto shader) invalidates the cache.
	terrain.get("material").call("set_shader_param", "auto_slope", 3.0)
	eq(BBTerrain.albedo(terrain, aabb, base).get_size(), Vector2i(256, 256), "after a material change it bakes again")
	check(FileAccess.get_file_as_string(base + ".terrain.sig") != signature, "new signature")
	done()


## Vertex spacing from Project Settings; the mesh comes from the cache until
## the setting changes.
func test_terrain_resolution_follows_setting() -> void:
	if not ClassDB.class_exists("Terrain3D"):
		skip("Terrain3D is not installed")
		return
	clear_pipeline()
	var root: Node = await _terrain_root()
	var terrain: Node3D = root.get_node("Nav/Terrain3D")
	var base: String = "res://.pipeline/resolution_test"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://.pipeline"))
	ProjectSettings.set_setting(BBTerrain.SETTING_SPACING, 4)
	# 256 m terrain: every 4 m gives 65 × 65 vertices.
	eq(_vertex_count(BBTerrain.terrain_mesh(terrain, base)), 65 * 65, "a vertex every 4 m")

	var fake: ArrayMesh = ArrayMesh.new()
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3.ZERO, Vector3.RIGHT, Vector3.FORWARD])
	fake.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	ResourceSaver.save(fake, base + ".terrain.res")
	eq(_vertex_count(BBTerrain.terrain_mesh(terrain, base)), 3, "without a change the mesh comes from the cache")

	ProjectSettings.set_setting(BBTerrain.SETTING_SPACING, 16)
	eq(_vertex_count(BBTerrain.terrain_mesh(terrain, base)), 17 * 17, "after a settings change it bakes again, every 16 m")
	ProjectSettings.set_setting(BBTerrain.SETTING_SPACING, 1)
	eq(_vertex_count(BBTerrain.terrain_mesh(terrain, base)), 257 * 257, "full resolution every 1 m")
	ProjectSettings.set_setting(BBTerrain.SETTING_SPACING, BBTerrain.DEFAULT_SPACING)
	done()


func _vertex_count(mesh: Mesh) -> int:
	return (mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX] as PackedVector3Array).size() if mesh else -1



func _vec(color: Color) -> Vector3:
	return Vector3(color.r, color.g, color.b)
