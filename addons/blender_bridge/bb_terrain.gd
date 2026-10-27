@tool
class_name BBTerrain
extends RefCounted

## Terrain3D terrain for Blender: a mesh with UVs and a material with baked colour.
##
## Terrain3D draws terrain with its own shader (splatting from a texture array,
## control map, slope-based auto shader), which can't be reproduced 1:1 in
## Blender. Instead a colour map is baked from above: in each pixel the average
## colour of the textures the control map (or auto shader) blends there, multiplied
## by the terrain's colour map. That's enough for layout: you can see where grass,
## rock, sand or a path is.
##
## Baking is expensive, so the mesh and texture are cached next to the manifest and
## recomputed only when the terrain data, its material or the settings change.
##
## Resolution is in [code]Project Settings ▸ Blender Bridge ▸ Terrain[/code],
## and applies to the whole team.

const SETTING_SPACING: String = "blender_bridge/terrain/mesh_spacing_m"
const SETTING_TEXTURE: String = "blender_bridge/terrain/texture_size"
## Distance between mesh vertices in metres. Terrain3D bakes in powers of two
## of its vertex spacing (LOD 0–8).
const DEFAULT_SPACING: int = 8
## Longer side of the baked texture in pixels.
const DEFAULT_TEXTURE: int = 2048
const MAX_LOD: int = 8
## Above this many vertices a warning is shown; Blender and glTF export will be slow.
const WARN_VERTICES: int = 4_000_000


## Registers the settings so they show up in Project Settings. A value equal
## to the default isn't saved to project.godot.
static func register_settings() -> void:
	_register(SETTING_SPACING, DEFAULT_SPACING, "1 m:1,2 m:2,4 m:4,8 m:8,16 m:16,32 m:32")
	_register(SETTING_TEXTURE, DEFAULT_TEXTURE, "1024 px:1024,2048 px:2048,4096 px:4096,8192 px:8192")


static func _register(name: String, value: int, hint: String) -> void:
	if not ProjectSettings.has_setting(name):
		ProjectSettings.set_setting(name, value)
	ProjectSettings.set_initial_value(name, value)
	ProjectSettings.add_property_info({"name": name, "type": TYPE_INT, "hint": PROPERTY_HINT_ENUM, "hint_string": hint})
	ProjectSettings.set_as_basic(name, true)


## LOD for [code]bake_mesh[/code]: the power of two closest to the configured
## vertex spacing, relative to the terrain's vertex_spacing.
static func mesh_lod(terrain: Node3D) -> int:
	var meters: float = float(ProjectSettings.get_setting(SETTING_SPACING, DEFAULT_SPACING))
	var ratio: float = maxf(1.0, meters / float(terrain.get("vertex_spacing")))
	return clampi(roundi(log(ratio) / log(2.0)), 0, MAX_LOD)


static func texture_size() -> int:
	return clampi(int(ProjectSettings.get_setting(SETTING_TEXTURE, DEFAULT_TEXTURE)), 256, 16384)


## Terrain mesh with UVs across the whole terrain and a material with baked colour.
## [param cache_base] is the path without extension where the mesh, texture
## and signatures are stored.
static func mesh_with_material(terrain: Node3D, cache_base: String) -> Mesh:
	var mesh: ArrayMesh = terrain_mesh(terrain, cache_base)
	if mesh == null:
		return null
	var material: StandardMaterial3D = StandardMaterial3D.new()
	material.resource_name = "Terrain3D"
	material.roughness = 1.0
	material.albedo_texture = ImageTexture.create_from_image(albedo(terrain, mesh.get_aabb(), cache_base))
	mesh.surface_set_material(0, material)
	return mesh


