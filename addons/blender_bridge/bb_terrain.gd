@tool
class_name BBTerrain
extends RefCounted

## Terén z Terrain3D pro Blender: mesh s UV a materiálem s upečenou barvou.
##
## Terrain3D kreslí terén vlastním shaderem (splatting z texturového pole,
## control mapa, auto shader podle sklonu), který do Blenderu 1:1 převést
## nejde. Místo toho se shora upeče barevná mapa: v každém pixelu průměrná
## barva textur, které tam control mapa (nebo auto shader) míchá, vynásobená
## barevnou mapou terénu. Na rozmisťování to stačí — je vidět, kde je tráva,
## skála, písek nebo cesta.
##
## Pečení je drahé, takže se výsledek ukládá vedle manifestu a znovu se
## počítá, jen když se změnila data terénu nebo jeho materiál.

## Vrchol terénního meshe každých 2^4 = 16 m.
const MESH_LOD: int = 4
## Delší strana upečené textury v pixelech.
const TEXTURE_SIZE: int = 1024


## Mesh terénu s UV přes celý terén a materiálem s upečenou barvou.
## [param cache_base] je cesta bez přípony, kam se ukládá textura a podpis.
static func mesh_with_material(terrain: Node3D, cache_base: String) -> Mesh:
	var baked: Mesh = terrain.call("bake_mesh", MESH_LOD, 0)
	if baked == null or baked.get_surface_count() == 0:
		return null
	var aabb: AABB = baked.get_aabb()
	var arrays: Array = baked.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = PackedVector2Array()
	uvs.resize(vertices.size())
	for index: int in vertices.size():
		var vertex: Vector3 = vertices[index]
		uvs[index] = Vector2((vertex.x - aabb.position.x) / aabb.size.x, (vertex.z - aabb.position.z) / aabb.size.z)
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	var mesh: ArrayMesh = ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)

	var material: StandardMaterial3D = StandardMaterial3D.new()
	material.resource_name = "Terrain3D"
	material.roughness = 1.0
	material.albedo_texture = ImageTexture.create_from_image(albedo(terrain, aabb, cache_base))
	mesh.surface_set_material(0, material)
	return mesh


## Upečená barva terénu shora, z cache, pokud se terén nezměnil.
static func albedo(terrain: Node3D, aabb: AABB, cache_base: String) -> Image:
	var signature: String = _signature(terrain, aabb)
	var image_path: String = cache_base + ".terrain.png"
	var signature_path: String = cache_base + ".terrain.sig"
	if FileAccess.file_exists(image_path) and FileAccess.file_exists(signature_path) \
			and FileAccess.get_file_as_string(signature_path) == signature:
		var cached: Image = Image.load_from_file(ProjectSettings.globalize_path(image_path))
		if cached != null:
			return cached
	var image: Image = bake_albedo(terrain, aabb)
	image.save_png(ProjectSettings.globalize_path(image_path))
	var file: FileAccess = FileAccess.open(signature_path, FileAccess.WRITE)
	file.store_string(signature)
	file.close()
	return image


static func bake_albedo(terrain: Node3D, aabb: AABB) -> Image:
	var data: Object = terrain.call("get_data")
	var palette: PackedColorArray = _palette(terrain)
	var auto: Dictionary = _auto_shader(terrain)
	var step: float = maxf(1.0, maxf(aabb.size.x, aabb.size.z) / TEXTURE_SIZE)
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
		# Stejný vzorec jako shader Terrain3D (auto_blend).
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


## Průměrná barva každé textury terénu (zmenšením až na 1×1 px), vynásobená
## albedo_color assetu.
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


## Parametr shaderu z uložených hodnot materiálu. [code]get_shader_param[/code]
## se ptá rendereru a bez něj (headless, testy) vrací null; slovník
## [code]_shader_parameters[/code] je k dispozici vždy.
static func _param(material: Object, name: String, fallback: float) -> float:
	if material == null:
		return fallback
	var stored: Variant = material.get("_shader_parameters")
	var value: Variant = (stored as Dictionary).get(StringName(name)) if stored is Dictionary else null
	if value == null:
		value = material.call("get_shader_param", name)
	return float(value) if value != null else fallback


## Co ovlivňuje upečenou barvu: data terénu (soubory regionů), textury
## a parametry auto shaderu, rozsah a rozlišení.
static func _signature(terrain: Node3D, aabb: AABB) -> String:
	var parts: PackedStringArray = [str(aabb), str(TEXTURE_SIZE), str(_auto_shader(terrain))]
	var directory: String = str(terrain.get("data_directory"))
	var files: PackedStringArray = DirAccess.get_files_at(directory) if DirAccess.dir_exists_absolute(directory) else PackedStringArray()
	files.sort()
	for file: String in files:
		var path: String = directory.path_join(file)
		parts.append("%s:%d" % [file, FileAccess.get_modified_time(path)])
	var assets: Object = terrain.get("assets")
	if assets != null:
		for id: int in assets.call("get_texture_count"):
			var texture_asset: Object = assets.call("get_texture", id)
			if texture_asset != null:
				var albedo_texture: Texture2D = texture_asset.call("get_albedo_texture")
				parts.append("%d:%s:%s" % [id, albedo_texture.resource_path if albedo_texture else "", texture_asset.call("get_albedo_color")])
	return "\n".join(parts).md5_text()
