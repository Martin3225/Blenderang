#!/usr/bin/env python3
"""Builds the release zips into ``dist/``.

    python tools/build_release.py              # version from the sources
    python tools/build_release.py --tag v0.2.0 # also check it matches the git tag

* ``blenderang-blender-<version>.zip``: the Blender extension, files at the zip
  root (``Edit ▸ Preferences ▸ Get Extensions ▸ Install from Disk…``).
* ``blenderang-godot-<version>.zip``: ``addons/blenderang/``, to unpack into a
  Godot project.

The version in ``addons/blenderang/plugin.cfg`` and
``tools/blenderang/blender_manifest.toml`` must be the same.
"""

from __future__ import annotations

import argparse
import configparser
import sys
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GODOT_ADDON = REPO / "addons" / "blenderang"
BLENDER_EXTENSION = REPO / "tools" / "blenderang"
DIST = REPO / "dist"


def godot_version() -> str:
    config = configparser.ConfigParser()
    config.read(GODOT_ADDON / "plugin.cfg", encoding="utf-8")
    return config["plugin"]["version"].strip('"')


def blender_version() -> str:
    with open(BLENDER_EXTENSION / "blender_manifest.toml", "rb") as handle:
        return tomllib.load(handle)["version"]


def files_of(folder: Path) -> list[Path]:
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def write_zip(target: Path, folder: Path, prefix: str) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files_of(folder):
            bundle.write(path, prefix + path.relative_to(folder).as_posix())
    print(target.relative_to(REPO))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="git tag the release is for, e.g. v0.2.0")
    options = parser.parse_args()

    version = godot_version()
    if blender_version() != version:
        sys.exit("version mismatch: plugin.cfg %s, blender_manifest.toml %s" % (version, blender_version()))
    if options.tag is not None and options.tag != "v" + version:
        sys.exit("tag %s doesn't match version %s" % (options.tag, version))

    DIST.mkdir(exist_ok=True)
    write_zip(DIST / ("blenderang-blender-%s.zip" % version), BLENDER_EXTENSION, "")
    write_zip(DIST / ("blenderang-godot-%s.zip" % version), GODOT_ADDON, "addons/blenderang/")


if __name__ == "__main__":
    main()