## Terrain mesh with UVs, from cache if neither the terrain nor the resolution changed.
static func terrain_mesh(terrain: Node3D, cache_base: String) -> ArrayMesh:
	var lod: int = mesh_lod(terrain)
	var parts: PackedStringArray = ["lod:%d" % lod, "spacing:%s" % terrain.get("vertex_spacing")]
	var signature: String = _signature(parts + _data_parts(terrain))
	var mesh_path: String = cache_base + ".terrain.res"
	var signature_path: String = cache_base + ".terrain.mesh.sig"
	if FileAccess.file_exists(mesh_path) and _cache_valid(signature_path, signature):
		var cached: ArrayMesh = ResourceLoader.load(mesh_path, "ArrayMesh", ResourceLoader.CACHE_MODE_IGNORE) as ArrayMesh
		if cached != null and cached.get_surface_count() > 0:
			return cached
	var mesh: ArrayMesh = _bake_mesh(terrain, lod)
	if mesh == null:
		return null
	if ResourceSaver.save(mesh, mesh_path, ResourceSaver.FLAG_COMPRESS) == OK:
		_store_signature(signature_path, signature)
	return mesh


static func _bake_mesh(terrain: Node3D, lod: int) -> ArrayMesh:
	var baked: Mesh = terrain.call("bake_mesh", lod, 0)
	if baked == null or baked.get_surface_count() == 0:
		return null
	var aabb: AABB = baked.get_aabb()
	var arrays: Array = baked.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	if vertices.size() > WARN_VERTICES:
		push_warning("Blender Bridge: terrain has %d vertices, Blender will be slow. Lower %s." % [vertices.size(), SETTING_SPACING])
	var uvs: PackedVector2Array = PackedVector2Array()
	uvs.resize(vertices.size())
	for index: int in vertices.size():
		var vertex: Vector3 = vertices[index]
		uvs[index] = Vector2((vertex.x - aabb.position.x) / aabb.size.x, (vertex.z - aabb.position.z) / aabb.size.z)
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	var mesh: ArrayMesh = ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


## Baked top-down colour of the terrain, from cache if the terrain didn't change.
static func albedo(terrain: Node3D, aabb: AABB, cache_base: String) -> Image:
	var signature: String = _albedo_signature(terrain, aabb)
	var image_path: String = cache_base + ".terrain.png"
	var signature_path: String = cache_base + ".terrain.sig"
	if FileAccess.file_exists(image_path) and _cache_valid(signature_path, signature):
		var cached: Image = Image.load_from_file(ProjectSettings.globalize_path(image_path))
		if cached != null:
			return cached
	var image: Image = bake_albedo(terrain, aabb)
	image.save_png(ProjectSettings.globalize_path(image_path))
	_store_signature(signature_path, signature)
	return image


static func _cache_valid(signature_path: String, signature: String) -> bool:
	return FileAccess.file_exists(signature_path) and FileAccess.get_file_as_string(signature_path) == signature


static func _store_signature(signature_path: String, signature: String) -> void:
	var file: FileAccess = FileAccess.open(signature_path, FileAccess.WRITE)
	file.store_string(signature)
	file.close()


static func bake_albedo(terrain: Node3D, aabb: AABB) -> Image:
	var data: Object = terrain.call("get_data")
	var palette: PackedColorArray = _palette(terrain)
	var auto: Dictionary = _auto_shader(terrain)
	var step: float = maxf(1.0, maxf(aabb.size.x, aabb.size.z) / texture_size())
	var width: int = maxi(1, ceili(aabb.size.x / step))
	var height: int = maxi(1, ceili(aabb.size.z / step))
	var image: Image = Image.create_empty(width, height, false, Image.FORMAT_RGB8)
	for y: int in height:
		for x: int in width:
			var position: Vector3 = Vector3(aabb.position.x + (x + 0.5) * step, 0.0, aabb.position.z + (y + 0.5) * step)
			image.set_pixel(x, y, _color_at(data, position, palette, auto))
	return image


static func _color_at(data: Object, position: Vector3, palette: PackedColorArray, auto: Dictionary) -> Color:
	var control: int = data.call("get_control", position)
	var base: int
	var overlay: int
	var blend: float
	if auto["enabled"] and Terrain3DUtil.is_auto(control):
		var normal: Vector3 = data.call("get_normal", position)
		var elevation: float = data.call("get_height", position)
		# Same formula as the Terrain3D shader (auto_blend).
		blend = clampf(auto["slope"] * 2.0 * (normal.y - 1.0) + 1.0 - auto["height_reduction"] * 0.01 * elevation, 0.0, 1.0)
		base = auto["base"]
		overlay = auto["overlay"]
	else:
		base = Terrain3DUtil.get_base(control)
		overlay = Terrain3DUtil.get_overlay(control)
		blend = Terrain3DUtil.get_blend(control)
	var color: Color = _pick(palette, base).lerp(_pick(palette, overlay), blend)
	var tint: Color = data.call("get_color", position)
	if not is_nan(tint.r):
		color *= Color(tint.r, tint.g, tint.b)
	color.a = 1.0
	return color


