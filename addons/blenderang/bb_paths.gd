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
## Sources can also live in a [b]models folder[/b] outside the project (e.g. a separate
## git repository the team shares). Each person sets where it is on their disk
## ([code].pipeline/local/settings.json[/code]); shared paths into it are written
## as [code]models://<path inside the folder>[/code], so they are the same for everyone.
## Without an exact path, the folder is searched for [code]<asset name>.blend[/code].
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
const MODELS_PREFIX: String = "models://"
## Assets that can have a source .blend.
const MODEL_EXTENSIONS: PackedStringArray = ["glb", "gltf", "fbx"]

## Personal choice of sources outside the project. The folder has its own .gitignore with "*",
## so it's never committed and the team's .gitignore doesn't need touching.
const LOCAL_DIR: String = "res://.pipeline/local"
const LOCAL_SOURCES: String = "res://.pipeline/local/sources.json"
## Personal settings: where the models folder is on this disk.
const LOCAL_SETTINGS: String = "res://.pipeline/local/settings.json"
## Project setting, shared by the team: the folder of the project the models folder
## mirrors. With the default, the source of [code]res://assets/levels/castle.glb[/code]
## is [code]levels/castle.blend[/code] in the models folder. Blender reads it from project.godot.
const SETTING_MODELS_MIRROR: String = "blenderang/models/project_folder"
const DEFAULT_MODELS_MIRROR: String = "assets"

## [code].blend[/code] files in the models folder by lowercase name; built once
## per manifest export (see [method forget_models_index]).
static var _models_index: Dictionary = {}
static var _models_index_folder: String = ""


## Path to the source [code].blend[/code]: relative to the project root
## (Blender doesn't know [code]res://[/code]), [code]models://…[/code] inside the
## models folder, or absolute for a personal source outside both. An empty string
## means there is no source. [method absolute_source] turns it into a file path.
##
## Order: personal choice (only for you) → [code].bbsrc[/code] (shared) →
## [code].blend[/code] next to the asset → [code]<name>.blend[/code] in the models folder.
static func source_for(asset_path: String) -> String:
	if asset_path.is_empty():
		return ""
	var personal: String = read_local(asset_path)
	if not personal.is_empty() and FileAccess.file_exists(personal):
		return personal
	return _shared_source_for(asset_path)


## [method source_for] without the personal choice: the source the whole team gets.
static func _shared_source_for(asset_path: String) -> String:
	var candidate: String = read_override(asset_path)
	if candidate.is_empty():
		candidate = expected_source_for(asset_path)
		if not FileAccess.file_exists("res://" + candidate):
			candidate = find_in_models_folder(asset_path)
	if candidate.is_empty():
		return ""
	return candidate if FileAccess.file_exists(absolute_source(candidate)) else ""


## Keeps the source of an asset the FileSystem dock moved or renamed (called after
## the move). The personal choice and [code].bbsrc[/code] follow the asset; when the
## source wouldn't resolve the same way at the new path (renamed asset, a .blend left
## next to the old place), a [code].bbsrc[/code] there points to it. A moved folder
## takes its .bbsrc and .blend files along on disk; project paths inside .bbsrc are
## moved along with it.
static func follow_move(old_asset: String, new_asset: String) -> void:
	var personal: String = read_local(old_asset)
	if not personal.is_empty():
		write_local(old_asset, "")
		write_local(new_asset, personal)
	var before: String = _source_before_move(old_asset, new_asset)
	write_override(old_asset, "")
	if before.is_empty() or _shared_source_for(new_asset) == before:
		return
	write_override(new_asset, "" if before == expected_source_for(new_asset) else before)


## The shared source the asset had at its old path, as a path valid after the move.
static func _source_before_move(old_asset: String, new_asset: String) -> String:
	# A single file moves alone and its .bbsrc stays; a moved folder takes it along.
	var marker: String = read_override(old_asset)
	if marker.is_empty():
		marker = read_override(new_asset)
	if not marker.is_empty():
		var moved: String = _moved_along(marker, old_asset, new_asset)
		return moved if FileAccess.file_exists(absolute_source(moved)) else ""
	var sibling: String = _moved_along(expected_source_for(old_asset), old_asset, new_asset)
	if FileAccess.file_exists("res://" + sibling):
		return sibling
	return find_in_models_folder(old_asset)


