"""Building the scene in Blender from the manifest (Godot → Blender)."""

import base64
import math
import os
import re
import shutil

import bpy

import blenderang
import blenderang.bridge as bridge
from harness import ASSETS, BridgeCase, godot_to_blender_point
import harness

MODELS = ("Barrel", "Character", "Crate", "Detached", "Helmet", "InRotated", "Tower")


def write_source(asset: str, collection_name: str) -> str:
    """A source .blend with one collection, as an artist would make it."""
    mesh = bpy.data.meshes.new(collection_name + "_src")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    collection = bpy.data.collections.new(collection_name)
    collection.objects.link(bpy.data.objects.new(collection_name + "_body", mesh))
    path = os.path.join(harness.ASSETS, asset)
    bpy.data.libraries.write(path, {collection}, fake_user=True)
    bpy.data.collections.remove(collection)
    return path


class BuildSceneTest(BridgeCase):
    def test_scene_is_named_and_never_saved(self):
        scene = self.open_scene()
        self.assertEqual(scene.name, "basic")
        self.assertEqual(bpy.data.filepath, "")

    def test_models_are_in_layout(self):
        self.open_scene()
        names = sorted(o.name for o in bpy.data.collections[bridge.COLL_LAYOUT].objects)
        self.assertEqual(names, list(MODELS))

    def test_models_at_godot_world_positions(self):
        self.open_scene()
        expected = {
            "Crate": (2, 0, 3),
            "InRotated": (10, 2, -2),      # under a rotated and scaled parent
            "Detached": (20, 0, 20),       # top_level
            "Character": (5, 0, -2),
        }
        for name, godot in expected.items():
            self.assertVectorAlmostEqual(bpy.data.objects[name].matrix_world.translation,
                                         godot_to_blender_point(*godot), msg=name)

    def test_rotation_about_up_axis(self):
        self.open_scene()
        self.assertAlmostEqual(bpy.data.objects["Crate"].matrix_world.to_euler().z, math.radians(30), places=4)

    def test_every_model_is_visible_exactly_once(self):
        scene = self.open_scene()
        scene_objects = set(scene.objects)
        for name in MODELS:
            source = bpy.data.objects[name].instance_collection
            self.assertIsNotNone(source, "%s has no geometry" % name)
            meshes = [o for o in source.all_objects if o.type == "MESH"]
            self.assertTrue(meshes, "%s: preview without a mesh" % name)
            leaked = scene_objects & set(source.all_objects)
            self.assertFalse(leaked, "%s: the preview's source is also in the scene (at the origin): %s" % (name, leaked))

    def test_no_stray_objects_outside_bridge_collections(self):
        scene = self.open_scene()
        allowed = {bridge.COLL_LAYOUT, bridge.COLL_LOCKED}
        for obj in scene.objects:
            owners = {c.name for c in obj.users_collection}
            self.assertTrue(owners & allowed, "%s is outside the bridge collections: %s" % (obj.name, owners))

    def test_bone_shape_helpers_stay_out_of_model(self):
        self.open_scene()
        source = bpy.data.objects["Character"].instance_collection
        shapes = {
            bone.custom_shape
            for obj in source.all_objects if obj.type == "ARMATURE"
            for bone in obj.pose.bones if bone.custom_shape
        }
        self.assertTrue(any(o.type == "ARMATURE" for o in source.all_objects), "rig without an armature")
        self.assertFalse(shapes & set(source.all_objects), "bone shapes are drawn as part of the model")

    def test_fbx_asset_has_preview(self):
        self.open_scene()
        source = bpy.data.objects["Barrel"].instance_collection
        self.assertTrue(any(o.type == "MESH" for o in source.all_objects))

    def test_context_has_real_godot_geometry(self):
        self.open_scene()
        locked = self.collection_objects(bridge.COLL_LOCKED)
        names = {o.name for o in locked}
        for name in ("Player", "Building", "Spawn", "Sun", "Sphere"):
            self.assertIn(name, names)
        building = bpy.data.objects["Building"]
        self.assertTrue(any(c.type == "MESH" for c in building.children_recursive), "Building without a mesh")
        self.assertVectorAlmostEqual(building.matrix_world.translation, godot_to_blender_point(-10, 0, -10))

    def test_context_is_selectable_but_locked(self):
        self.open_scene()
        self.assertFalse(bpy.data.collections[bridge.COLL_LOCKED].hide_select)
        for obj in self.collection_objects(bridge.COLL_LOCKED):
            self.assertFalse(obj.hide_select, obj.name)
            self.assertEqual(tuple(obj.lock_location), (True, True, True), obj.name)
            self.assertEqual(tuple(obj.lock_rotation), (True, True, True), obj.name)
            self.assertEqual(tuple(obj.lock_scale), (True, True, True), obj.name)

    def test_context_falls_back_to_boxes_without_glb(self):
        manifest = self.read_manifest()
        del manifest["context_glb"]
        self.write_manifest(manifest)
        self.open_scene()
        building = bpy.data.objects["Building"]
        self.assertEqual(building.type, "MESH")
        self.assertEqual(len(building.data.vertices), 8)
        self.assertEqual(tuple(building.lock_location), (True, True, True))

    def test_library_source_is_linked_for_all_instances(self):
        source = write_source("crate.blend", "crate")
        manifest = self.read_manifest()
        for item in manifest["nodes"]:
            if item.get("src", "").endswith("crate.glb"):
                item["tier"] = "library"
                item["src_blend"] = "fixtures/assets/crate.blend"
        self.write_manifest(manifest)
        bpy.ops.wm.read_homefile(use_empty=True)
        self.open_scene()
        linked = {bpy.data.objects[n].instance_collection for n in ("Crate", "InRotated", "Detached")}
        self.assertEqual(len(linked), 1, "all instances share one linked collection")
        collection = linked.pop()
        self.assertIsNotNone(collection.library)
        self.assertTrue(bridge._same_file(bpy.path.abspath(collection.library.filepath), source))
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_TIER), "library")

    def test_declared_source_that_is_missing_falls_back_to_preview(self):
        manifest = self.read_manifest()
        crate = self.entry(manifest, "Crate")
        crate["tier"] = "library"
        crate["src_blend"] = "fixtures/assets/neexistuje.blend"
        self.write_manifest(manifest)
        self.open_scene()
        obj = bpy.data.objects["Crate"]
        self.assertEqual(obj.get(bridge.P_TIER), "none")
        self.assertIsNotNone(obj.instance_collection)

    def test_terrain_is_real_mesh_in_world_space(self):
        if not os.path.exists(self.manifest_path("terrain")):
            self.skipTest("Terrain3D is not installed")
        self.open_scene("terrain")
        meshes = [o for o in self.collection_objects(bridge.COLL_LOCKED) if o.type == "MESH"]
        self.assertEqual([o.name for o in meshes], ["TerrainMesh"], "only the terrain, no internal Terrain3D meshes")
        terrain = meshes[0]
        self.assertGreater(len(terrain.data.vertices), 100)
        heights = [(terrain.matrix_world @ v.co).z for v in terrain.data.vertices]
        self.assertAlmostEqual(max(heights), 20.0, delta=1.0)
        self.assertVectorAlmostEqual(bpy.data.objects["CrateOnHill"].matrix_world.translation,
                                     godot_to_blender_point(128, 20, 128))

    def test_reload_rebuilds_from_manifest(self):
        self.open_scene()
        bpy.data.objects["Crate"].location.x += 50
        self.assertEqual(bpy.ops.bb.rebuild(), {"FINISHED"})
        self.assertVectorAlmostEqual(bpy.data.objects["Crate"].matrix_world.translation,
                                     godot_to_blender_point(2, 0, 3))

    def test_panel_lists_all_models(self):
        scene = self.open_scene()
        self.assertEqual([o.name for o in bridge.scene_models(scene)], list(MODELS))


