@tool
class_name BBPaths
extends RefCounted

## Mapování mezi importovaným assetem v [code]res://[/code] a jeho zdrojovým
## [code].blend[/code] souborem.
##
## Zdroj leží [b]vedle[/b] exportovaného assetu se stejným názvem:
## [code]zviretice.glb[/code] → [code]zviretice.blend[/code]. Když to nesedí
## (jeden .blend exportuje víc assetů, nebo zdroj pravdy drží layout scény),
## zapíše se přesná cesta do souboru [code]<asset>.bbsrc[/code] vedle assetu.
##
## Godot má v [code]project.godot[/code] vypnutý import .blend
## ([code]filesystem/import/blender/enabled=false[/code]), takže zdrojové
## soubory můžou ležet kdekoli v projektu, aniž by je kdokoli bez Blenderu
## musel řešit.
##
## Žádný centrální index assetů neexistuje záměrně — jeden soubor, do kterého
## zapisuje celý tým, je zdroj merge konfliktů.

const OVERRIDE_EXTENSION: String = "bbsrc"
const SOURCE_EXTENSION: String = "blend"

## Metadatum na kořeni scény s cestou k layout souboru, když nemá ležet
## vedle [code].tscn[/code].
const META_LAYOUT: StringName = &"bb_layout"


## Cesta ke zdrojovému [code].blend[/code], relativně ke kořeni projektu
## (Blender o [code]res://[/code] neví). Prázdný řetězec znamená, že zdroj
## neexistuje.
static func source_for(asset_path: String) -> String:
	if asset_path.is_empty():
		return ""
	var candidate: String = read_override(asset_path)
	if candidate.is_empty():
		candidate = expected_source_for(asset_path)
	return candidate if FileAccess.file_exists("res://" + candidate) else ""


## Cesta, na kterou se zdroj očekává, i když tam zatím není: vedle assetu,
## stejný název, přípona [code].blend[/code].
static func expected_source_for(asset_path: String) -> String:
	return asset_path.trim_prefix("res://").get_basename() + "." + SOURCE_EXTENSION


## Přesná cesta zapsaná ve [code]<asset>.bbsrc[/code], nebo prázdno.
static func read_override(asset_path: String) -> String:
	var marker: String = override_path(asset_path)
	if not FileAccess.file_exists(marker):
		return ""
	var file: FileAccess = FileAccess.open(marker, FileAccess.READ)
	if file == null:
		return ""
	var value: String = file.get_as_text().strip_edges()
	file.close()
	return value.trim_prefix("res://")


static func override_path(asset_path: String) -> String:
	return "%s.%s" % [asset_path, OVERRIDE_EXTENSION]


## Zapíše výjimku. Prázdná cesta výjimku smaže a vrátí se ke konvenci.
static func write_override(asset_path: String, blend_path: String) -> bool:
	var marker: String = override_path(asset_path)
	if blend_path.is_empty():
		if FileAccess.file_exists(marker):
			return DirAccess.remove_absolute(ProjectSettings.globalize_path(marker)) == OK
		return true
	var file: FileAccess = FileAccess.open(marker, FileAccess.WRITE)
	if file == null:
		push_error("Blender Bridge: nelze zapsat %s" % marker)
		return false
	file.store_string(blend_path.trim_prefix("res://"))
	file.close()
	return true


## Layout scény. Výchozí je soubor vedle [code].tscn[/code]; kořen scény
## může cestu přebít metadatem [constant META_LAYOUT].
static func layout_for(scene_path: String, override: String = "") -> String:
	if not override.is_empty():
		return override.trim_prefix("res://")
	return scene_path.trim_prefix("res://").get_basename() + "." + SOURCE_EXTENSION


## Kde leží zdroj pravdy pro geometrii assetu.
##
## [code]local[/code] — geometrie je přímo v layout souboru scény, edituje
## se bez skákání mezi soubory. Pro unikátní geometrii levelu a whitebox.
## [code]library[/code] — vlastní [code].blend[/code], do layoutu linkovaný.
## [code]none[/code] — zdroj chybí; Blender ukáže model z [code].glb[/code]
## a nabídne z něj zdroj vyrobit.
static func tier_for(asset_path: String, layout: String) -> String:
	var source: String = source_for(asset_path)
	if source.is_empty():
		return "none"
	if source == layout:
		return "local"
	return "library"
