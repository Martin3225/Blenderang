extends SceneTree

## Vygeneruje testovací scény. Spouští runner přes --regen-fixtures; výsledek
## se commituje, aby testy běžely nad stabilním vstupem.
##
## basic.tscn — všechny případy rozmístění:
##   Props/Crate, Props/Tower, Props/Barrel  art instance v kontejneru (označí se)
##   Rotated (otočený a zvětšený rodič)
##     InRotated   instance pod transformovaným rodičem (označí se)
##     Detached    instance s top_level (označí se, transformace je globální)
##   Player        instance .tscn — gameplay, NEoznačí se
##   Building      StaticBody3D s meshem, kolizí a vnořenou Decoration
##                 (vnořená instance pod tělesem se NEoznačí)
##   Character     riggovaný .glb (označí se)
##   Spawn, Sun    Marker3D a světlo — jen kontext
##   Logic/Floating  Node3D pod obyčejným Node — kontext s meshem
## second.tscn — malá druhá scéna pro otevírání z kontextového menu
## terrain.tscn — Terrain3D pod posunutým NavigationRegion3D (top_level)

const ASSETS: String = "res://fixtures/assets/"
const SCENES: String = "res://fixtures/scenes/"


func _initialize() -> void:
	_generate.call_deferred()


func _generate() -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(SCENES))
	_save(_player(), SCENES + "player.tscn")
	_save(_basic(), SCENES + "basic.tscn")
	_save(_second(), SCENES + "second.tscn")
	if ClassDB.class_exists("Terrain3D"):
		var terrain: Node3D = await _terrain()
		_save(terrain, SCENES + "terrain.tscn")
	print("FIXTURES_OK")
	quit(0)


func _save(root: Node, path: String) -> void:
	var packed: PackedScene = PackedScene.new()
	var err: Error = packed.pack(root)
	if err == OK:
		err = ResourceSaver.save(packed, path)
	if err != OK:
		push_error("nelze uložit %s (%d)" % [path, err])
	if root.is_inside_tree():
		root.get_parent().remove_child(root)
	root.free()


func _add(parent: Node, child: Node, owner: Node, name: String) -> Node:
	child.name = name
	parent.add_child(child)
	child.owner = owner
	return child


func _instance(parent: Node, owner: Node, asset: String, name: String, position: Vector3) -> Node3D:
	var node: Node3D = (load(ASSETS + asset) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	node.position = position
	return _add(parent, node, owner, name)


func _player() -> Node:
	var root: CharacterBody3D = CharacterBody3D.new()
	root.name = "Player"
	var shape: CollisionShape3D = _add(root, CollisionShape3D.new(), root, "Shape")
	shape.shape = CapsuleShape3D.new()
	shape.position = Vector3(0, 1, 0)
	var mesh: MeshInstance3D = _add(root, MeshInstance3D.new(), root, "Body")
	mesh.mesh = CapsuleMesh.new()
	mesh.position = Vector3(0, 1, 0)
	return root


func _basic() -> Node:
	var root: Node3D = Node3D.new()
	root.name = "Basic"

	var props: Node3D = _add(root, Node3D.new(), root, "Props")
	var crate: Node3D = _instance(props, root, "crate.glb", "Crate", Vector3(2, 0, 3))
	crate.rotation_degrees = Vector3(0, 30, 0)
	_instance(props, root, "tower.glb", "Tower", Vector3(-4, 0, 1))
	_instance(props, root, "barrel.fbx", "Barrel", Vector3(0, 0, -5))

	var rotated: Node3D = _add(root, Node3D.new(), root, "Rotated")
	rotated.position = Vector3(10, 2, 0)
	rotated.rotation_degrees = Vector3(0, 90, 0)
	rotated.scale = Vector3(2, 2, 2)
	_instance(rotated, root, "crate.glb", "InRotated", Vector3(1, 0, 0))
	var detached: Node3D = _instance(rotated, root, "crate.glb", "Detached", Vector3(20, 0, 20))
	detached.top_level = true

	var player: Node3D = (load(SCENES + "player.tscn") as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	_add(root, player, root, "Player")

	var building: StaticBody3D = _add(root, StaticBody3D.new(), root, "Building")
	building.position = Vector3(-10, 0, -10)
	var body: MeshInstance3D = _add(building, MeshInstance3D.new(), root, "Mesh")
	var box: BoxMesh = BoxMesh.new()
	box.size = Vector3(4, 3, 4)
	body.mesh = box
	body.position = Vector3(0, 1.5, 0)
	var shape: CollisionShape3D = _add(building, CollisionShape3D.new(), root, "Shape")
	var box_shape: BoxShape3D = BoxShape3D.new()
	box_shape.size = Vector3(4, 3, 4)
	shape.shape = box_shape
	shape.position = Vector3(0, 1.5, 0)
	_instance(building, root, "crate.glb", "Decoration", Vector3(0, 3, 0))

	_instance(root, root, "rig.glb", "Character", Vector3(5, 0, -2))

	var spawn: Marker3D = _add(root, Marker3D.new(), root, "Spawn")
	spawn.position = Vector3(1, 0, 1)
	var sun: DirectionalLight3D = _add(root, DirectionalLight3D.new(), root, "Sun")
	sun.rotation_degrees = Vector3(-45, 30, 0)

	var logic: Node = _add(root, Node.new(), root, "Logic")
	var floating: Node3D = _add(logic, Node3D.new(), root, "Floating")
	floating.position = Vector3(0, 5, 0)
	var sphere: MeshInstance3D = _add(floating, MeshInstance3D.new(), root, "Sphere")
	sphere.mesh = SphereMesh.new()
	return root


func _second() -> Node:
	var root: Node3D = Node3D.new()
	root.name = "Second"
	_instance(root, root, "crate.glb", "Crate", Vector3(1, 0, 1))
	return root


## Jeden region 256 m s kopcem uprostřed, pod NavigationRegion3D posunutým
## o (100, 5, 100). Terrain3D je top_level, takže posun rodiče ho nesmí ovlivnit.
func _terrain() -> Node3D:
	var root: Node3D = Node3D.new()
	root.name = "TerrainScene"
	var nav: NavigationRegion3D = _add(root, NavigationRegion3D.new(), root, "Nav")
	nav.position = Vector3(100, 5, 100)
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://fixtures/terrain_data"))
	var terrain: Node3D = ClassDB.instantiate("Terrain3D")
	terrain.set("data_directory", "res://fixtures/terrain_data")
	_add(nav, terrain, root, "Terrain3D")
	get_root().add_child(root)
	await process_frame
	await process_frame
	# Jako v reálném projektu: terén v počátku, i když rodič je posunutý.
	terrain.global_transform = Transform3D.IDENTITY

	var data: Object = terrain.call("get_data")
	data.call("add_region_blankp", Vector3(1, 0, 1), true)
	for x: int in range(0, 256, 4):
		for z: int in range(0, 256, 4):
			var distance: float = Vector2(x - 128, z - 128).length()
			var height: float = maxf(0.0, 20.0 - distance * 0.25)
			data.call("set_height", Vector3(x, 0, z), height)
	data.call("update_maps", 3, true, false)
	data.call("save_directory", "res://fixtures/terrain_data")

	_instance(nav, root, "crate.glb", "CrateOnHill", Vector3(28, 15, 28))
	return root