class ResilienceTest(BridgeCase):
    """One broken file must not crash building the whole scene."""

    def test_corrupt_context_falls_back_to_boxes(self):
        manifest = self.read_manifest()
        with open(os.path.join(harness.PROJECT, manifest["context_glb"]), "wb") as handle:
            handle.write(b"glTF\x02\x00\x00\x00\x10\x01\x00\x00")   # like an empty export from the editor
        scene = self.open_scene()
        self.assertTrue(scene.get(bridge.S_MANIFEST), "the scene finished building")
        self.assertEqual(bpy.data.objects["Building"].type, "MESH")
        self.assertEqual(len(bpy.data.objects["Building"].data.vertices), 8)
        self.assertTrue(any("context" in w for w in scene[bridge.S_WARNINGS]), list(scene[bridge.S_WARNINGS]))
        self.assertFalse([o for o in scene.objects if not o.users_collection or
                          not {c.name for c in o.users_collection} & {bridge.COLL_LAYOUT, bridge.COLL_LOCKED}],
                         "nothing was left half-done after a failed import")

    def test_corrupt_asset_does_not_break_other_models(self):
        with open(os.path.join(harness.ASSETS, "tower.glb"), "wb") as handle:
            handle.write(b"not a glb")
        scene = self.open_scene()
        self.assertTrue(scene.get(bridge.S_MANIFEST))
        self.assertIsNone(bpy.data.objects["Tower"].instance_collection, "a broken asset stays an empty axis")
        self.assertIsNotNone(bpy.data.objects["Crate"].instance_collection, "the other models are fine")
        self.assertTrue(any("Tower" in w for w in scene[bridge.S_WARNINGS]), list(scene[bridge.S_WARNINGS]))

    def test_clean_build_has_no_warnings(self):
        scene = self.open_scene()
        self.assertEqual(list(scene[bridge.S_WARNINGS]), [])


