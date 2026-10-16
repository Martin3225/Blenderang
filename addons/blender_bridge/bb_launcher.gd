@tool
class_name BBLauncher
extends RefCounted

## Spuštění Blenderu se scénou rovnou postavenou z manifestu.
##
## Cesta k Blenderu se bere z editorového nastavení, které Godot sám používá
## pro import .blend: [code]Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸
## Blender Path[/code]. Na Linuxu může ukazovat i na flatpak wrapper
## [code]/var/lib/flatpak/exports/bin/org.blender.Blender[/code].

const SETTING_BLENDER_PATH: String = "filesystem/import/blender/blender_path"


static func blender_path() -> String:
	var settings: EditorSettings = EditorInterface.get_editor_settings()
	if not settings.has_setting(SETTING_BLENDER_PATH):
		return ""
	return str(settings.get_setting(SETTING_BLENDER_PATH))


## Python, který Blender spustí po startu. V GUI se volání odloží časovačem,
## protože při [code]--python-expr[/code] ještě neexistuje okno a operátor
## by neměl kontext. V [code]--background[/code] časovače neběží, tam se
## volá hned.
static func startup_expression(manifest_abs: String) -> String:
	# JSON řetězec je zároveň platný Python literál, včetně zpětných lomítek
	# z Windows cest.
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
			"Blender Bridge: nastav cestu k Blenderu v Editor Settings ▸ FileSystem ▸ Import ▸ Blender ▸ Blender Path (teď: \"%s\")"
			% executable
		)
		return ERR_FILE_NOT_FOUND
	var pid: int = OS.create_process(executable, ["--python-expr", startup_expression(manifest_abs)])
	return OK if pid > 0 else FAILED
