extends "res://tests/bb_test.gd"

## Writing changes from Blender back to the scene.


func _setup() -> Array:
	var root: Node = scene("basic")
	mark_props(root)
	var baseline: Dictionary = BBManifest.export_scene(root)
	return [root, baseline, baseline.duplicate(true)]


func _set_origin(manifest: Dictionary, name: String, origin: Vector3) -> void:
	var item: Dictionary = entry(manifest, name)
	item["xform"][9] = origin.x
	item["xform"][10] = origin.y
	item["xform"][11] = origin.z


func _set_basis(manifest: Dictionary, name: String, basis: Basis) -> void:
	var item: Dictionary = entry(manifest, name)
	var values: Array = [basis.x.x, basis.x.y, basis.x.z, basis.y.x, basis.y.y, basis.y.z, basis.z.x, basis.z.y, basis.z.z]
	for index: int in values.size():
		item["xform"][index] = values[index]


func _apply(root: Node, manifest: Dictionary, baseline: Dictionary) -> BBApply.Plan:
	var plan: BBApply.Plan = BBApply.plan(root, manifest, baseline)
	BBApply.new().execute(BBApply.operations(root, plan))
	return plan


func _world(root: Node, path: String) -> Transform3D:
	return BBManifest.global_xform(root.get_node(path) as Node3D, root)


func test_unchanged_manifest_is_noop() -> void:
	var setup: Array = _setup()
	check(BBApply.plan(setup[0], setup[2], setup[1]).is_empty(), "no changes")
	done()


func test_move_under_rotated_scaled_parent() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	_set_origin(setup[2], "InRotated", Vector3(10, 2, -5))
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	eq(plan.moved.size(), 1, "moved")
	near(_world(root, "Rotated/InRotated").origin, Vector3(10, 2, -5), "world position after import")
	# Locally: the parent is 2× bigger and rotated, so −3 m in the world is 1.5 m locally.
	near((root.get_node("Rotated/InRotated") as Node3D).position, Vector3(2.5, 0, 0), "local position")
	done()


func test_rotation_and_scale_survive() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var target: Basis = Basis(Vector3.RIGHT, deg_to_rad(20)).scaled(Vector3(1, 3, 1))
	_set_basis(setup[2], "Crate", target)
	_apply(root, setup[2], setup[1])
	near(_world(root, "Props/Crate").basis, target, "rotation and scale")
	done()


func test_move_top_level_node() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	_set_origin(setup[2], "Detached", Vector3(25, 0, 20))
	_apply(root, setup[2], setup[1])
	near((root.get_node("Rotated/Detached") as Node3D).transform.origin, Vector3(25, 0, 20),
		"top_level holds the global transform directly")
	done()


func test_duplicate_from_blender_is_added_under_parent() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var copy: Dictionary = entry(setup[2], "Tower").duplicate(true)
	copy["bb_id"] = "id_tower_copy"
	copy["name"] = "TowerCopy"
	copy["xform"][9] = 7.0
	setup[2]["nodes"].append(copy)
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	eq(plan.added.size(), 1, "added")
	var added: Node3D = root.get_node_or_null("Props/TowerCopy")
	check(added != null, "new node under Props")
	if added != null:
		eq(BBOwnership.get_id(added), "id_tower_copy", "id")
		eq(added.scene_file_path, "res://fixtures/assets/tower.glb", "instance of the same asset")
		eq(added.owner, root, "owner, so the scene saves it")
		near(_world(root, "Props/TowerCopy").origin, Vector3(7, 0, 1), "pozice")
	done()


func test_add_with_unknown_parent_goes_to_root() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var copy: Dictionary = entry(setup[2], "Crate").duplicate(true)
	copy["bb_id"] = "id_orphan"
	copy["name"] = "Orphan"
	copy["parent"] = "Neexistuje"
	setup[2]["nodes"].append(copy)
	_apply(root, setup[2], setup[1])
	check(root.get_node_or_null("Orphan") != null, "node under the root")
	done()


func test_add_with_missing_asset_is_reported() -> void:
	var setup: Array = _setup()
	var copy: Dictionary = entry(setup[2], "Crate").duplicate(true)
	copy["bb_id"] = "id_broken"
	copy["src"] = "res://neexistuje.glb"
	setup[2]["nodes"].append(copy)
	var plan: BBApply.Plan = BBApply.plan(setup[0], setup[2], setup[1])
	var ops: Array[Dictionary] = BBApply.operations(setup[0], plan)
	eq(ops.size(), 0, "no operation")
	eq(plan.unresolved.size(), 1, "problem reported")
	done()