class OpenFailureTest(BridgeCase):
    """A scene that can't be opened from Godot says why, not only in the console."""

    def startup_python(self) -> str:
        """The Python Godot passes to Blender, decoded from its base64 wrapper."""
        with open(os.path.join(harness.PIPELINE, "startup_expr.py"), encoding="utf-8") as handle:
            encoded = re.search(r"b64decode\('([A-Za-z0-9+/=]*)'\)", handle.read()).group(1)
        return base64.b64decode(encoded).decode("utf-8")

    def test_unreadable_manifest_is_reported_and_kept_for_the_panel(self):
        with open(self.manifest_path(), "w", encoding="utf-8") as handle:
            handle.write("{")
        with self.assertRaisesRegex(RuntimeError, "basic.json is not valid JSON"):
            bpy.ops.bb.open_from_godot(filepath=self.manifest_path())
        self.assertIn("not valid JSON", blenderang._OPEN_ERROR["message"], "the panel shows it")
        self._restore()
        self.open_scene()
        self.assertEqual(blenderang._OPEN_ERROR["message"], "", "a successful open clears it")

    def test_startup_python_reports_a_missing_manifest(self):
        startup = self.startup_python().replace("basic.json", "missing.json")
        with self.assertRaisesRegex(RuntimeError, "Blenderang: manifest does not exist: .*missing.json"):
            exec(startup, {})

    def test_startup_python_without_the_extension(self):
        startup = self.startup_python()
        blenderang.unregister()
        try:
            with self.assertRaisesRegex(RuntimeError, "Blenderang extension is not installed or enabled"):
                exec(startup, {})
        finally:
            blenderang.register()


class DetailTest(BridgeCase):
    def test_model_detail(self):
        self.open_scene()
        kind, rows = bridge.describe(bpy.data.objects["InRotated"])
        values = dict(rows)
        self.assertEqual(kind, "model")
        self.assertEqual(values["Godot node"], "Rotated/InRotated")
        self.assertEqual(values["Parent"], "Rotated")
        self.assertEqual(values["Asset"], "fixtures/assets/crate.glb")
        self.assertIn("fixtures/assets/crate.blend", values["Source"])

    def test_godot_context_detail_names_the_godot_node(self):
        self.open_scene()
        mesh = next(c for c in bpy.data.objects["Building"].children_recursive if c.type == "MESH")
        kind, rows = bridge.describe(mesh)
        self.assertEqual(kind, "godot")
        self.assertEqual(dict(rows)["Godot node"], "Building")

    def test_helper_detail(self):
        self.open_scene()
        helper = bpy.data.objects.new("Helper", None)
        bpy.context.scene.collection.objects.link(helper)
        self.assertEqual(bridge.describe(helper)[0], "helper")


