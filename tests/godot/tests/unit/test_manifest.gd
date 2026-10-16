extends "res://tests/bb_test.gd"

## Co a v jakých souřadnicích jde z Godotu do manifestu.


func test_owned_entry_has_world_transform() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Dictionary = entry(BBManifest.export_scene(root), "Crate")
	eq(crate.get("owner"), "blender", "vlastník")
	near(origin_of(crate), Vector3(2, 0, 3), "pozice Crate")
	var x: Array = crate["xform"]
	var expected: Basis = Basis(Vector3.UP, deg_to_rad(30))
	near(Basis(Vector3(x[0], x[1], x[2]), Vector3(x[3], x[4], x[5]), Vector3(x[6], x[7], x[8])),
		expected, "rotace Crate")
	done()


func test_transform_composes_rotated_and_scaled_parent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	# Rodič (10,2,0), otočený o 90° kolem Y, měřítko 2; dítě lokálně (1,0,0).
	near(origin_of(entry(BBManifest.export_scene(root), "InRotated")), Vector3(10, 2, -2), "pozice InRotated")
	done()


func test_top_level_ignores_parent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	near(origin_of(entry(BBManifest.export_scene(root), "Detached")), Vector3(20, 0, 20),
		"top_level node nesmí dostat transformaci rodiče")
	done()


func test_plain_containers_are_transparent() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	for name: String in ["Props", "Rotated", "Logic"]:
		check(entry(manifest, name).is_empty(), "%s je jen organizační kontejner" % name)
	done()


func test_gameplay_nodes_become_locked_context() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var manifest: Dictionary = BBManifest.export_scene(root)
	for name: String in ["Player", "Building", "Spawn", "Sun", "Sphere"]:
		eq(entry(manifest, name).get("owner"), "godot", "%s jako kontext" % name)
	check(entry(manifest, "Floating").is_empty(), "Floating je obyčejný Node3D, tedy kontejner")
	check(entry(manifest, "Decoration").is_empty(), "neoznačená Decoration je součástí Building")
	done()


func test_owned_node_inside_context_is_found() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	root.get_node("Building/Decoration").set_meta(BBOwnership.META_ID, "id_decoration")
	var decoration: Dictionary = entry(BBManifest.export_scene(root), "Decoration")
	eq(decoration.get("owner"), "blender", "ručně označená Decoration")
	eq(decoration.get("parent"), "Building", "rodič")
	near(origin_of(decoration), Vector3(-10, 3, -10), "pozice")
	done()


func test_bounds_cover_whole_subtree() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var building: Dictionary = entry(BBManifest.export_scene(root), "Building")
	# Box 4×3×4 od y=0 a na něm krychle 1 m (y 3–4).
	near(Vector3(building["bounds"]["size"][0], building["bounds"]["size"][1], building["bounds"]["size"][2]),
		Vector3(4, 4, 4), "velikost obálky")
	near(Vector3(building["bounds"]["position"][0], building["bounds"]["position"][1], building["bounds"]["position"][2]),
		Vector3(-2, 0, -2), "počátek obálky")
	done()


func test_missing_source_reports_expected_path() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Dictionary = entry(BBManifest.export_scene(root), "Crate")
	eq(crate.get("tier"), "none", "tier")
	eq(crate.get("src_blend_missing"), "fixtures/assets/crate.blend", "očekávaný zdroj vedle assetu")
	done()


func test_write_creates_manifest_baseline_and_context() -> void:
	clear_pipeline()
	var root: Node = scene("basic")
	mark_props(root)
	var path: String = BBManifest.write(root)
	eq(path, "res://.pipeline/basic.json", "cesta manifestu")
	check(FileAccess.file_exists("res://.pipeline/basic.last.json"), "snímek pro diff")
	check(FileAccess.file_exists("res://.pipeline/basic.context.glb"), "geometrie kontextu")
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	eq(manifest.get("context_glb"), ".pipeline/basic.context.glb", "odkaz na kontext v manifestu")
	check(FileAccess.file_exists("res://.pipeline/.gdignore"), ".gdignore v .pipeline")
	done()