static func _pick(palette: PackedColorArray, index: int) -> Color:
	return palette[index] if index >= 0 and index < palette.size() else Color(0.5, 0.5, 0.5)


## Average colour of each terrain texture (downscaled to 1×1 px), multiplied
## by the asset's albedo_color.
static func _palette(terrain: Node3D) -> PackedColorArray:
	var palette: PackedColorArray = PackedColorArray()
	var assets: Object = terrain.get("assets")
	if assets == null:
		return palette
	for id: int in assets.call("get_texture_count"):
		var texture_asset: Object = assets.call("get_texture", id)
		var color: Color = Color(0.5, 0.5, 0.5)
		if texture_asset != null:
			var albedo_texture: Texture2D = texture_asset.call("get_albedo_texture")
			if albedo_texture != null:
				color = _average(albedo_texture.get_image())
			color *= texture_asset.call("get_albedo_color")
		color.a = 1.0
		palette.append(color)
	return palette


static func _average(source: Image) -> Color:
	if source == null:
		return Color(0.5, 0.5, 0.5)
	var image: Image = source.duplicate()
	if image.is_compressed():
		image.decompress()
	image.convert(Image.FORMAT_RGBA8)
	while image.get_width() > 1 or image.get_height() > 1:
		image.resize(maxi(1, image.get_width() / 2), maxi(1, image.get_height() / 2), Image.INTERPOLATE_BILINEAR)
	return image.get_pixel(0, 0)


static func _auto_shader(terrain: Node3D) -> Dictionary:
	var material: Object = terrain.get("material")
	var enabled: bool = material != null and material.call("get_auto_shader")
	return {
		"enabled": enabled,
		"slope": _param(material, "auto_slope", 1.0),
		"height_reduction": _param(material, "auto_height_reduction", 0.1),
		"base": int(_param(material, "auto_base_texture", 0)),
		"overlay": int(_param(material, "auto_overlay_texture", 1)),
	}


## Shader parameter from the material's stored values. [code]get_shader_param[/code]
## asks the renderer and returns null without one (headless, tests); the
## [code]_shader_parameters[/code] dictionary is always available.
static func _param(material: Object, name: String, fallback: float) -> float:
	if material == null:
		return fallback
	var stored: Variant = material.get("_shader_parameters")
	var value: Variant = (stored as Dictionary).get(StringName(name)) if stored is Dictionary else null
	if value == null:
		value = material.call("get_shader_param", name)
	return float(value) if value != null else fallback


## What affects the baked colour: terrain data, textures and auto shader
## parameters, extent and resolution.
static func _albedo_signature(terrain: Node3D, aabb: AABB) -> String:
	var parts: PackedStringArray = [str(aabb), str(texture_size()), str(_auto_shader(terrain))]
	parts += _data_parts(terrain)
	var assets: Object = terrain.get("assets")
	if assets != null:
		for id: int in assets.call("get_texture_count"):
			var texture_asset: Object = assets.call("get_texture", id)
			if texture_asset != null:
				var albedo_texture: Texture2D = texture_asset.call("get_albedo_texture")
				parts.append("%d:%s:%s" % [id, albedo_texture.resource_path if albedo_texture else "", texture_asset.call("get_albedo_color")])
	return _signature(parts)


## Terrain region files and their modification times.
static func _data_parts(terrain: Node3D) -> PackedStringArray:
	var parts: PackedStringArray = []
	var directory: String = str(terrain.get("data_directory"))
	var files: PackedStringArray = DirAccess.get_files_at(directory) if DirAccess.dir_exists_absolute(directory) else PackedStringArray()
	files.sort()
	for file: String in files:
		parts.append("%s:%d" % [file, FileAccess.get_modified_time(directory.path_join(file))])
	return parts


static func _signature(parts: PackedStringArray) -> String:
	return "\n".join(parts).md5_text()