class HierarchyTest(BridgeCase):
    def test_child_model_is_parented_and_follows(self):
        self.open_scene()
        helmet = bpy.data.objects["Helmet"]
        character = bpy.data.objects["Character"]
        self.assertIs(helmet.parent, character)
        self.assertVectorAlmostEqual(helmet.matrix_world.translation, godot_to_blender_point(5, 1.8, -2))
        character.location.x += 2
        bridge.export(bpy.context.scene)
        sent = self.entry(self.read_manifest(), "Helmet")["xform"]
        self.assertAlmostEqual(sent[9], 7.0, places=4, msg="moving the parent is sent for the child too")

    def test_empties_are_about_one_metre(self):
        self.open_scene()
        empties = [o for o in self.collection_objects(bridge.COLL_LOCKED) if o.type == "EMPTY"]
        self.assertTrue(empties)
        for obj in empties:
            world = obj.empty_display_size * max(abs(v) for v in obj.matrix_world.to_scale())
            self.assertAlmostEqual(world, 1.0, places=3, msg=obj.name)


class ChooseSourceTest(BridgeCase):
    CRATE = "res://fixtures/assets/crate.glb"

    def shared(self) -> str:
        write_source("../shared_props.blend", "props_library")
        return os.path.join(harness.PROJECT, "fixtures", "shared_props.blend")

    def outside(self) -> str:
        """Source outside the project, e.g. an artist's personal folder."""
        path = os.path.join(os.path.dirname(harness.PROJECT), "outside_sources", "crate_master.blend")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_source(os.path.relpath(path, harness.ASSETS), "crate_master")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_source_in_project_is_shared(self):
        source = self.shared()
        self.addCleanup(os.remove, source)
        scene = self.open_scene()
        path, personal = bridge.choose_source(scene, self.CRATE, source)
        self.assertEqual((path, personal), ("fixtures/shared_props.blend", False))
        with open(os.path.join(harness.ASSETS, "crate.glb.bbsrc"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "fixtures/shared_props.blend", "Godot reads the same file")
        for name in ("Crate", "InRotated", "Detached"):
            obj = bpy.data.objects[name]
            self.assertEqual(obj.get(bridge.P_TIER), "library", name)
            self.assertIsNotNone(obj.instance_collection.library, name)
        self.assertEqual(bridge.source_choice(harness.PROJECT, self.CRATE), "shared")

    def test_source_outside_project_is_personal(self):
        source = self.outside()
        scene = self.open_scene()
        path, personal = bridge.choose_source(scene, self.CRATE, source)
        self.assertTrue(personal)
        self.assertEqual(path, source)
        self.assertFalse(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")), "nothing shared is written to the project")
        self.assertEqual(bridge.local_sources(harness.PROJECT), {self.CRATE: source})
        with open(os.path.join(harness.PIPELINE, "local", ".gitignore"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "*", "a personal choice is never committed")
        self.assertIsNotNone(bpy.data.objects["Crate"].instance_collection.library)
        self.assertEqual(bridge.source_choice(harness.PROJECT, self.CRATE), "personal")
        self.assertIn("only for you", dict(bridge.describe(bpy.data.objects["Crate"])[1])["Source"])

    def test_personal_source_wins_and_survives_reload(self):
        shared = self.shared()
        self.addCleanup(os.remove, shared)
        personal = self.outside()
        scene = self.open_scene()
        bridge.choose_source(scene, self.CRATE, shared)
        bridge.choose_source(scene, self.CRATE, personal)
        bpy.ops.bb.rebuild()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), personal)
        self.assertTrue(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")), "the others' shared choice stays")

    def test_clear_personal_falls_back_to_shared(self):
        shared = self.shared()
        self.addCleanup(os.remove, shared)
        personal = self.outside()
        scene = self.open_scene()
        bridge.choose_source(scene, self.CRATE, shared)
        bridge.choose_source(scene, self.CRATE, personal)
        bridge.clear_source(scene, self.CRATE)
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), "fixtures/shared_props.blend")
        self.assertEqual(bridge.local_sources(harness.PROJECT), {})

    def test_choosing_inside_project_drops_personal_choice(self):
        shared = self.shared()
        self.addCleanup(os.remove, shared)
        personal = self.outside()
        scene = self.open_scene()
        bridge.choose_source(scene, self.CRATE, personal)
        bridge.choose_source(scene, self.CRATE, shared)
        self.assertEqual(bridge.local_sources(harness.PROJECT), {})
        self.assertEqual(bridge.source_choice(harness.PROJECT, self.CRATE), "shared")

    def test_choosing_sibling_needs_no_marker(self):
        source = write_source("crate.blend", "crate")
        scene = self.open_scene()
        self.assertEqual(bridge.choose_source(scene, self.CRATE, source), ("fixtures/assets/crate.blend", False))
        self.assertFalse(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")))

    def test_clear_source_returns_to_preview(self):
        source = self.shared()
        self.addCleanup(os.remove, source)
        scene = self.open_scene()
        bridge.choose_source(scene, self.CRATE, source)
        bridge.clear_source(scene, self.CRATE)
        self.assertFalse(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")))
        crate = bpy.data.objects["Crate"]
        self.assertEqual(crate.get(bridge.P_TIER), "none")
        self.assertIsNotNone(crate.instance_collection)
        self.assertIsNone(crate.instance_collection.library)

    def test_rejects_non_blend(self):
        scene = self.open_scene()
        with self.assertRaises(bridge.BridgeError):
            bridge.choose_source(scene, self.CRATE, os.path.join(harness.ASSETS, "crate.glb"))


class ModelsFolderTest(BridgeCase):
    """Sources in a shared folder outside the project, at a different place on every disk."""

    CRATE = "res://fixtures/assets/crate.glb"

    def library(self) -> str:
        folder = os.path.join(os.path.dirname(harness.PROJECT), "models_library")
        os.makedirs(folder, exist_ok=True)
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def library_source(self, folder: str, relative: str, collection: str = "crate") -> str:
        path = os.path.join(folder, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_source(os.path.relpath(path, harness.ASSETS), collection)
        return path

    def test_source_is_found_by_name(self):
        folder = self.library()
        self.library_source(folder, "props/Crate.blend")
        self.library_source(folder, ".git/crate.blend")
        scene = self.open_scene()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_TIER), "none", "no folder set yet")
        bridge.set_models_folder(scene, folder)
        crate = bpy.data.objects["Crate"]
        self.assertEqual(crate.get(bridge.P_SRC_BLEND), "models://props/Crate.blend")
        self.assertIsNotNone(crate.instance_collection.library)
        self.assertEqual(bpy.data.objects["Tower"].get(bridge.P_TIER), "none", "no tower.blend in the folder")
        self.assertEqual(dict(bridge.describe(crate)[1])["Source"], "props/Crate.blend (models folder)")
        bpy.ops.bb.rebuild()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), "models://props/Crate.blend", "kept after rebuild")
        self.assertEqual(list(bpy.context.scene[bridge.S_WARNINGS]), [])

    def test_sibling_wins_and_mirrored_path_breaks_ties(self):
        folder = self.library()
        self.library_source(folder, "a/crate.blend")
        self.library_source(folder, "fixtures/assets/crate.blend")
        scene = self.open_scene()
        bridge.set_models_folder(scene, folder)
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), "models://fixtures/assets/crate.blend")
        write_source("crate.blend", "crate")
        bpy.ops.bb.rebuild()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), "fixtures/assets/crate.blend")

    def test_ambiguous_name_warns(self):
        folder = self.library()
        self.library_source(folder, "b/crate.blend")
        self.library_source(folder, "a/crate.blend")
        scene = self.open_scene()
        bridge.set_models_folder(scene, folder)
        bpy.ops.bb.rebuild()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), "models://a/crate.blend")
        warnings = list(bpy.context.scene[bridge.S_WARNINGS])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("a/crate.blend", warnings[0])

    def test_picked_source_in_folder_is_shared_relative(self):
        folder = self.library()
        source = self.library_source(folder, "props/crate_v2.blend")
        scene = self.open_scene()
        bridge.set_models_folder(scene, folder)
        self.assertEqual(bridge.choose_source(scene, self.CRATE, source), ("models://props/crate_v2.blend", False))
        with open(os.path.join(harness.ASSETS, "crate.glb.bbsrc"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "models://props/crate_v2.blend", "no absolute path in the shared file")
        self.assertEqual(bridge.local_sources(harness.PROJECT), {})

        # Someone else keeps the folder elsewhere: the same .bbsrc works for them.
        moved = os.path.join(os.path.dirname(harness.PROJECT), "models_elsewhere")
        shutil.move(folder, moved)
        self.addCleanup(shutil.rmtree, moved, True)
        bridge.set_models_folder(scene, moved)
        crate = bpy.data.objects["Crate"]
        self.assertEqual(crate.get(bridge.P_SRC_BLEND), "models://props/crate_v2.blend")
        self.assertTrue(bridge._same_file(bpy.path.abspath(crate.instance_collection.library.filepath),
                                          os.path.join(moved, "props", "crate_v2.blend")))

        # Without the folder set the model falls back to the .glb preview.
        bridge.set_models_folder(scene, "")
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_TIER), "none")

    def test_make_source_goes_to_folder_and_edits_there(self):
        folder = self.library()
        scene = self.open_scene()
        bridge.set_models_folder(scene, folder)
        self.assertEqual(bpy.ops.bb.promote_source(name="Tower"), {"FINISHED"})
        created = os.path.join(folder, "fixtures", "assets", "tower.blend")
        self.assertTrue(os.path.isfile(created))
        self.assertFalse(os.path.exists(os.path.join(harness.ASSETS, "tower.blend")), "nothing new in the game project")
        self.assertEqual(bpy.data.objects["Tower"].get(bridge.P_SRC_BLEND), "models://fixtures/assets/tower.blend")
        self.assertEqual(bpy.ops.bb.edit_source(name="Tower"), {"FINISHED"})
        self.assertTrue(bridge._same_file(bpy.data.filepath, created))

    def test_models_folder_mirrors_a_project_folder(self):
        root = os.path.join(os.path.dirname(harness.PROJECT), "mirror_project")
        os.makedirs(root, exist_ok=True)
        self.addCleanup(shutil.rmtree, root, True)
        godot = os.path.join(root, "project.godot")
        with open(godot, "w", encoding="utf-8") as handle:
            handle.write('config_version=5\n\n[application]\n\nconfig/name="x"\n')
        self.assertEqual(bridge.models_relative(root, "res://assets/levels/castle.glb"), "levels/castle.blend",
                         "by default assets/ is mirrored, same as Godot")
        self.assertEqual(bridge.models_relative(root, "res://props/crate.glb"), "props/crate.blend",
                         "an asset outside it keeps its whole path")
        with open(godot, "a", encoding="utf-8") as handle:
            handle.write('\n[blenderang]\n\nmodels/project_folder="/art/"\n')
        self.assertEqual(bridge.models_relative(root, "res://art/levels/castle.glb"), "levels/castle.blend")
        self.assertEqual(bridge.models_asset(root, "levels/castle.blend"), "res://art/levels/castle.glb")


