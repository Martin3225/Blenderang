extends "res://tests/bb_test.gd"

## Finding the source .blend.

const ASSET: String = "res://fixtures/assets/crate.glb"
const SIBLING: String = "res://fixtures/assets/crate.blend"
const ELSEWHERE: String = "res://fixtures/elsewhere.blend"
const MOVED: String = "res://fixtures/moved/crate.glb"
const RENAMED: String = "res://fixtures/assets/box.glb"


var _outside: String = ProjectSettings.globalize_path("res://").path_join("../outside_sources/crate_master.blend").simplify_path()
var _library: String = ProjectSettings.globalize_path("res://").path_join("../models_library").simplify_path()


func _cleanup() -> void:
	remove_file(SIBLING)
	remove_file(ELSEWHERE)
	for asset: String in [ASSET, RENAMED]:
		remove_file(BBPaths.override_path(asset))
	remove_file(BBPaths.LOCAL_SOURCES)
	remove_file(BBPaths.LOCAL_SETTINGS)
	if FileAccess.file_exists(_outside):
		DirAccess.remove_absolute(_outside)
	_remove_tree(_library)
	for folder: String in ["res://fixtures/moved", "res://fixtures/mv_a", "res://fixtures/mv_b"]:
		_remove_tree(ProjectSettings.globalize_path(folder))
	BBPaths.forget_models_index()
	# A test that crashed mid-way must not leave its mirror setting to the next one.
	ProjectSettings.set_setting(BBPaths.SETTING_MODELS_MIRROR, null)


func _remove_tree(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path):
		return
	var hidden: DirAccess = DirAccess.open(path)
	hidden.include_hidden = true
	for name: String in hidden.get_directories():
		_remove_tree(path.path_join(name))
	for name: String in hidden.get_files():
		DirAccess.remove_absolute(path.path_join(name))
	DirAccess.remove_absolute(path)


## An empty file in the models folder; returns its absolute path.
func _library_file(relative: String) -> String:
	var path: String = _library.path_join(relative)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	FileAccess.open(path, FileAccess.WRITE).close()
	return path


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


func test_models_folder_found_by_name() -> void:
	_cleanup()
	_library_file("props/Crate.blend")
	_library_file(".git/crate.blend")
	eq(BBPaths.source_for(ASSET), "", "without a folder set nothing is searched")
	check(BBPaths.set_models_folder(_library), "setting the folder")
	eq(BBPaths.models_folder(), _library, "stored only for you")
	check(FileAccess.get_file_as_string(BBPaths.LOCAL_SETTINGS).contains(_library), "in the personal settings")
	eq(BBPaths.source_for(ASSET), "models://props/Crate.blend", "found at any depth, any case; .git skipped")
	eq(BBPaths.absolute_source("models://props/Crate.blend"), _library.path_join("props/Crate.blend"), "absolute path")
	eq(BBPaths.tier_for(ASSET), "library", "tier")
	_cleanup()
	done()


func test_sibling_wins_over_models_folder() -> void:
	_cleanup()
	_library_file("crate.blend")
	write_file(SIBLING, "")
	BBPaths.set_models_folder(_library)
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "next to the asset first")
	_cleanup()
	done()


func test_models_folder_mirrored_path_breaks_ties() -> void:
	_cleanup()
	_library_file("a/crate.blend")
	_library_file("fixtures/assets/crate.blend")
	_library_file("z/crate.blend")
	BBPaths.set_models_folder(_library)
	eq(BBPaths.source_for(ASSET), "models://fixtures/assets/crate.blend", "the asset's own path wins")
	DirAccess.remove_absolute(_library.path_join("fixtures/assets/crate.blend"))
	BBPaths.forget_models_index()
	eq(BBPaths.source_for(ASSET), "models://a/crate.blend", "otherwise the first alphabetically, same as Blender")
	_cleanup()
	done()


