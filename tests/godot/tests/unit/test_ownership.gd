extends "res://tests/bb_test.gd"

## Which nodes Blender may move.


func test_auto_mark_picks_art_instances() -> void:
	var root: Node = scene("basic")
	var names: PackedStringArray = []
	for node: Node in mark_props(root):
		names.append(str(node.name))
	names.sort()
	eq(names, PackedStringArray(["Barrel", "Character", "Crate", "Detached", "Helmet", "InRotated", "Tower"]),
		"marked art instances")
	done()


func test_gameplay_instance_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	check(not BBOwnership.is_blender_owned(root.get_node("Player")),
		"Player is a .tscn instance, not an art asset")
	done()


func test_instance_under_physics_body_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	check(not BBOwnership.is_blender_owned(root.get_node("Building/Decoration")),
		"Decoration is part of the Building gameplay unit")
	done()


func test_inside_of_foreign_instance_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Node = root.get_node("Props/Crate")
	for child: Node in crate.get_children():
		check(not BBOwnership.is_blender_owned(child), "%s inside the crate.glb instance" % child.name)
	done()


func test_duplicate_ids_are_reported() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	# Ctrl+D in the editor copies metadata too.
	root.get_node("Props/Tower").set_meta(BBOwnership.META_ID, "id_crate")
	var duplicates: Array[Node] = []
	var taken: Dictionary = BBOwnership.collect_ids(root, duplicates)
	eq(duplicates.size(), 1, "number of duplicates")
	check(taken.has("id_crate"), "the first occurrence stays valid")
	done()


func test_assign_id_replaces_taken_id() -> void:
	var root: Node = scene("basic")
	var crate: Node = root.get_node("Props/Crate")
	crate.set_meta(BBOwnership.META_ID, "taken")
	check(BBOwnership.assign_id(crate, {"taken": root}), "a taken id is reassigned")
	check(BBOwnership.get_id(crate) != "taken", "the new id is different")
	done()
