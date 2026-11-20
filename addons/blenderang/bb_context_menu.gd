@tool
extends EditorContextMenuPlugin

## Context menu items: "Open in Blender" on a scene tab and on a [code].tscn[/code]
## in the FileSystem, "Open source in Blender" on an imported model whose source
## [code].blend[/code] exists.

const LABEL: String = "Open in Blender"
const SOURCE_LABEL: String = "Open source in Blender"
const MODEL_EXTENSIONS: PackedStringArray = ["glb", "gltf", "fbx"]

var _open_scene: Callable
var _open_source: Callable


func _init(open_scene: Callable, open_source: Callable) -> void:
	_open_scene = open_scene
	_open_source = open_source


func _popup_menu(paths: PackedStringArray) -> void:
	if not _scene_of(paths).is_empty():
		add_context_menu_item(LABEL, _on_pressed, BBIcons.blender())
	var model: String = _model_of(paths)
	if model.is_empty():
		return
	# The models folder may have changed since the last look (git pull).
	BBPaths.forget_models_index()
	if not BBPaths.source_for(model).is_empty():
		add_context_menu_item(SOURCE_LABEL, _on_source_pressed, BBIcons.blender())


func _on_pressed(selection: Variant) -> void:
	var scene: String = _scene_of(_paths_of(selection))
	if not scene.is_empty():
		_open_scene.call(scene)


func _on_source_pressed(selection: Variant) -> void:
	var model: String = _model_of(_paths_of(selection))
	if not model.is_empty():
		_open_source.call(model)


func _scene_of(paths: PackedStringArray) -> String:
	for path: String in paths:
		if path.get_extension() == "tscn":
			return path
	return ""


## Only for a single selected model: one click shouldn't start several Blenders.
func _model_of(paths: PackedStringArray) -> String:
	if paths.size() == 1 and MODEL_EXTENSIONS.has(paths[0].get_extension().to_lower()):
		return paths[0]
	return ""


## Slots pass the selection differently: FileSystem an array of paths, scene tab the node itself.
func _paths_of(selection: Variant) -> PackedStringArray:
	if selection is PackedStringArray:
		return selection
	if selection is Array:
		var paths: PackedStringArray = []
		for item: Variant in selection:
			paths.append(item.scene_file_path if item is Node else str(item))
		return paths
	if selection is Node:
		return PackedStringArray([selection.scene_file_path])
	return PackedStringArray([str(selection)])
