@tool
extends EditorContextMenuPlugin

## Položka „Otevřít v Blenderu“ v kontextovém menu tabu scény a souboru
## [code].tscn[/code] ve FileSystemu.

const LABEL: String = "Otevřít v Blenderu"

var _open_scene: Callable


func _init(open_scene: Callable) -> void:
	_open_scene = open_scene


func _popup_menu(paths: PackedStringArray) -> void:
	for path: String in paths:
		if path.get_extension() == "tscn":
			add_context_menu_item(LABEL, _on_pressed, BBIcons.blender())
			return


func _on_pressed(selection: Variant) -> void:
	for path: String in _paths_of(selection):
		if path.get_extension() == "tscn":
			_open_scene.call(path)
			return


## Sloty předávají výběr různě: FileSystem pole cest, tab scény přímo node.
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
