extends "res://tests/bb_test.gd"

## Finding the source .blend.

const ASSET: String = "res://fixtures/assets/crate.glb"
const SIBLING: String = "res://fixtures/assets/crate.blend"
const ELSEWHERE: String = "res://fixtures/elsewhere.blend"


var _outside: String = ProjectSettings.globalize_path("res://").path_join("../outside_sources/crate_master.blend").simplify_path()


func _cleanup() -> void:
	remove_file(SIBLING)
	remove_file(ELSEWHERE)
	remove_file(BBPaths.override_path(ASSET))
	remove_file(BBPaths.LOCAL_SOURCES)
	if FileAccess.file_exists(_outside):
		DirAccess.remove_absolute(_outside)


func _make_outside() -> void:
	DirAccess.make_dir_recursive_absolute(_outside.get_base_dir())
	var file: FileAccess = FileAccess.open(_outside, FileAccess.WRITE)
	file.close()


func test_no_source_is_tier_none() -> void:
	_cleanup()
	eq(BBPaths.source_for(ASSET), "", "source")
	eq(BBPaths.tier_for(ASSET), "none", "tier")
	eq(BBPaths.expected_source_for(ASSET), "fixtures/assets/crate.blend", "expected path")
	done()


func test_sibling_blend_is_found() -> void:
	_cleanup()
	write_file(SIBLING, "")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "source next to the asset")
	eq(BBPaths.tier_for(ASSET), "library", "tier")
	_cleanup()
	done()


func test_override_wins_over_sibling() -> void:
	_cleanup()
	write_file(SIBLING, "")
	write_file(ELSEWHERE, "")
	check(BBPaths.write_override(ASSET, ELSEWHERE), "writing .bbsrc")
	eq(BBPaths.source_for(ASSET), "fixtures/elsewhere.blend", "the exact path takes precedence")
	_cleanup()
	done()


func test_override_to_missing_file_is_none() -> void:
	_cleanup()
	write_file(SIBLING, "")
	BBPaths.write_override(ASSET, ELSEWHERE)
	eq(BBPaths.source_for(ASSET), "", "a missing picked source isn't replaced by the convention")
	_cleanup()
	done()


func test_empty_override_removes_marker() -> void:
	_cleanup()
	BBPaths.write_override(ASSET, ELSEWHERE)
	check(BBPaths.write_override(ASSET, ""), "deleting")
	check(not FileAccess.file_exists(BBPaths.override_path(ASSET)), ".bbsrc is gone")
	done()


func test_choose_inside_project_is_shared() -> void:
	_cleanup()
	write_file(ELSEWHERE, "")
	check(not BBPaths.choose_source(ASSET, ProjectSettings.globalize_path(ELSEWHERE)), "inside the project it isn't personal")
	eq(BBPaths.read_override(ASSET), "fixtures/elsewhere.blend", "written to .bbsrc")
	eq(BBPaths.read_local(ASSET), "", "nothing personal")
	_cleanup()
	done()


func test_choose_outside_project_is_personal() -> void:
	_cleanup()
	_make_outside()
	check(BBPaths.choose_source(ASSET, _outside), "outside the project it's personal")
	check(not FileAccess.file_exists(BBPaths.override_path(ASSET)), "nothing shared is written to the project")
	eq(BBPaths.read_local(ASSET), _outside, "personal entry")
	eq(BBPaths.source_for(ASSET), _outside, "Godot uses it")
	eq(BBPaths.tier_for(ASSET), "library", "tier")
	eq(FileAccess.get_file_as_string(BBPaths.LOCAL_DIR + "/.gitignore").strip_edges(), "*", "never committed")
	_cleanup()
	done()


func test_personal_wins_over_shared() -> void:
	_cleanup()
	write_file(SIBLING, "")
	_make_outside()
	BBPaths.choose_source(ASSET, _outside)
	eq(BBPaths.source_for(ASSET), _outside, "personal takes precedence")
	BBPaths.choose_source(ASSET, ProjectSettings.globalize_path(SIBLING))
	eq(BBPaths.read_local(ASSET), "", "a choice inside the project clears the personal one")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "back to the shared one")
	_cleanup()
	done()


func test_missing_personal_source_falls_back() -> void:
	_cleanup()
	write_file(SIBLING, "")
	BBPaths.write_local(ASSET, "/neexistuje/crate.blend")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "a missing personal source is skipped")
	_cleanup()
	done()
