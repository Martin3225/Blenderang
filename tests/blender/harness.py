"""Společný základ Blender testů.

Každý test začíná v prázdném Blenderu s nedotčeným manifestem a assety;
cokoli, co test v pracovním projektu vytvoří (.blend zdroje, přegenerované
.glb, značka rozpracované úpravy), se po něm vrátí.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest

import bpy
from mathutils import Vector

PROJECT = ""
ASSETS = ""
PIPELINE = ""
_PRISTINE_ASSETS = ""
_PRISTINE_PIPELINE = ""


def configure(project: str) -> None:
    global PROJECT, ASSETS, PIPELINE, _PRISTINE_ASSETS
    PROJECT = project
    ASSETS = os.path.join(project, "fixtures", "assets")
    PIPELINE = os.path.join(project, ".pipeline")
    _PRISTINE_ASSETS = os.path.join(project, ".pipeline", "pristine_assets")
    if not os.path.isdir(_PRISTINE_ASSETS):
        shutil.copytree(ASSETS, _PRISTINE_ASSETS)
    global _PRISTINE_PIPELINE
    _PRISTINE_PIPELINE = os.path.join(project, ".pipeline_pristine")
    if not os.path.isdir(_PRISTINE_PIPELINE):
        shutil.copytree(PIPELINE, _PRISTINE_PIPELINE, ignore=shutil.ignore_patterns("pristine_assets"))


def godot_to_blender_point(x: float, y: float, z: float) -> Vector:
    """Godot (Y nahoru, -Z dopředu) → Blender (Z nahoru)."""
    return Vector((x, -z, y))


class BridgeCase(unittest.TestCase):
    def setUp(self) -> None:
        self._restore()
        bpy.ops.wm.read_homefile(use_empty=True)

    def tearDown(self) -> None:
        bpy.ops.wm.read_homefile(use_empty=True)
        self._restore()

    def _restore(self) -> None:
        # Manifesty i geometrie kontextu, jak je vyexportoval Godot.
        for name in os.listdir(_PRISTINE_PIPELINE):
            source = os.path.join(_PRISTINE_PIPELINE, name)
            if os.path.isfile(source):
                shutil.copyfile(source, os.path.join(PIPELINE, name))
        marker = os.path.join(PIPELINE, "bb_edit.json")
        if os.path.exists(marker):
            os.remove(marker)
        for name in os.listdir(ASSETS):
            path = os.path.join(ASSETS, name)
            if name.endswith((".blend", ".blend1", ".bbsrc")):
                os.remove(path)
        for name in os.listdir(_PRISTINE_ASSETS):
            shutil.copyfile(os.path.join(_PRISTINE_ASSETS, name), os.path.join(ASSETS, name))

    # -------------------------------------------------------------- pomůcky

    def manifest_path(self, scene: str = "basic") -> str:
        return os.path.join(PIPELINE, scene + ".json")

    def read_manifest(self, scene: str = "basic") -> dict:
        with open(self.manifest_path(scene), encoding="utf-8") as handle:
            return json.load(handle)

    def write_manifest(self, data: dict, scene: str = "basic") -> None:
        with open(self.manifest_path(scene), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent="\t")

    @staticmethod
    def entry(manifest: dict, name: str) -> dict:
        for item in manifest["nodes"]:
            if item.get("name") == name:
                return item
        raise KeyError(name)

    def open_scene(self, scene: str = "basic") -> bpy.types.Scene:
        result = bpy.ops.bb.open_from_godot(filepath=self.manifest_path(scene))
        self.assertEqual(result, {"FINISHED"})
        return bpy.context.scene

    def assertVectorAlmostEqual(self, actual, expected, places: int = 3, msg: str = "") -> None:
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=places, msg="%s: %s != %s" % (msg, tuple(actual), tuple(expected)))

    @staticmethod
    def collection_objects(name: str) -> list[bpy.types.Object]:
        collection = bpy.data.collections.get(name)
        return list(collection.all_objects) if collection else []
