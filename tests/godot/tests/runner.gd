extends SceneTree

## Runs all res://tests/unit/test_*.gd and writes the results to JSON
## (path after the --out argument). Test order is declaration order in the file.

const UNIT_DIR: String = "res://tests/unit/"


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var results: Array = []
	var files: PackedStringArray = DirAccess.get_files_at(UNIT_DIR)
	files.sort()
	for file: String in files:
		if not (file.begins_with("test_") and file.ends_with(".gd")):
			continue
		var suite: RefCounted = load(UNIT_DIR + file).new()
		suite.tree = self
		var group: String = file.get_basename().trim_prefix("test_")
		for method: String in _test_methods(suite):
			suite._begin()
			await suite.call(method)
			var result: Dictionary = suite._finish()
			result["name"] = "%s.%s" % [group, method.trim_prefix("test_")]
			results.append(result)
			print("%s %s %s" % [result["status"], result["name"], result.get("message", "")])
	var out: String = _arg("--out")
	var file_out: FileAccess = FileAccess.open(out, FileAccess.WRITE)
	file_out.store_string(JSON.stringify(results, "\t"))
	file_out.close()
	quit(0)


func _test_methods(suite: Object) -> PackedStringArray:
	var names: PackedStringArray = []
	for method: Dictionary in suite.get_method_list():
		var name: String = method["name"]
		if name.begins_with("test_") and not names.has(name):
			names.append(name)
	return names


func _arg(key: String) -> String:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var index: int = args.find(key)
	return args[index + 1] if index >= 0 and index + 1 < args.size() else ""
