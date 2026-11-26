"""Editing a model in its .blend with context from the scene."""

import json
import os
import shutil
import struct
import time

import bpy

import blenderang.bridge as bridge
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
        tower = bpy.data.objects["Tower"]
        self.assertEqual(tower.get(bridge.P_TIER), "library", "after returning the scene sees the new source")

        # Returning ends the scene context; the source stays linked by the file itself.
        source = os.path.join(harness.ASSETS, "tower.blend")
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
        self.assertIsNone(bridge.edit_session())
        self.assertTrue(bridge._same_file(bridge.file_root(), harness.PROJECT))
        self.assertFalse(os.path.exists(bridge._sessions_path()), "nothing about the file is kept on this machine")
        self.assertIsNone(bpy.data.collections.get(bridge.COLL_CONTEXT))
        self.assertFalse(bpy.ops.bb.return_to_scene.poll())
        glb = os.path.join(harness.ASSETS, "tower.glb")
        before = os.stat(glb).st_mtime_ns
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(glb).st_mtime_ns, before, "reopening keeps export on save")

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

    def test_exporter_path_follows_the_project_on_this_disk(self):
        self.start_edit()
        collection = bpy.data.collections["tower"]
        self.assertEqual(collection[bridge.C_ASSET], "res://fixtures/assets/tower.glb", "shared path in the .blend")
        # The same .blend saved on a disk where the project is elsewhere.
        bridge.gltf_exporter(collection).filepath = "/somewhere/else/fixtures/assets/tower.glb"
        bridge.localize_export_paths(harness.PROJECT)
        self.assertTrue(bridge._same_file(bpy.path.abspath(bridge.gltf_exporter(collection).filepath),
                                          os.path.join(harness.ASSETS, "tower.glb")))
        self.assertTrue(bridge.gltf_exporter(collection).filepath.startswith("//"),
                        "relative to the .blend, no path from this disk in the shared file")

    def test_changed_exporter_path_is_shared_on_save(self):
        self.start_edit()
        collection = bpy.data.collections["tower"]
        moved = os.path.join(harness.ASSETS, "tower_moved.glb")
        self.addCleanup(lambda: os.path.exists(moved) and os.remove(moved))
        bridge.gltf_exporter(collection).filepath = moved
        bpy.ops.wm.save_mainfile()
        self.assertTrue(os.path.isfile(moved), "exported where the exporter points")
        self.assertEqual(collection[bridge.C_ASSET], "res://fixtures/assets/tower_moved.glb")

    def test_auto_save_switch_off_stops_export(self):
        self.start_edit()
        glb = os.path.join(harness.ASSETS, "tower.glb")
        self.assertEqual(bpy.ops.bb.auto_export(enable=False), {"FINISHED"})
        before = os.stat(glb).st_mtime_ns
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        self.assertEqual(os.stat(glb).st_mtime_ns, before, "switched off: saving doesn't export")
        bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
        self.assertFalse(bridge.auto_export(), "the switch is saved in the .blend")
        self.assertEqual(bpy.ops.bb.auto_export(enable=True), {"FINISHED"})
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(glb).st_mtime_ns, before)


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

        self.assertTrue(bridge._sessions_path().startswith(os.path.dirname(harness.PROJECT)),
                        "the edit sessions are in the tests' isolated config, not the user's")
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


class SourceFromGodotTest(BridgeCase):
    """"Open source in Blender" from Godot's FileSystem: the model's .blend without a scene."""

    def open_from_godot(self) -> str:
        from test_build import write_source
        source = write_source("crate.blend", "crate")
        # The Python exactly as Godot passes it to Blender (tests/tools/export_manifests.gd).
        with open(os.path.join(harness.PIPELINE, "source_expr.py"), encoding="utf-8") as handle:
            exec(handle.read(), {})
        return source

    def test_saving_regenerates_asset(self):
        source = self.open_from_godot()
        self.assertTrue(bridge._same_file(bpy.data.filepath, source))
        self.assertIsNone(bridge.edit_session(), "no scene to return to")
        self.assertFalse(os.path.exists(bridge._sessions_path()), "the open request was taken")
        self.assertTrue(bridge._same_file(bridge.file_root(), harness.PROJECT))
        self.assertIsNone(bpy.data.collections.get(bridge.COLL_CONTEXT), "no scene around")
        self.assertFalse(bpy.ops.bb.return_to_scene.poll(), "there is no scene to return to")
        self.assertEqual(bpy.context.view_layer.active_layer_collection.collection.name, "crate")
        collection = bpy.data.collections["crate"]
        self.assertEqual(collection[bridge.C_ASSET], "res://fixtures/assets/crate.glb", "found by name, exporter added")
        self.assertFalse(bridge.gltf_exporter(collection).export_properties.export_apply,
                         "a hand-made source keeps Blender's export defaults")

        glb = os.path.join(harness.ASSETS, "crate.glb")
        before = os.stat(glb).st_mtime_ns
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(glb).st_mtime_ns, before, "saving regenerates the .glb in the project")

    def test_scene_edit_elsewhere_keeps_its_session(self):
        """Two Blender windows: one edits Tower from the scene, the other opens Crate from Godot."""
        self.open_scene()
        bpy.ops.bb.promote_source(name="Tower")
        bpy.ops.bb.edit_source(name="Tower")
        tower = bpy.data.filepath
        self.open_from_godot()
        bpy.ops.wm.open_mainfile(filepath=tower)
        session = bridge.edit_session()
        self.assertIsNotNone(session, "Tower's edit survived")
        self.assertTrue(session["manifest"].endswith("basic.json"))


