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


## Python that opens the scene from the manifest after Blender starts.
static func startup_expression(manifest_abs: String) -> String:
	# A JSON string is also a valid Python literal, including the backslashes
	# in Windows paths.
	return _deferred_call("bpy.ops.bb.open_from_godot(filepath=%s)" % JSON.stringify(manifest_abs))


## Python that opens a model's source .blend without a scene; saving it
## regenerates [param asset] in the project at [param root_abs].
static func source_expression(source_abs: String, asset: String, root_abs: String) -> String:
	return _deferred_call("bpy.ops.bb.open_source(filepath=%s, asset=%s, root=%s)" % [
		JSON.stringify(source_abs), JSON.stringify(asset), JSON.stringify(root_abs)])


## In the GUI the call is deferred with a timer, because during
## [code]--python-expr[/code] no window exists yet and the operator would have
## no context. In [code]--background[/code] timers don't run, so it's called right away.
static func _deferred_call(call: String) -> String:
	return "\n".join([
		"import bpy",
		"def _bb_open():",
		"    " + call,
		"if bpy.app.background:",
		"    _bb_open()",
		"else:",
		"    bpy.app.timers.register(lambda: _bb_open() and None, first_interval=0.2)",
	])


static func launch(manifest_abs: String) -> Error:
	return _launch(startup_expression(manifest_abs))


static func launch_source(source_abs: String, asset: String) -> Error:
	var root: String = ProjectSettings.globalize_path("res://").trim_suffix("/")
	return _launch(source_expression(source_abs, asset, root))


static func _launch(expression: String) -> Error:
	var executable: String = blender_path()
	if executable.is_empty() or not FileAccess.file_exists(executable):
		push_error(
			"Blenderang: set the Blender path in Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path (currently: \"%s\")"
			% executable
		)
		return ERR_FILE_NOT_FOUND
	var pid: int = OS.create_process(executable, python_args(expression))
	return OK if pid > 0 else FAILED


## Blender arguments that run [param expression].
## On Windows [method OS.create_process] builds one command line and wraps an
## argument containing spaces in quotes without escaping the quotes and
## backslashes inside it, so the expression (JSON strings, Windows paths,
## newlines) would reach Blender cut apart. Base64 contains none of those.
static func python_args(expression: String) -> PackedStringArray:
	return PackedStringArray([
		"--python-expr",
		"import base64; exec(base64.b64decode('%s').decode('utf-8'))" % Marshalls.utf8_to_base64(expression),
	])
