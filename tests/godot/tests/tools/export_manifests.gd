extends SceneTree

## Manifests of the fixture scenes for the Blender tests. Ids are readable (id_crate, …)
## so the tests can find them. The Blender harness backs up the whole .pipeline
## and restores it before each test.

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
		print("MANIFEST ", BBManifest.write(root))
	helper._finish()
	# Startup Python exactly as the plugin passes it to Blender.
	var file: FileAccess = FileAccess.open("res://.pipeline/startup_expr.py", FileAccess.WRITE)
	file.store_string(BBLauncher.startup_expression(ProjectSettings.globalize_path("res://.pipeline/basic.json")))
	file.close()
	# "Open source in Blender" for crate.glb with a source next to it.
	file = FileAccess.open("res://.pipeline/source_expr.py", FileAccess.WRITE)
	file.store_string(BBLauncher.source_expression(
		ProjectSettings.globalize_path("res://fixtures/assets/crate.blend"),
		"res://fixtures/assets/crate.glb",
		ProjectSettings.globalize_path("res://").trim_suffix("/")))
	file.close()
	quit(0)