class SeveralModelsTest(BridgeCase):
    """One .blend with several collections, each exporting its own asset."""

    def write_props(self) -> str:
        path = os.path.join(harness.ASSETS, "props.blend")
        collections = set()
        for name, asset in (("Box", "crate.glb"), ("Spire", "tower.glb"), ("Cutters", "")):
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
            collection = bpy.data.collections.new(name)
            collection.objects.link(bpy.data.objects.new(name + "_body", mesh))
            if asset:
                bridge.set_export_target(collection, os.path.join(harness.ASSETS, asset), harness.PROJECT)
            collections.add(collection)
        bpy.data.libraries.write(path, collections, fake_user=True)
        for collection in collections:
            bpy.data.collections.remove(collection)
        return path

    def test_each_asset_links_its_collection_and_save_exports_all(self):
        scene = self.open_scene()
        source = self.write_props()
        bridge.choose_source(scene, "res://fixtures/assets/crate.glb", source)
        bridge.choose_source(scene, "res://fixtures/assets/tower.glb", source)
        self.assertEqual(bpy.data.objects["Crate"].instance_collection.name, "Box")
        self.assertEqual(bpy.data.objects["Tower"].instance_collection.name, "Spire")

        self.assertEqual(bpy.ops.bb.edit_source(name="Crate"), {"FINISHED"})
        self.assertEqual(bpy.context.view_layer.active_layer_collection.collection.name, "Box")
        self.assertEqual(sorted(c.name for c in bridge.model_collections()), ["Box", "Spire"],
                         "a collection without an exporter is a helper, not a model")
        glbs = [os.path.join(harness.ASSETS, name) for name in ("crate.glb", "tower.glb")]
        before = [os.stat(glb).st_mtime_ns for glb in glbs]
        time.sleep(0.05)
        bpy.ops.wm.save_mainfile()
        for glb, stamp in zip(glbs, before):
            self.assertGreater(os.stat(glb).st_mtime_ns, stamp, glb)


