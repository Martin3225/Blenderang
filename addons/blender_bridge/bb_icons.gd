@tool
class_name BBIcons
extends RefCounted

## Ikona pro tlačítka mostu. Bere se z editorového tématu, aby ladila
## s ostatními ikonami a nemusel se do pluginu přidávat obrázek.


static func blender() -> Texture2D:
	var theme: Theme = EditorInterface.get_editor_theme()
	for candidate: StringName in [&"ExternalLink", &"PackedScene", &"Node3D"]:
		if theme.has_icon(candidate, &"EditorIcons"):
			return theme.get_icon(candidate, &"EditorIcons")
	return null
