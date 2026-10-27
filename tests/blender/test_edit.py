"""Editing a model in its .blend with context from the scene."""

import json
import os
import shutil
import struct
import time

import bpy

import blender_bridge.bridge as bridge
import harness
from harness import BridgeCase, godot_to_blender_point


class EditTest(BridgeCase):
    def start_edit(self, name: str = "Tower") -> None:
        self.open_scene()
        self.assertEqual(bpy.ops.bb.promote_source(name=name), {"FINISHED"})
        self.assertEqual(bpy.ops.bb.edit_source(name=name), {"FINISHED"})

    def test_pending_moves_are_sent_before_leaving_scene(self):
        self.open_scene()
        bpy.ops.bb.promote_source(name="Tower")
        bpy.data.objects["Tower"].location.x += 2
        bpy.ops.bb.edit_source(name="Tower")
        self.assertAlmostEqual(self.entry(self.read_manifest(), "Tower")["xform"][9], -2.0, places=4)

    def test_opens_source_in_edit_mode(self):
        self.start_edit()
        self.assertTrue(bridge._same_file(bpy.data.filepath, os.path.join(harness.ASSETS, "tower.blend")))
        session = bridge.edit_session()
        self.assertIsNotNone(session)
        self.assertIn("tower", bpy.context.scene.collection.children, "the model is in the source's scene")

    def test_context_surrounds_model_in_its_local_space(self):
        self.start_edit()
        context = bpy.data.collections.get(bridge.COLL_CONTEXT)
        self.assertIsNotNone(context)
        names = {o.name for o in context.all_objects}
        for name in ("Building", "Player", "Crate", "Barrel"):
            self.assertIn(name, names)
        # In Godot, Tower stands at (-4, 0, 1), Building at (-10, 0, -10).
        offset = godot_to_blender_point(-10, 0, -10) - godot_to_blender_point(-4, 0, 1)
        self.assertVectorAlmostEqual(bpy.data.objects["Building"].matrix_world.translation, offset)
        building = bpy.data.objects["Building"]
        self.assertTrue(any(c.type == "MESH" for c in building.children_recursive), "context has real geometry")

    def test_context_is_locked(self):
        self.start_edit()
        for obj in bpy.data.collections[bridge.COLL_CONTEXT].all_objects:
            self.assertEqual(tuple(obj.lock_location), (True, True, True), obj.name)

    def test_other_instances_of_same_asset_show_live_edits(self):
        self.start_edit("Crate")
        edited = bpy.data.collections["crate"]
        for name in ("InRotated", "Detached"):
            self.assertIs(bpy.data.objects[name].instance_collection, edited, name)

    def test_save_regenerates_glb_and_never_stores_context(self):
        self.start_edit()
        glb = os.path.join(harness.ASSETS, "tower.glb")
        before = os.stat(glb).st_mtime_ns
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(glb).st_mtime_ns, before, ".glb was not regenerated")
        self.assertIsNotNone(bpy.data.collections.get(bridge.COLL_CONTEXT), "context came back after saving")

        copy = os.path.join(harness.PIPELINE, "saved_copy.blend")
        shutil.copyfile(bpy.data.filepath, copy)
        try:
            with bpy.data.libraries.load(copy) as (data_from, _):
                collections = set(data_from.collections)
                objects = set(data_from.objects)
                meshes = set(data_from.meshes)
        finally:
            os.remove(copy)
        self.assertNotIn(bridge.COLL_CONTEXT, collections)
        self.assertFalse({"Building", "Player", "Godot", "Crate"} & objects, objects)
        self.assertFalse({m for m in meshes if "crate" in m.lower()}, "previews of other models were saved")

    def test_return_to_scene(self):
        self.start_edit()
        self.assertEqual(bpy.ops.bb.return_to_scene(), {"FINISHED"})
        self.assertEqual(bpy.data.filepath, "")
        self.assertIsNone(bridge.edit_session())
        self.assertFalse(os.path.exists(os.path.join(harness.PIPELINE, "bb_edit.json")))
        tower = bpy.data.objects["Tower"]
        self.assertEqual(tower.get(bridge.P_TIER), "library", "after returning the scene sees the new source")

    def test_edit_requires_source(self):
        self.open_scene()
        with self.assertRaisesRegex(RuntimeError, "has no source"):
            bpy.ops.bb.edit_source(name="Tower")
        self.assertEqual(bpy.data.filepath, "", "the scene stayed open")

    def test_exporter_points_to_asset(self):
        self.start_edit()
        exporters = bpy.data.collections["tower"].exporters
        self.assertEqual(len(exporters), 1)
        self.assertTrue(bridge._same_file(bpy.path.abspath(exporters[0].export_properties.filepath),
                                          os.path.join(harness.ASSETS, "tower.glb")))

    def test_new_source_applies_modifiers_by_default(self):
        self.start_edit()
        props = bridge.gltf_exporter(bpy.data.collections["tower"]).export_properties
        self.assertTrue(props.export_apply)
        self.assertEqual(props.export_format, "GLB")

    def test_apply_modifiers_toggle_changes_exported_geometry(self):
        self.start_edit()
        collection = bpy.data.collections["tower"]
        mesh = next(o for o in collection.all_objects if o.type == "MESH")
        array = mesh.modifiers.new("Array", "ARRAY")
        array.count = 3
        props = bridge.gltf_exporter(collection).export_properties
        glb = os.path.join(harness.ASSETS, "tower.glb")

        props.export_apply = False
        bpy.ops.wm.save_mainfile()
        plain = glb_vertex_count(glb)
        props.export_apply = True
        bpy.ops.wm.save_mainfile()
        self.assertGreater(glb_vertex_count(glb), plain, "the array from the modifier is missing in the .glb")

    def test_older_source_gets_defaults_once(self):
        self.start_edit()
        collection = bpy.data.collections["tower"]
        del collection[bridge.C_EXPORT_SET]
        bridge.gltf_exporter(collection).export_properties.export_apply = False
        bpy.ops.wm.save_mainfile()
        bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
        collection = bpy.data.collections["tower"]
        self.assertTrue(bridge.gltf_exporter(collection).export_properties.export_apply,
                        "an older source without settings got the defaults")

        bridge.gltf_exporter(collection).export_properties.export_apply = False
        bpy.ops.wm.save_mainfile()
        bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
        self.assertFalse(bridge.gltf_exporter(bpy.data.collections["tower"]).export_properties.export_apply,
                         "a source's own settings are not overwritten")