class AutoSaveToGodotTest(BridgeCase):
    """A .blend nobody opened from Godot, exported into the project on save."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = os.path.join(os.path.dirname(harness.PROJECT), "models_library")
        os.makedirs(os.path.join(self.folder, "props"), exist_ok=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.glb = os.path.join(harness.ASSETS, "lamp.glb")
        self.addCleanup(lambda: os.path.exists(self.glb) and os.remove(self.glb))

    def new_lamp(self, name: str = "lamp") -> tuple[str, str]:
        """A fresh .blend with a cube in the models folder; returns (path, Godot project)."""
        scene = self.open_scene()   # opening from Godot makes the project known
        bridge.set_models_folder(scene, self.folder)
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        path = os.path.join(self.folder, "props", name + ".blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        return path, bridge.project_for(path)[0]

    def test_new_file_exports_once_switched_on(self):
        path, root = self.new_lamp()
        self.assertTrue(bridge._same_file(root, harness.PROJECT))
        self.assertEqual(bridge.project_for(path)[1], "res://assets/props/lamp.glb",
                         "project + assets/ + path in the models folder")
        self.assertFalse(os.path.exists(self.glb), "nothing is exported until switched on")
        self.assertEqual(bridge.file_root(), "")

        result = bpy.ops.bb.link_to_godot(auto=True, project=root, target="res://fixtures/assets/lamp.glb")
        self.assertEqual(result, {"FINISHED"})
        collection = bpy.data.collections["lamp"]
        self.assertIn("Cube", collection.objects, "the scene's objects went into a collection named after the file")
        self.assertTrue(bridge.gltf_exporter(collection).export_properties.export_apply)
        self.assertEqual(bridge.godot_status(root, "res://fixtures/assets/lamp.glb"),
                         ("new in Godot, linked to this file", False), "Godot finds lamp.blend by name")
        bpy.ops.wm.save_mainfile()
        self.assertTrue(os.path.isfile(self.glb))
        self.assertEqual(collection[bridge.C_ASSET], "res://fixtures/assets/lamp.glb")
        self.assertFalse(bridge.godot_status(root, "res://fixtures/assets/lamp.glb")[1])

        bpy.ops.wm.open_mainfile(filepath=path)
        self.assertTrue(bridge.auto_export(), "reopening keeps exporting")
        self.assertFalse(os.path.exists(bridge._sessions_path()), "the link is in the file, not on this machine")
        self.assertEqual(bpy.data.collections["lamp"][bridge.C_PROJECT], "BlenderangTests")

    def test_link_without_auto_exports_only_on_demand(self):
        _, root = self.new_lamp()
        result = bpy.ops.bb.link_to_godot(auto=False, project=root, target="res://fixtures/assets/lamp.glb")
        self.assertEqual(result, {"FINISHED"})
        bpy.ops.wm.save_mainfile()
        self.assertFalse(os.path.exists(self.glb), "linked without auto save: saving doesn't export")
        self.assertEqual(bpy.ops.bb.export_now(), {"FINISHED"})
        self.assertTrue(os.path.isfile(self.glb))

    def test_suggested_path_follows_the_models_folder_or_guesses(self):
        path, root = self.new_lamp()
        self.assertEqual(bridge.suggested_asset(root, path), ("res://assets/props/lamp.glb", True))
        self.assertEqual(bridge.suggested_asset(root, path, ""), ("res://assets/lamp.glb", False),
                         "outside the models folder: the mirrored folder + the file's name")

    def test_link_sets_the_models_folder(self):
        _, root = self.new_lamp()
        bridge.store_models_folder(root, "")
        result = bpy.ops.bb.link_to_godot(auto=True, project=root, models=self.folder,
                                          target=os.path.join(harness.ASSETS, "lamp.glb"))
        self.assertEqual(result, {"FINISHED"})
        self.assertTrue(bridge._same_file(bridge.models_folder(root), self.folder),
                        "saved for this project, Godot reads it too")

    def test_replaced_file_without_exporter_is_unlinked(self):
        path, root = self.new_lamp()
        pristine = path + ".orig"
        shutil.copyfile(path, pristine)
        bpy.ops.bb.link_to_godot(auto=True, project=root, target="res://fixtures/assets/lamp.glb")
        bpy.ops.wm.save_mainfile()

        os.replace(pristine, path)   # a teammate's version from before it was linked
        bpy.ops.wm.open_mainfile(filepath=path)
        self.assertEqual(bridge.file_root(), "", "nothing on this machine claims the file is linked")
        result = bpy.ops.bb.link_to_godot(auto=True, project=root, target="res://fixtures/assets/lamp.glb")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(bridge.linked_models()), 1, "linking again sets up the exporter")

    def test_renamed_file_stays_linked(self):
        path, root = self.new_lamp()
        bpy.ops.bb.link_to_godot(auto=True, project=root, target="res://fixtures/assets/lamp.glb")
        bpy.ops.wm.save_mainfile()
        renamed = os.path.join(self.folder, "props", "lamp_old.blend")
        bpy.ops.wm.read_homefile(use_empty=True)
        os.rename(path, renamed)   # in the file manager or with git mv
        before = os.stat(self.glb).st_mtime_ns
        time.sleep(0.05)

        bpy.ops.wm.open_mainfile(filepath=renamed)
        self.assertTrue(bridge._same_file(bridge.file_root(), harness.PROJECT))
        bpy.ops.wm.save_mainfile()
        self.assertGreater(os.stat(self.glb).st_mtime_ns, before, "exports to the same asset")
        text, problem = bridge.godot_status(root, "res://fixtures/assets/lamp.glb")
        self.assertTrue(problem, "Godot looks for lamp.blend by name: " + text)

    def test_save_as_outside_finds_the_project_by_name(self):
        _, root = self.new_lamp()
        other = os.path.join(os.path.dirname(harness.PROJECT), "other_project")
        os.makedirs(other, exist_ok=True)
        self.addCleanup(shutil.rmtree, other, True)
        with open(os.path.join(other, "project.godot"), "w", encoding="utf-8") as handle:
            handle.write('[application]\n\nconfig/name="Other"\n')
        bridge.remember_project(other)
        bpy.ops.bb.link_to_godot(auto=True, project=root, target="res://fixtures/assets/lamp.glb")

        outside = os.path.join(os.path.dirname(harness.PROJECT), "outside_sources", "lamp.blend")
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        bpy.ops.wm.save_as_mainfile(filepath=outside)
        self.assertTrue(os.path.isfile(self.glb), "the exporter path follows the file to its new folder")
        os.remove(self.glb)

        bpy.ops.wm.open_mainfile(filepath=outside)
        self.assertTrue(bridge._same_file(bridge.file_root(), harness.PROJECT),
                        "outside the project and the models folder, the project is found by name")
        bpy.ops.wm.save_mainfile()
        self.assertTrue(os.path.isfile(self.glb))