## A project path after the asset's move: unchanged while the file is still there,
## otherwise moved like the asset's folder ([code]a/b/x.glb[/code] → [code]c/b/x.glb[/code]
## moved [code]a/[/code] to [code]c/[/code]).
static func _moved_along(stored: String, old_asset: String, new_asset: String) -> String:
	if stored.begins_with(MODELS_PREFIX) or stored.is_absolute_path() or FileAccess.file_exists("res://" + stored):
		return stored
	var old_parts: PackedStringArray = old_asset.trim_prefix("res://").split("/")
	var new_parts: PackedStringArray = new_asset.trim_prefix("res://").split("/")
	while old_parts.size() > 1 and new_parts.size() > 1 \
			and old_parts[old_parts.size() - 1] == new_parts[new_parts.size() - 1]:
		old_parts.remove_at(old_parts.size() - 1)
		new_parts.remove_at(new_parts.size() - 1)
	var old_folder: String = "/".join(old_parts) + "/"
	if not stored.begins_with(old_folder):
		return stored
	return "/".join(new_parts) + "/" + stored.substr(old_folder.length())


## File path of a source as [method source_for] returns it. A [code]models://[/code]
## path without a models folder set resolves to an empty string.
static func absolute_source(source: String) -> String:
	if source.begins_with(MODELS_PREFIX):
		var folder: String = models_folder()
		return "" if folder.is_empty() else folder.path_join(source.trim_prefix(MODELS_PREFIX))
	if source.is_absolute_path():
		return source
	return ProjectSettings.globalize_path("res://" + source)


## Is the file inside the project? Only such a path can be shared via [code].bbsrc[/code].
static func is_inside_project(absolute_path: String) -> bool:
	return ProjectSettings.localize_path(absolute_path).begins_with("res://")


## [code]models://…[/code] for a file inside the models folder, otherwise empty.
static func to_models_path(absolute_path: String) -> String:
	var folder: String = models_folder()
	if folder.is_empty():
		return ""
	var path: String = absolute_path.replace("\\", "/").simplify_path()
	var inside: bool = path.to_lower().begins_with(folder.to_lower() + "/") if OS.get_name() == "Windows" \
			else path.begins_with(folder + "/")
	return MODELS_PREFIX + path.substr(folder.length() + 1) if inside else ""


## Sets the chosen file as the asset's source. Inside the project or the models
## folder → shared [code].bbsrc[/code] (and clears any personal choice); elsewhere →
## a personal entry others won't see. Returns [code]true[/code] for a personal one.
static func choose_source(asset_path: String, absolute_path: String) -> bool:
	if is_inside_project(absolute_path):
		var relative: String = ProjectSettings.localize_path(absolute_path).trim_prefix("res://")
		write_override(asset_path, "" if relative == expected_source_for(asset_path) else relative)
		write_local(asset_path, "")
		return false
	var shared: String = to_models_path(absolute_path)
	if not shared.is_empty():
		write_override(asset_path, shared)
		write_local(asset_path, "")
		return false
	write_local(asset_path, absolute_path)
	return true


static func read_local(asset_path: String) -> String:
	return str(_read_json(LOCAL_SOURCES).get(asset_path, ""))


## Writes a personal source (absolute path). An empty path deletes the entry.
static func write_local(asset_path: String, absolute_path: String) -> bool:
	var sources: Dictionary = _read_json(LOCAL_SOURCES)
	if absolute_path.is_empty():
		sources.erase(asset_path)
	else:
		sources[asset_path] = absolute_path
	return _write_local_json(LOCAL_SOURCES, sources)


## Absolute path of the models folder on this disk (forward slashes), or empty when not set.
static func models_folder() -> String:
	var folder: String = str(_read_json(LOCAL_SETTINGS).get("models_folder", ""))
	return folder.replace("\\", "/").simplify_path().trim_suffix("/") if not folder.is_empty() else ""


## Sets where the models folder is on this disk. An empty path unsets it.
static func set_models_folder(absolute_path: String) -> bool:
	var settings: Dictionary = _read_json(LOCAL_SETTINGS)
	if absolute_path.is_empty():
		settings.erase("models_folder")
	else:
		settings["models_folder"] = absolute_path.simplify_path()
	forget_models_index()
	return _write_local_json(LOCAL_SETTINGS, settings)


