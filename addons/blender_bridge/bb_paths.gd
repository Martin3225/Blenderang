@tool
class_name BBPaths
extends RefCounted

## Mapping between an imported asset in [code]res://[/code] and its source
## [code].blend[/code] file.
##
## The source sits [b]next to[/b] the exported asset with the same name:
## [code]castle.glb[/code] → [code]castle.blend[/code]. When that doesn't fit
## (one .blend exports several assets, or the scene layout holds the source of truth),
## the exact path is written to a [code]<asset>.bbsrc[/code] file next to the asset.
##
## Godot has .blend import turned off in [code]project.godot[/code]
## ([code]filesystem/import/blender/enabled=false[/code]), so source
## files can live anywhere in the project without anyone who lacks Blender
## having to deal with them.
##
## There is deliberately no central asset index: one file the whole team
## writes to is a source of merge conflicts.

const OVERRIDE_EXTENSION: String = "bbsrc"
const SOURCE_EXTENSION: String = "blend"

## Personal choice of sources outside the project. The folder has its own .gitignore with "*",
## so it's never committed and the team's .gitignore doesn't need touching.
const LOCAL_DIR: String = "res://.pipeline/local"
const LOCAL_SOURCES: String = "res://.pipeline/local/sources.json"


## Path to the source [code].blend[/code]: relative to the project root
## (Blender doesn't know [code]res://[/code]), or absolute for a personal source
## outside the project. An empty string means there is no source.
##
## Order: personal choice (only for you) → [code].bbsrc[/code] (shared) →
## [code].blend[/code] next to the asset.
static func source_for(asset_path: String) -> String:
	if asset_path.is_empty():
		return ""
	var personal: String = read_local(asset_path)
	if not personal.is_empty() and FileAccess.file_exists(personal):
		return personal
	var candidate: String = read_override(asset_path)
	if candidate.is_empty():
		candidate = expected_source_for(asset_path)
	return candidate if FileAccess.file_exists("res://" + candidate) else ""


## Is the file inside the project? Only such a path can be shared via [code].bbsrc[/code].
static func is_inside_project(absolute_path: String) -> bool:
	return ProjectSettings.localize_path(absolute_path).begins_with("res://")


## Sets the chosen file as the asset's source. Inside the project → shared
## [code].bbsrc[/code] (and clears any personal choice); outside the project →
## a personal entry others won't see. Returns [code]true[/code] for a personal one.
static func choose_source(asset_path: String, absolute_path: String) -> bool:
	if is_inside_project(absolute_path):
		var relative: String = ProjectSettings.localize_path(absolute_path).trim_prefix("res://")
		write_override(asset_path, "" if relative == expected_source_for(asset_path) else relative)
		write_local(asset_path, "")
		return false
	write_local(asset_path, absolute_path)
	return true


static func read_local(asset_path: String) -> String:
	return str(_local_sources().get(asset_path, ""))


## Writes a personal source (absolute path). An empty path deletes the entry.
static func write_local(asset_path: String, absolute_path: String) -> bool:
	var sources: Dictionary = _local_sources()
	if absolute_path.is_empty():
		sources.erase(asset_path)
	else:
		sources[asset_path] = absolute_path
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(LOCAL_DIR))
	var ignore: String = LOCAL_DIR + "/.gitignore"
	if not FileAccess.file_exists(ignore):
		var marker: FileAccess = FileAccess.open(ignore, FileAccess.WRITE)
		marker.store_string("*\n")
		marker.close()
	var file: FileAccess = FileAccess.open(LOCAL_SOURCES, FileAccess.WRITE)
	if file == null:
		push_error("Blender Bridge: nelze zapsat %s" % LOCAL_SOURCES)
		return false
	file.store_string(JSON.stringify(sources, "\t"))
	file.close()
	return true


static func _local_sources() -> Dictionary:
	if not FileAccess.file_exists(LOCAL_SOURCES):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(LOCAL_SOURCES))
	return parsed if parsed is Dictionary else {}


## Path where the source is expected even if it isn't there yet: next to the asset,
## same name, [code].blend[/code] extension.
static func expected_source_for(asset_path: String) -> String:
	return asset_path.trim_prefix("res://").get_basename() + "." + SOURCE_EXTENSION


## The exact path written in [code]<asset>.bbsrc[/code], or empty.
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


## Writes the override. An empty path deletes it and falls back to the convention.
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


## Where the source of truth for the asset's geometry lives.
##
## [code]library[/code]: its own [code].blend[/code], linked into Blender
## and edited there.
## [code]none[/code]: no source; Blender shows the model from the [code].glb[/code]
## and offers to make a source from it.
##
## The scene itself has no .blend: the layout is always in the [code].tscn[/code]
## and Blender builds it from the manifest each time.
static func tier_for(asset_path: String) -> String:
	return "none" if source_for(asset_path).is_empty() else "library"