class TerrainMaterialTest(BridgeCase):
    def test_terrain_has_textured_material(self):
        if not os.path.exists(self.manifest_path("terrain")):
            self.skipTest("Terrain3D is not installed")
        self.open_scene("terrain")
        terrain = bpy.data.objects["TerrainMesh"]
        self.assertTrue(terrain.data.uv_layers, "terrain has UVs")
        material = terrain.active_material
        self.assertIsNotNone(material, "terrain has a material")
        images = [n.image for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
        self.assertEqual(len(images), 1, "the material has a baked texture")
        self.assertEqual(tuple(images[0].size), (256, 256))


class FilterTest(BridgeCase):
    def test_filter_by_name_path_and_asset(self):
        scene = self.open_scene()
        models = bridge.scene_models(scene)
        names = lambda text: [o.name for o in bridge.filter_models(models, text)]
        self.assertEqual(names(""), list(MODELS))
        self.assertEqual(names("tow"), ["Tower"], "part of the name")
        self.assertEqual(names("ROTATED"), ["Detached", "InRotated"], "Godot path, case-insensitive")
        self.assertEqual(names("crate.glb"), ["Crate", "Detached", "Helmet", "InRotated"], "asset name")
        self.assertEqual(names("crate rotated"), ["Detached", "InRotated"], "several words = all of them")
        self.assertEqual(names("nothing like this"), [])
