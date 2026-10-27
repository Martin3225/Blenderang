extends SceneTree

## Generates the test scenes. The runner runs it via --regen-fixtures; the result
## is committed so tests run on stable input.
##
## basic.tscn — all layout cases:
##   Props/Crate, Props/Tower, Props/Barrel  art instances in a container (marked)
##   Rotated (rotated and scaled parent)
##     InRotated   instance under a transformed parent (marked)
##     Detached    instance with top_level (marked, transform is global)
##   Player        .tscn instance — gameplay, NOT marked
##   Building      StaticBody3D with a mesh, collision and nested Decoration
##                 (a nested instance under a body is NOT marked)
##   Character     rigged .glb (marked)
##     Helmet      art instance as a child of the model (gear on an armature; marked)
##     Socket      Marker3D under the model — context
##   Spawn, Sun    Marker3D and a light — context only
##   Logic/Floating  Node3D under a plain Node — context with a mesh
## second.tscn — a small second scene for opening from the context menu
## terrain.tscn — Terrain3D under an offset NavigationRegion3D (top_level)

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
		push_error("cannot save %s (%d)" % [path, err])
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

	var character: Node3D = _instance(root, root, "rig.glb", "Character", Vector3(5, 0, -2))
	# Like gear on armature_f: art instances added in the scene as children of the model.
	_instance(character, root, "crate.glb", "Helmet", Vector3(0, 1.8, 0))
	var socket: Marker3D = _add(character, Marker3D.new(), root, "Socket")
	socket.position = Vector3(0, 1, 0)

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


## Three single-colour textures and an auto shader: grass (0) on flat ground, rock (1)
## on slopes. The colours are pure so they can be recognised in the baked map test.
func _terrain_look(terrain: Node3D) -> void:
	var assets: Object = ClassDB.instantiate("Terrain3DAssets")
	var colors: Array[Color] = [Color(0.2, 0.6, 0.2), Color(0.5, 0.5, 0.5), Color(0.8, 0.7, 0.4)]
	var names: PackedStringArray = ["grass", "rock", "sand"]
	for id: int in colors.size():
		var image: Image = Image.create_empty(8, 8, true, Image.FORMAT_RGBA8)
		image.fill(colors[id])
		image.generate_mipmaps()
		var texture_asset: Object = ClassDB.instantiate("Terrain3DTextureAsset")
		texture_asset.set("name", names[id])
		texture_asset.call("set_albedo_texture", ImageTexture.create_from_image(image))
		assets.call("set_texture", id, texture_asset)
	terrain.set("assets", assets)
	# Shader parameters can only be set once the material belongs to the terrain.
	var material: Object = terrain.get("material")
	material.call("set_auto_shader", true)
	material.call("set_shader_param", "auto_base_texture", 1)
	material.call("set_shader_param", "auto_overlay_texture", 0)
	material.call("set_shader_param", "auto_slope", 10.0)
	material.call("set_shader_param", "auto_height_reduction", 0.0)


## One 256 m region with a hill in the middle, under a NavigationRegion3D offset
## by (100, 5, 100). Terrain3D is top_level, so the parent's offset must not affect it.
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
	# As in a real project: terrain at the origin, even though the parent is offset.
	terrain.global_transform = Transform3D.IDENTITY

	_terrain_look(terrain)
	var data: Object = terrain.call("get_data")
	data.call("add_region_blankp", Vector3(1, 0, 1), true)
	# Painting: sand everywhere (id 2), quadrant x≥128, z<128 auto shader
	# (grass on flat ground, rock on slopes), corner x<32, z<32 tinted red.
	for x: int in 256:
		for z: int in 256:
			var position: Vector3 = Vector3(x, 0, z)
			data.call("set_height", position, maxf(0.0, 20.0 - Vector2(x - 128, z - 128).length() * 0.25))
			data.call("set_control_base_id", position, 2)
			data.call("set_control_overlay_id", position, 2)
			data.call("set_control_blend", position, 0.0)
			data.call("set_control_auto", position, x >= 128 and z < 128)
			if x < 32 and z < 32:
				data.call("set_color", position, Color(1.0, 0.5, 0.5))
	data.call("update_maps", 3, true, false)
	data.call("save_directory", "res://fixtures/terrain_data")

	_instance(nav, root, "crate.glb", "CrateOnHill", Vector3(28, 15, 28))
	return root
