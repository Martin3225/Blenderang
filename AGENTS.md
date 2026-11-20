# AGENTS.md

## Release

1. Bump the version in both `addons/blenderang/plugin.cfg` and
   `tools/blenderang/blender_manifest.toml` (they must match).
2. `python tests/run_tests.py` must pass; CI doesn't run tests (needs Godot + Blender).
3. Commit, then `git tag vX.Y.Z` and push branch + tag to **both** remotes:
   `github` (public, triggers `.github/workflows/release.yml`) and `origin` (private Gitea mirror).
4. The workflow builds `blenderang-godot-X.Y.Z.zip` and `blenderang-blender-X.Y.Z.zip`
   (`tools/build_release.py`) and attaches them to the GitHub release; it fails on a
   tag/version mismatch. v0.1.0 predates this: its Blender zip is `blenderang-0.1.0.zip`.
5. Godot Asset Library is not automated: it serves the repo archive (trimmed by
   `.gitattributes` export-ignore); point the listing at the new tag by hand.

## Invariants

- Source `.blend` resolution is implemented twice and must stay identical:
  `addons/blenderang/bb_paths.gd` (Godot) and `tools/blenderang/bridge.py` (Blender).
  Change both and add tests on both sides (`tests/godot/tests/unit/test_paths.gd`,
  `tests/blender/test_build.py`).
- `.pipeline/local/` (`sources.json`, `settings.json`) is personal, gitignored, and read by both sides.
- Code, comments, UI and docs are in English.
