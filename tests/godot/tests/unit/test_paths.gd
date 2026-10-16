extends "res://tests/bb_test.gd"

## Hledání zdrojového .blend.

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
	eq(BBPaths.source_for(ASSET), "", "zdroj")
	eq(BBPaths.tier_for(ASSET), "none", "tier")
	eq(BBPaths.expected_source_for(ASSET), "fixtures/assets/crate.blend", "očekávaná cesta")
	done()


func test_sibling_blend_is_found() -> void:
	_cleanup()
	write_file(SIBLING, "")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "zdroj vedle assetu")
	eq(BBPaths.tier_for(ASSET), "library", "tier")
	_cleanup()
	done()


func test_override_wins_over_sibling() -> void:
	_cleanup()
	write_file(SIBLING, "")
	write_file(ELSEWHERE, "")
	check(BBPaths.write_override(ASSET, ELSEWHERE), "zápis .bbsrc")
	eq(BBPaths.source_for(ASSET), "fixtures/elsewhere.blend", "přesná cesta má přednost")
	_cleanup()
	done()


func test_override_to_missing_file_is_none() -> void:
	_cleanup()
	write_file(SIBLING, "")
	BBPaths.write_override(ASSET, ELSEWHERE)
	eq(BBPaths.source_for(ASSET), "", "chybějící vybraný zdroj se nenahrazuje konvencí")
	_cleanup()
	done()


func test_empty_override_removes_marker() -> void:
	_cleanup()
	BBPaths.write_override(ASSET, ELSEWHERE)
	check(BBPaths.write_override(ASSET, ""), "smazání")
	check(not FileAccess.file_exists(BBPaths.override_path(ASSET)), ".bbsrc je pryč")
	done()


func test_choose_inside_project_is_shared() -> void:
	_cleanup()
	write_file(ELSEWHERE, "")
	check(not BBPaths.choose_source(ASSET, ProjectSettings.globalize_path(ELSEWHERE)), "v projektu není osobní")
	eq(BBPaths.read_override(ASSET), "fixtures/elsewhere.blend", "zapsáno do .bbsrc")
	eq(BBPaths.read_local(ASSET), "", "nic osobního")
	_cleanup()
	done()


func test_choose_outside_project_is_personal() -> void:
	_cleanup()
	_make_outside()
	check(BBPaths.choose_source(ASSET, _outside), "mimo projekt je osobní")
	check(not FileAccess.file_exists(BBPaths.override_path(ASSET)), "do projektu se nic sdíleného nezapíše")
	eq(BBPaths.read_local(ASSET), _outside, "osobní záznam")
	eq(BBPaths.source_for(ASSET), _outside, "Godot ho použije")
	eq(BBPaths.tier_for(ASSET), "library", "tier")
	eq(FileAccess.get_file_as_string(BBPaths.LOCAL_DIR + "/.gitignore").strip_edges(), "*", "nikdy se necommitne")
	_cleanup()
	done()


func test_personal_wins_over_shared() -> void:
	_cleanup()
	write_file(SIBLING, "")
	_make_outside()
	BBPaths.choose_source(ASSET, _outside)
	eq(BBPaths.source_for(ASSET), _outside, "osobní má přednost")
	BBPaths.choose_source(ASSET, ProjectSettings.globalize_path(SIBLING))
	eq(BBPaths.read_local(ASSET), "", "výběr v projektu osobní zruší")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "zpět ke sdílenému")
	_cleanup()
	done()


func test_missing_personal_source_falls_back() -> void:
	_cleanup()
	write_file(SIBLING, "")
	BBPaths.write_local(ASSET, "/neexistuje/crate.blend")
	eq(BBPaths.source_for(ASSET), "fixtures/assets/crate.blend", "chybějící osobní zdroj se přeskočí")
	_cleanup()
	done()
