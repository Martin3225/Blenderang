extends "res://tests/bb_test.gd"

## Hledání zdrojového .blend.

const ASSET: String = "res://fixtures/assets/crate.glb"
const SIBLING: String = "res://fixtures/assets/crate.blend"
const ELSEWHERE: String = "res://fixtures/elsewhere.blend"


func _cleanup() -> void:
	remove_file(SIBLING)
	remove_file(ELSEWHERE)
	remove_file(BBPaths.override_path(ASSET))


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
