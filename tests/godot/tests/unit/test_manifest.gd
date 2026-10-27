extends "res://tests/bb_test.gd"

## What goes from Godot into the manifest, and in which coordinates.


func test_owned_entry_has_world_transform() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Dictionary = entry(BBManifest.export_scene(root), "Crate")
	eq(crate.get("owner"), "blender", "owner")
	near(origin_of(crate), Vector3(2, 0, 3), "pozice Crate")
	var x: Array = crate["xform"]
	var expected: Basis = Basis(Vector3.UP, deg_to_rad(30))
	near(Basis(Vector3(x[0], x[1], x[2]), Vector3(x[3], x[4], x[5]), Vector3(x[6], x[7], x[8])),
		expected, "rotace Crate")
	done()


func test_transform_composes_rotated_and_scaled_parent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	# Parent (10,2,0), rotated 90° around Y, scale 2; child locally (1,0,0).
	near(origin_of(entry(BBManifest.export_scene(root), "InRotated")), Vector3(10, 2, -2), "pozice InRotated")
	done()


func test_top_level_ignores_parent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	near(origin_of(entry(BBManifest.export_scene(root), "Detached")), Vector3(20, 0, 20),
		"a top_level node must not get the parent's transform")
	done()


func test_plain_containers_are_transparent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	for name: String in ["Props", "Rotated", "Logic"]:
		check(entry(manifest, name).is_empty(), "%s is just an organisational container" % name)
	done()


func test_gameplay_nodes_become_locked_context() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	for name: String in ["Player", "Building", "Spawn", "Sun", "Sphere"]:
		eq(entry(manifest, name).get("owner"), "godot", "%s as context" % name)
	check(entry(manifest, "Floating").is_empty(), "Floating is a plain Node3D, so a container")
	check(entry(manifest, "Decoration").is_empty(), "unmarked Decoration is part of Building")
	done()


func test_owned_node_inside_context_is_found() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	root.get_node("Building/Decoration").set_meta(BBOwnership.META_ID, "id_decoration")
	var decoration: Dictionary = entry(BBManifest.export_scene(root), "Decoration")
	eq(decoration.get("owner"), "blender", "manually marked Decoration")
	eq(decoration.get("parent"), "Building", "parent")
	near(origin_of(decoration), Vector3(-10, 3, -10), "pozice")
	done()


func test_children_of_model_are_exported() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	var helmet: Dictionary = entry(manifest, "Helmet")
	eq(helmet.get("owner"), "blender", "gear on a model goes to Blender")
	eq(helmet.get("parent"), "Character", "the parent is the model")
	near(origin_of(helmet), Vector3(5, 1.8, -2), "the child's world position")
	var socket: Dictionary = entry(manifest, "Socket")
	eq(socket.get("owner"), "godot", "a marker on a model is context")
	near(origin_of(socket), Vector3(5, 1, -2), "pozice markeru")
	done()


func test_inside_of_model_asset_is_not_exported() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	for item: Dictionary in manifest["nodes"]:
		check(not str(item["path"]).begins_with("Props/Crate/"), "inside of crate.glb: %s" % item["path"])
	done()


func test_bounds_cover_whole_subtree() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var building: Dictionary = entry(BBManifest.export_scene(root), "Building")
	# A 4×3×4 box from y=0 with a 1 m cube on top (y 3–4).
	near(Vector3(building["bounds"]["size"][0], building["bounds"]["size"][1], building["bounds"]["size"][2]),
		Vector3(4, 4, 4), "bounding box size")
	near(Vector3(building["bounds"]["position"][0], building["bounds"]["position"][1], building["bounds"]["position"][2]),
		Vector3(-2, 0, -2), "bounding box origin")
	done()


func test_missing_source_reports_expected_path() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Dictionary = entry(BBManifest.export_scene(root), "Crate")
	eq(crate.get("tier"), "none", "tier")
	eq(crate.get("src_blend_missing"), "fixtures/assets/crate.blend", "expected source next to the asset")
	done()


func test_write_creates_manifest_baseline_and_context() -> void:
	clear_pipeline()
	var root: Node = scene("basic")
	mark_props(root)
	var path: String = BBManifest.write(root)
	eq(path, "res://.pipeline/basic.json", "cesta manifestu")
	check(FileAccess.file_exists("res://.pipeline/basic.last.json"), "snapshot for the diff")
	check(FileAccess.file_exists("res://.pipeline/basic.context.glb"), "geometrie kontextu")
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	eq(manifest.get("context_glb"), ".pipeline/basic.context.glb", "context link in the manifest")
	check(FileAccess.file_exists("res://.pipeline/.gdignore"), ".gdignore v .pipeline")
	done()
