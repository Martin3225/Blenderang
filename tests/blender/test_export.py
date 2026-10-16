"""Odeslání změn z Blenderu do manifestu (Blender → Godot)."""

import math

import bpy

import blender_bridge.bridge as bridge
from harness import BridgeCase


class ExportTest(BridgeCase):
    def send(self) -> dict:
        return bridge.export(bpy.context.scene)

    def test_untouched_scene_roundtrips_exactly(self):
        original = self.read_manifest()
        self.open_scene()
        counts = self.send()
        self.assertEqual((counts["moved"], counts["added"], counts["removed"]), (0, 0, 0))
        after = self.read_manifest()
        self.assertEqual(
            [e for e in after["nodes"] if e.get("owner") != "blender"],
            [e for e in original["nodes"] if e.get("owner") != "blender"],
            "Godot část manifestu se nesmí změnit",
        )
        self.assertEqual(after["context_glb"], original["context_glb"])

    def test_move_is_sent_in_godot_axes(self):
        self.open_scene()
        crate = bpy.data.objects["Crate"]
        crate.location.x += 3     # Godot +X
        crate.location.z += 2     # Godot +Y
        crate.location.y += 1     # Godot −Z
        counts = self.send()
        self.assertEqual(counts["moved"], 1)
        x = self.entry(self.read_manifest(), "Crate")["xform"]
        self.assertAlmostEqual(x[9], 5.0, places=4)
        self.assertAlmostEqual(x[10], 2.0, places=4)
        self.assertAlmostEqual(x[11], 2.0, places=4)

    def test_rotation_and_scale_are_sent(self):
        self.open_scene()
        tower = bpy.data.objects["Tower"]
        tower.rotation_euler = (0, 0, math.radians(90))
        tower.scale = (1, 1, 3)
        self.send()
        x = self.entry(self.read_manifest(), "Tower")["xform"]
        # Basis.x po otočení o 90° kolem svislé osy míří v Godotu na −Z.
        self.assertAlmostEqual(x[0], 0.0, places=4)
        self.assertAlmostEqual(x[2], -1.0, places=4)
        # Měřítko 3 v Blenderu na Z je v Godotu na Y.
        self.assertAlmostEqual(x[4], 3.0, places=4)

    def test_duplicate_gets_new_id_and_same_parent(self):
        self.open_scene()
        tower = bpy.data.objects["Tower"]
        copy = tower.copy()   # Shift+D zkopíruje i custom properties
        copy.name = "TowerCopy"
        bpy.data.collections[bridge.COLL_LAYOUT].objects.link(copy)
        copy.location.x += 5
        counts = self.send()
        self.assertEqual(counts["added"], 1)
        manifest = self.read_manifest()
        ids = [e["bb_id"] for e in manifest["nodes"] if e.get("owner") == "blender"]
        self.assertEqual(len(ids), len(set(ids)), "id musí být unikátní")
        added = self.entry(manifest, "TowerCopy")
        original = self.entry(manifest, "Tower")
        self.assertNotEqual(added["bb_id"], original["bb_id"])
        self.assertEqual(added["parent"], "Props")
        self.assertEqual(added["src"], original["src"])
        self.assertEqual(copy.get(bridge.P_ID), added["bb_id"], "objekt si nové id pamatuje")
        # Druhé odeslání už nesmí přidávat znovu.
        self.assertEqual(self.send()["added"], 0)

    def test_delete_is_sent(self):
        self.open_scene()
        bpy.data.objects.remove(bpy.data.objects["Barrel"], do_unlink=True)
        counts = self.send()
        self.assertEqual(counts["removed"], 1)
        with self.assertRaises(KeyError):
            self.entry(self.read_manifest(), "Barrel")

    def test_helper_objects_are_not_sent(self):
        self.open_scene()
        helper = bpy.data.objects.new("Pomocna", bpy.data.meshes.new("pomocna"))
        bpy.context.scene.collection.objects.link(helper)
        before = len(self.read_manifest()["nodes"])
        self.send()
        self.assertEqual(len(self.read_manifest()["nodes"]), before)

    def test_pinned_entry_is_not_overwritten(self):
        manifest = self.read_manifest()
        self.entry(manifest, "Crate")["pinned"] = True
        self.write_manifest(manifest)
        self.open_scene()
        bpy.data.objects["Crate"].location.x += 100
        counts = self.send()
        self.assertEqual(counts["pinned"], 1)
        self.assertAlmostEqual(self.entry(self.read_manifest(), "Crate")["xform"][9], 2.0, places=4)

    def test_send_without_loaded_manifest_fails_cleanly(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.export(bpy.context.scene)
