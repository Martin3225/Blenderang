"""Stavba scény v Blenderu z manifestu (Godot → Blender)."""

import math
import os

import bpy

import blender_bridge.bridge as bridge
from harness import ASSETS, BridgeCase, godot_to_blender_point
import harness

MODELS = ("Barrel", "Character", "Crate", "Detached", "Helmet", "InRotated", "Tower")


def write_source(asset: str, collection_name: str) -> str:
    """Zdrojový .blend s jednou kolekcí, jak by ho vyrobil grafik."""
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
            "InRotated": (10, 2, -2),      # pod otočeným a zvětšeným rodičem
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
            self.assertIsNotNone(source, "%s nemá geometrii" % name)
            meshes = [o for o in source.all_objects if o.type == "MESH"]
            self.assertTrue(meshes, "%s: náhled bez meshe" % name)
            leaked = scene_objects & set(source.all_objects)
            self.assertFalse(leaked, "%s: zdroj náhledu je i ve scéně (v počátku): %s" % (name, leaked))

    def test_no_stray_objects_outside_bridge_collections(self):
        scene = self.open_scene()
        allowed = {bridge.COLL_LAYOUT, bridge.COLL_LOCKED}
        for obj in scene.objects:
            owners = {c.name for c in obj.users_collection}
            self.assertTrue(owners & allowed, "%s leží mimo kolekce mostu: %s" % (obj.name, owners))

    def test_bone_shape_helpers_stay_out_of_model(self):
        self.open_scene()
        source = bpy.data.objects["Character"].instance_collection
        shapes = {
            bone.custom_shape
            for obj in source.all_objects if obj.type == "ARMATURE"
            for bone in obj.pose.bones if bone.custom_shape
        }
        self.assertTrue(any(o.type == "ARMATURE" for o in source.all_objects), "rig bez armatury")
        self.assertFalse(shapes & set(source.all_objects), "tvary kostí se vykreslují jako součást modelu")

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
        self.assertTrue(any(c.type == "MESH" for c in building.children_recursive), "Building bez meshe")
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
        self.assertEqual(len(linked), 1, "všechny instance sdílí jednu nalinkovanou kolekci")
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
            self.skipTest("Terrain3D není nainstalovaný")
        self.open_scene("terrain")
        meshes = [o for o in self.collection_objects(bridge.COLL_LOCKED) if o.type == "MESH"]
        self.assertEqual([o.name for o in meshes], ["TerrainMesh"], "jen terén, žádné interní meshe Terrain3D")
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
    """Jeden vadný soubor nesmí shodit stavbu celé scény."""

    def test_corrupt_context_falls_back_to_boxes(self):
        manifest = self.read_manifest()
        with open(os.path.join(harness.PROJECT, manifest["context_glb"]), "wb") as handle:
            handle.write(b"glTF\x02\x00\x00\x00\x10\x01\x00\x00")   # jako prázdný export z editoru
        scene = self.open_scene()
        self.assertTrue(scene.get(bridge.S_MANIFEST), "scéna se dostavěla")
        self.assertEqual(bpy.data.objects["Building"].type, "MESH")
        self.assertEqual(len(bpy.data.objects["Building"].data.vertices), 8)
        self.assertTrue(any("kontext" in w for w in scene[bridge.S_WARNINGS]), list(scene[bridge.S_WARNINGS]))
        self.assertFalse([o for o in scene.objects if not o.users_collection or
                          not {c.name for c in o.users_collection} & {bridge.COLL_LAYOUT, bridge.COLL_LOCKED}],
                         "po neúspěšném importu nic nezůstalo napůl")

    def test_corrupt_asset_does_not_break_other_models(self):
        with open(os.path.join(harness.ASSETS, "tower.glb"), "wb") as handle:
            handle.write(b"not a glb")
        scene = self.open_scene()
        self.assertTrue(scene.get(bridge.S_MANIFEST))
        self.assertIsNone(bpy.data.objects["Tower"].instance_collection, "rozbitý asset zůstane osou")
        self.assertIsNotNone(bpy.data.objects["Crate"].instance_collection, "ostatní modely jsou v pořádku")
        self.assertTrue(any("Tower" in w for w in scene[bridge.S_WARNINGS]), list(scene[bridge.S_WARNINGS]))

    def test_clean_build_has_no_warnings(self):
        scene = self.open_scene()
        self.assertEqual(list(scene[bridge.S_WARNINGS]), [])


class DetailTest(BridgeCase):
    def test_model_detail(self):
        self.open_scene()
        kind, rows = bridge.describe(bpy.data.objects["InRotated"])
        values = dict(rows)
        self.assertEqual(kind, "model")
        self.assertEqual(values["Node v Godotu"], "Rotated/InRotated")
        self.assertEqual(values["Rodič"], "Rotated")
        self.assertEqual(values["Asset"], "fixtures/assets/crate.glb")
        self.assertIn("fixtures/assets/crate.blend", values["Zdroj"])

    def test_godot_context_detail_names_the_godot_node(self):
        self.open_scene()
        mesh = next(c for c in bpy.data.objects["Building"].children_recursive if c.type == "MESH")
        kind, rows = bridge.describe(mesh)
        self.assertEqual(kind, "godot")
        self.assertEqual(dict(rows)["Node v Godotu"], "Building")

    def test_helper_detail(self):
        self.open_scene()
        helper = bpy.data.objects.new("Pomocna", None)
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
        self.assertAlmostEqual(sent[9], 7.0, places=4, msg="posun rodiče se pošle i u dítěte")

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
        """Zdroj mimo projekt — třeba osobní složka grafika."""
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
            self.assertEqual(handle.read(), "fixtures/shared_props.blend", "Godot čte stejný soubor")
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
        self.assertFalse(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")), "do projektu se nic sdíleného nezapíše")
        self.assertEqual(bridge.local_sources(harness.PROJECT), {self.CRATE: source})
        with open(os.path.join(harness.PIPELINE, "local", ".gitignore"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "*", "osobní výběr se nikdy necommitne")
        self.assertIsNotNone(bpy.data.objects["Crate"].instance_collection.library)
        self.assertEqual(bridge.source_choice(harness.PROJECT, self.CRATE), "personal")
        self.assertIn("jen u tebe", dict(bridge.describe(bpy.data.objects["Crate"])[1])["Zdroj"])

    def test_personal_source_wins_and_survives_reload(self):
        shared = self.shared()
        self.addCleanup(os.remove, shared)
        personal = self.outside()
        scene = self.open_scene()
        bridge.choose_source(scene, self.CRATE, shared)
        bridge.choose_source(scene, self.CRATE, personal)
        bpy.ops.bb.rebuild()
        self.assertEqual(bpy.data.objects["Crate"].get(bridge.P_SRC_BLEND), personal)
        self.assertTrue(os.path.exists(os.path.join(harness.ASSETS, "crate.glb.bbsrc")), "sdílený výběr ostatních zůstal")

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