## Registers the shared settings so they show up in Project Settings. A value equal
## to the default isn't saved to project.godot.
static func register_settings() -> void:
	if not ProjectSettings.has_setting(SETTING_MODELS_MIRROR):
		ProjectSettings.set_setting(SETTING_MODELS_MIRROR, DEFAULT_MODELS_MIRROR)
	ProjectSettings.set_initial_value(SETTING_MODELS_MIRROR, DEFAULT_MODELS_MIRROR)
	ProjectSettings.add_property_info({"name": SETTING_MODELS_MIRROR, "type": TYPE_STRING})
	ProjectSettings.set_as_basic(SETTING_MODELS_MIRROR, true)


## The project folder the models folder mirrors, without slashes; may be empty.
static func models_mirror() -> String:
	return str(ProjectSettings.get_setting(SETTING_MODELS_MIRROR, DEFAULT_MODELS_MIRROR)) \
			.replace("\\", "/").lstrip("/").rstrip("/")


## Where the asset's source sits in the models folder by convention: the asset's
## path without the mirrored project folder ([code]res://assets/levels/castle.glb[/code]
## → [code]levels/castle.blend[/code]). Assets outside that folder keep their whole path.
static func models_relative(asset_path: String) -> String:
	var expected: String = expected_source_for(asset_path)
	var mirror: String = models_mirror()
	if not mirror.is_empty() and expected.begins_with(mirror + "/"):
		return expected.substr(mirror.length() + 1)
	return expected


## [code]models://…[/code] path of [code]<asset name>.blend[/code] in the models folder,
## or empty. The name is matched case-insensitively at any depth. With several
## matches the one at the asset's mirrored path ([method models_relative])
## wins, otherwise the first alphabetically; pick the source by hand to be explicit.
static func find_in_models_folder(asset_path: String) -> String:
	var folder: String = models_folder()
	if folder.is_empty():
		return ""
	if folder != _models_index_folder:
		_models_index = _index_models(folder)
		_models_index_folder = folder
	var mirrored: String = models_relative(asset_path)
	var matches: Array = _models_index.get(mirrored.get_file().to_lower(), [])
	if matches.is_empty():
		return ""
	if matches.has(mirrored):
		return MODELS_PREFIX + mirrored
	if matches.size() > 1:
		push_warning("Blenderang: several %s in the models folder, using %s; pick the source to choose another." % [mirrored.get_file(), matches[0]])
	return MODELS_PREFIX + str(matches[0])


## Drops the cached listing of the models folder; the next lookup scans it again.
static func forget_models_index() -> void:
	_models_index = {}
	_models_index_folder = ""


## Lowercase file name → sorted relative paths. Hidden folders (.git) are skipped.
static func _index_models(folder: String) -> Dictionary:
	var index: Dictionary = {}
	var pending: Array[String] = [""]
	while not pending.is_empty():
		var relative: String = pending.pop_back()
		var directory: String = folder.path_join(relative)
		for name: String in DirAccess.get_directories_at(directory):
			if not name.begins_with("."):
				pending.push_back(relative.path_join(name))
		for name: String in DirAccess.get_files_at(directory):
			if name.get_extension().to_lower() == SOURCE_EXTENSION:
				var key: String = name.to_lower()
				if not index.has(key):
					index[key] = []
				index[key].append(relative.path_join(name))
	for key: String in index:
		index[key].sort()
	return index


static func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Dictionary else {}


static func _write_local_json(path: String, data: Dictionary) -> bool:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(LOCAL_DIR))
	var ignore: String = LOCAL_DIR + "/.gitignore"
	if not FileAccess.file_exists(ignore):
		var marker: FileAccess = FileAccess.open(ignore, FileAccess.WRITE)
		marker.store_string("*\n")
		marker.close()
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Blenderang: cannot write %s" % path)
		return false
	file.store_string(JSON.stringify(data, "\t"))
	file.close()
	return true


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
		push_error("Blenderang: cannot write %s" % marker)
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
	return tier_of(source_for(asset_path))


static func tier_of(source: String) -> String:
	return "none" if source.is_empty() else "library"