def glb_vertex_count(path: str) -> int:
    with open(path, "rb") as handle:
        handle.seek(12)
        length, _ = struct.unpack("<II", handle.read(8))
        gltf = json.loads(handle.read(length))
    return sum(
        gltf["accessors"][primitive["attributes"]["POSITION"]]["count"]
        for mesh in gltf["meshes"] for primitive in mesh["primitives"]
    )


class PersonalSourceEditTest(BridgeCase):
    """Editing a model whose source is outside the project."""

    def test_edit_personal_source(self):
        from test_build import write_source
        outside = os.path.join(os.path.dirname(harness.PROJECT), "outside_sources", "tower_master.blend")
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        write_source(os.path.relpath(outside, harness.ASSETS), "tower")
        self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
        scene = self.open_scene()
        bridge.choose_source(scene, "res://fixtures/assets/tower.glb", outside)

        self.assertTrue(bridge._pointer_path().startswith(os.path.dirname(harness.PROJECT)),
                        "the edit pointer is in the tests' isolated config, not the user's")
        self.assertEqual(bpy.ops.bb.edit_source(name="Tower"), {"FINISHED"})
        self.assertTrue(bridge._same_file(bpy.data.filepath, outside))
        self.assertIsNotNone(bridge.edit_session(), "the edit is found outside the project too")
        self.assertIsNotNone(bpy.data.collections.get(bridge.COLL_CONTEXT))

        glb = os.path.join(harness.ASSETS, "tower.glb")
        before = os.stat(glb).st_mtime_ns
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(glb).st_mtime_ns, before, "saving regenerates the .glb in the project")

        self.assertEqual(bpy.ops.bb.return_to_scene(), {"FINISHED"})
        self.assertIsNone(bridge.edit_session())
        self.assertEqual(bpy.data.objects["Tower"].get(bridge.P_SRC_BLEND), outside)
