@tool
class_name BBLauncher
extends RefCounted

## Launches Blender with the scene already built from the manifest.
##
## The Blender path comes from the editor setting Godot itself uses for
## importing .blend: [code]Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸
## Blender Path[/code]. On Linux it may also point to the flatpak wrapper
## [code]/var/lib/flatpak/exports/bin/org.blender.Blender[/code].

const SETTING_BLENDER_PATH: String = "filesystem/import/blender/blender_path"


static func blender_path() -> String:
	var settings: EditorSettings = EditorInterface.get_editor_settings()
	if not settings.has_setting(SETTING_BLENDER_PATH):
		return ""
	return str(settings.get_setting(SETTING_BLENDER_PATH))


## Python that Blender runs after startup. In the GUI the call is deferred with
## a timer, because during [code]--python-expr[/code] no window exists yet and the
## operator would have no context. In [code]--background[/code] timers don't
## run, so it's called right away.
static func startup_expression(manifest_abs: String) -> String:
	# A JSON string is also a valid Python literal, including the backslashes
	# in Windows paths.
	var literal: String = JSON.stringify(manifest_abs)
	return "\n".join([
		"import bpy",
		"def _bb_open():",
		"    bpy.ops.bb.open_from_godot(filepath=%s)" % literal,
		"if bpy.app.background:",
		"    _bb_open()",
		"else:",
		"    bpy.app.timers.register(lambda: _bb_open() and None, first_interval=0.2)",
	])


static func launch(manifest_abs: String) -> Error:
	var executable: String = blender_path()
	if executable.is_empty() or not FileAccess.file_exists(executable):
		push_error(
			"Blender Bridge: set the Blender path in Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path (currently: \"%s\")"
			% executable
		)
		return ERR_FILE_NOT_FOUND
	var pid: int = OS.create_process(executable, ["--python-expr", startup_expression(manifest_abs)])
	return OK if pid > 0 else FAILED
