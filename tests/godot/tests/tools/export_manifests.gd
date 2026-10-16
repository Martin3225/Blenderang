extends SceneTree

## Manifesty fixture scén pro Blender testy. Id jsou čitelná (id_crate, …),
## aby je testy mohly dohledat. Vedle se uloží nedotčené kopie, ze kterých
## si Blender testy manifest před každým testem obnoví.

const BBTest = preload("res://tests/bb_test.gd")


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var helper: RefCounted = BBTest.new()
	helper.tree = self
	var scenes: PackedStringArray = ["basic"]
	if ClassDB.class_exists("Terrain3D"):
		scenes.append("terrain")
	for name: String in scenes:
		var root: Node = helper.scene(name)
		await process_frame
		helper.mark_props(root)
		var path: String = BBManifest.write(root)
		DirAccess.copy_absolute(ProjectSettings.globalize_path(path),
			ProjectSettings.globalize_path("res://.pipeline/%s.pristine.json" % name))
		print("MANIFEST ", path)
	helper._finish()
	# Startovní Python přesně v podobě, v jaké ho plugin předá Blenderu.
	var file: FileAccess = FileAccess.open("res://.pipeline/startup_expr.py", FileAccess.WRITE)
	file.store_string(BBLauncher.startup_expression(ProjectSettings.globalize_path("res://.pipeline/basic.json")))
	file.close()
	quit(0)