func test_models_folder_mirrors_a_project_folder() -> void:
	_cleanup()
	_library_file("assets/crate.blend")
	_library_file("a/crate.blend")
	BBPaths.set_models_folder(_library)
	eq(BBPaths.models_relative("res://assets/levels/castle.glb"), "levels/castle.blend", "by default assets/ is mirrored")
	eq(BBPaths.models_relative(ASSET), "fixtures/assets/crate.blend", "an asset outside it keeps its whole path")
	ProjectSettings.set_setting(BBPaths.SETTING_MODELS_MIRROR, "/fixtures/")
	BBPaths.forget_models_index()
	eq(BBPaths.source_for(ASSET), "models://assets/crate.blend", "the mirrored path wins, same as Blender")
	ProjectSettings.set_setting(BBPaths.SETTING_MODELS_MIRROR, "")
	eq(BBPaths.models_relative(ASSET), "fixtures/assets/crate.blend", "empty: nothing is stripped")
	ProjectSettings.set_setting(BBPaths.SETTING_MODELS_MIRROR, null)
	_cleanup()
	done()


func test_choose_in_models_folder_is_shared_relative() -> void:
	_cleanup()
	var picked: String = _library_file("props/crate_v2.blend")
	BBPaths.set_models_folder(_library)
	check(not BBPaths.choose_source(ASSET, picked), "inside the models folder it isn't personal")
	eq(BBPaths.read_override(ASSET), "models://props/crate_v2.blend", "relative to the folder in .bbsrc")
	eq(BBPaths.read_local(ASSET), "", "nothing personal")
	eq(BBPaths.source_for(ASSET), "models://props/crate_v2.blend", "Godot uses it")
	BBPaths.set_models_folder("")
	eq(BBPaths.source_for(ASSET), "", "without the folder set the shared path doesn't resolve")
	_cleanup()
	done()


func test_moved_asset_takes_its_bbsrc_along() -> void:
	_cleanup()
	write_file(ELSEWHERE, "")
	BBPaths.write_override(ASSET, ELSEWHERE)
	BBPaths.follow_move(ASSET, RENAMED)
	check(not FileAccess.file_exists(BBPaths.override_path(ASSET)), "nothing left at the old place")
	eq(BBPaths.source_for(RENAMED), "fixtures/elsewhere.blend", "the renamed asset keeps its source")
	_cleanup()
	done()


func test_moved_asset_points_to_the_blend_left_behind() -> void:
	_cleanup()
	write_file(SIBLING, "")
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(MOVED.get_base_dir()))
	BBPaths.follow_move(ASSET, MOVED)
	eq(BBPaths.read_override(MOVED), "fixtures/assets/crate.blend", "the dock moves only the .glb")
	eq(BBPaths.source_for(MOVED), "fixtures/assets/crate.blend", "source")
	_cleanup()
	done()


func test_moved_asset_keeps_its_source_in_the_models_folder() -> void:
	_cleanup()
	_library_file("props/crate.blend")
	BBPaths.set_models_folder(_library)
	BBPaths.follow_move(ASSET, MOVED)
	check(not FileAccess.file_exists(BBPaths.override_path(MOVED)), "same name: still found by name, nothing to write")
	BBPaths.follow_move(ASSET, RENAMED)
	eq(BBPaths.read_override(RENAMED), "models://props/crate.blend", "renamed: no longer found by name")
	eq(BBPaths.source_for(RENAMED), "models://props/crate.blend", "source")
	_cleanup()
	done()


func test_moved_folder_moves_the_project_path_in_bbsrc() -> void:
	_cleanup()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://fixtures/mv_a/src"))
	write_file("res://fixtures/mv_a/src/x_master.blend", "")
	BBPaths.write_override("res://fixtures/mv_a/x.glb", "fixtures/mv_a/src/x_master.blend")
	# What the dock does with a folder: everything in it moves on disk, then files_moved per asset.
	DirAccess.rename_absolute(ProjectSettings.globalize_path("res://fixtures/mv_a"), ProjectSettings.globalize_path("res://fixtures/mv_b"))
	BBPaths.follow_move("res://fixtures/mv_a/x.glb", "res://fixtures/mv_b/x.glb")
	eq(BBPaths.read_override("res://fixtures/mv_b/x.glb"), "fixtures/mv_b/src/x_master.blend", "moved along with the folder")
	eq(BBPaths.source_for("res://fixtures/mv_b/x.glb"), "fixtures/mv_b/src/x_master.blend", "source")
	_cleanup()
	done()


func test_moved_asset_keeps_the_personal_source() -> void:
	_cleanup()
	_make_outside()
	BBPaths.choose_source(ASSET, _outside)
	BBPaths.follow_move(ASSET, RENAMED)
	eq(BBPaths.read_local(ASSET), "", "the old entry is gone")
	eq(BBPaths.source_for(RENAMED), _outside, "only for you, under the new path")
	_cleanup()
	done()
