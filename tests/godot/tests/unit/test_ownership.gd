extends "res://tests/bb_test.gd"

## Které nody smí Blender posouvat.


func test_auto_mark_picks_art_instances() -> void:
	var root: Node = scene("basic")
	var names: PackedStringArray = []
	for node: Node in mark_props(root):
		names.append(str(node.name))
	names.sort()
	eq(names, PackedStringArray(["Barrel", "Character", "Crate", "Detached", "InRotated", "Tower"]),
		"označené art instance")
	done()


func test_gameplay_instance_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	check(not BBOwnership.is_blender_owned(root.get_node("Player")),
		"Player je instance .tscn, ne art asset")
	done()


func test_instance_under_physics_body_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	check(not BBOwnership.is_blender_owned(root.get_node("Building/Decoration")),
		"Decoration je součást gameplay celku Building")
	done()


func test_inside_of_foreign_instance_is_not_marked() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	var crate: Node = root.get_node("Props/Crate")
	for child: Node in crate.get_children():
		check(not BBOwnership.is_blender_owned(child), "%s uvnitř instance crate.glb" % child.name)
	done()


func test_duplicate_ids_are_reported() -> void:
	var root: Node = scene("basic")
	mark_props(root)
	# Ctrl+D v editoru zkopíruje i metadata.
	root.get_node("Props/Tower").set_meta(BBOwnership.META_ID, "id_crate")
	var duplicates: Array[Node] = []
	var taken: Dictionary = BBOwnership.collect_ids(root, duplicates)
	eq(duplicates.size(), 1, "počet duplicit")
	check(taken.has("id_crate"), "první výskyt zůstává platný")
	done()


func test_assign_id_replaces_taken_id() -> void:
	var root: Node = scene("basic")
	var crate: Node = root.get_node("Props/Crate")
	crate.set_meta(BBOwnership.META_ID, "taken")
	check(BBOwnership.assign_id(crate, {"taken": root}), "obsazené id se přidělí znovu")
	check(BBOwnership.get_id(crate) != "taken", "nové id je jiné")
	done()