func test_delete_in_blender_removes_node() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var kept: Array = []
	for item: Dictionary in setup[2]["nodes"]:
		if item.get("name") != "Barrel":
			kept.append(item)
	setup[2]["nodes"] = kept
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	eq(plan.removed.size(), 1, "removed")
	check(root.get_node_or_null("Props/Barrel") == null, "Barrel is gone")
	done()


func test_parent_and_child_moved_together() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	# In Blender the parent moved and the child (its descendant) moved with it.
	_set_origin(setup[2], "Character", Vector3(7, 0, -2))
	_set_origin(setup[2], "Helmet", Vector3(7, 1.8, -2))
	_apply(root, setup[2], setup[1])
	near(_world(root, "Character").origin, Vector3(7, 0, -2), "parent")
	near(_world(root, "Character/Helmet").origin, Vector3(7, 1.8, -2), "the child doesn't move twice")
	near((root.get_node("Character/Helmet") as Node3D).position, Vector3(0, 1.8, 0), "the child's local position is unchanged")
	done()


func test_child_survives_deleted_parent() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var kept: Array = []
	for item: Dictionary in setup[2]["nodes"]:
		if item.get("name") != "Character":
			kept.append(item)
	setup[2]["nodes"] = kept
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	check(root.get_node_or_null("Character") == null, "parent deleted")
	var helmet: Node3D = root.get_node_or_null("Helmet")
	check(helmet != null, "a child that stayed in Blender is under the nearest ancestor")
	if helmet != null:
		eq(BBOwnership.get_id(helmet), "id_helmet", "same id")
		near(_world(root, "Helmet").origin, Vector3(5, 1.8, -2), "in the same place")
	eq(plan.added.size(), 1, "the child is added again")
	done()


func test_node_marked_after_export_is_not_deleted() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	# Marked in Godot only after the export: it's in neither the manifest nor the snapshot.
	root.get_node("Building/Decoration").set_meta(BBOwnership.META_ID, "id_late")
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	check(plan.removed.is_empty(), "nothing is removed")
	check(root.get_node_or_null("Building/Decoration") != null, "Decoration stayed")
	done()


func test_pinned_node_is_not_moved() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	root.get_node("Props/Crate").set_meta(BBOwnership.META_PINNED, true)
	_set_origin(setup[2], "Crate", Vector3(50, 0, 50))
	var plan: BBApply.Plan = _apply(root, setup[2], setup[1])
	eq(plan.pinned.size(), 1, "reported as pinned")
	near(_world(root, "Props/Crate").origin, Vector3(2, 0, 3), "position unchanged")
	done()


func test_gameplay_nodes_stay_untouched() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var before: Transform3D = _world(root, "Player")
	var children: int = root.get_node("Building").get_child_count()
	_set_origin(setup[2], "Player", Vector3(99, 99, 99))
	_set_origin(setup[2], "Crate", Vector3(3, 0, 3))
	_apply(root, setup[2], setup[1])
	near(_world(root, "Player"), before, "Player isn't overwritten from the manifest")
	eq(root.get_node("Building").get_child_count(), children, "Building unchanged")
	done()


func test_revert_restores_everything() -> void:
	var setup: Array = _setup()
	var root: Node = setup[0]
	var crate_before: Transform3D = _world(root, "Props/Crate")
	_set_origin(setup[2], "Crate", Vector3(9, 9, 9))
	var copy: Dictionary = entry(setup[2], "Tower").duplicate(true)
	copy["bb_id"] = "id_tmp"
	copy["name"] = "Tmp"
	setup[2]["nodes"].append(copy)
	var kept: Array = []
	for item: Dictionary in setup[2]["nodes"]:
		if item.get("name") != "Barrel":
			kept.append(item)
	setup[2]["nodes"] = kept
	var plan: BBApply.Plan = BBApply.plan(root, setup[2], setup[1])
	var ops: Array[Dictionary] = BBApply.operations(root, plan)
	var runner: BBApply = BBApply.new()
	runner.execute(ops)
	runner.revert(ops)
	near(_world(root, "Props/Crate"), crate_before, "move undone")
	check(root.get_node_or_null("Props/Tmp") == null, "add undone")
	check(root.get_node_or_null("Props/Barrel") != null, "remove undone")
	done()
