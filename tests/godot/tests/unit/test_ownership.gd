extends "res://tests/bb_test.gd"

## Which nodes Blender may move.


## The exact list also proves what is left out: Player (.tscn instance, gameplay),
## Building/Decoration (under a physics body) and the insides of crate.glb.
func test_auto_mark_picks_art_instances() -> void:
	var root: Node = scene("basic")
	var names: PackedStringArray = []
	for node: Node in mark_props(root):
		names.append(str(node.name))
	names.sort()
	eq(names, PackedStringArray(["Barrel", "Character", "Crate", "Detached", "Helmet", "InRotated", "Tower"]),
		"marked art instances")
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
