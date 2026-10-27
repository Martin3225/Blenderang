@tool
class_name BBIcons
extends RefCounted

## Icon for the bridge buttons. Taken from the editor theme so it matches
## the other icons and no image needs to be added to the plugin.


static func blender() -> Texture2D:
	var theme: Theme = EditorInterface.get_editor_theme()
	for candidate: StringName in [&"ExternalLink", &"PackedScene", &"Node3D"]:
		if theme.has_icon(candidate, &"EditorIcons"):
			return theme.get_icon(candidate, &"EditorIcons")
	return null
