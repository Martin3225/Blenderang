"""Making a source .blend from a preview (.glb → .blend)."""

import os

import bpy

import blenderang.bridge as bridge
import harness
from harness import BridgeCase


class PromoteTest(BridgeCase):
    def promote(self, name: str) -> dict:
        return bpy.ops.bb.promote_source(name=name)

    def test_creates_source_next_to_asset(self):
        self.open_scene()
        self.assertEqual(self.promote("Tower"), {"FINISHED"})
        source = os.path.join(harness.ASSETS, "tower.blend")
        self.assertTrue(os.path.isfile(source))
        tower = bpy.data.objects["Tower"]
        self.assertEqual(tower.get(bridge.P_TIER), "library")
        self.assertEqual(tower.get(bridge.P_SRC_BLEND), "fixtures/assets/tower.blend")
        self.assertIsNotNone(tower.instance_collection.library)

    def test_all_instances_of_asset_are_relinked(self):
        self.open_scene()
        self.promote("Crate")
        for name in ("Crate", "InRotated", "Detached"):
            obj = bpy.data.objects[name]
            self.assertIsNotNone(obj.instance_collection, "%s lost its geometry" % name)
            self.assertIsNotNone(obj.instance_collection.library, name)
            self.assertEqual(obj.get(bridge.P_TIER), "library", name)

    def test_rig_source_has_no_bone_shape_objects(self):
        self.open_scene()
        self.promote("Character")
        collection = bpy.data.objects["Character"].instance_collection
        shapes = {
            bone.custom_shape
            for obj in collection.all_objects if obj.type == "ARMATURE"
            for bone in obj.pose.bones if bone.custom_shape
        }
        self.assertFalse(shapes & set(collection.all_objects))

    def test_existing_source_is_never_overwritten(self):
        path = os.path.join(harness.ASSETS, "tower.blend")
        with open(path, "wb") as handle:
            handle.write(b"puvodni")
        self.open_scene()
        self.assertEqual(bpy.data.objects["Tower"].get(bridge.P_TIER), "none", "broken source → preview")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.promote("Tower")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"puvodni")

    def test_godot_sees_new_source_after_send(self):
        self.open_scene()
        self.promote("Tower")
        bridge.export(bpy.context.scene)
        # The manifest carries the tier from Blender only as information; Godot works
        # it out itself on the next export from the file next to the asset.
        self.assertTrue(os.path.isfile(os.path.join(harness.ASSETS, "tower.blend")))
