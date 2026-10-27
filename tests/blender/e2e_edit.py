"""E2E step 2 (Blender): runs exactly the Python that Godot passes,
does typical work in the scene (move, rotate, duplicate, delete, a helper
object and making a source) and sends it to Godot."""

import json
import math
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
options = dict(zip(args[::2], args[1::2]))
sys.path.insert(0, os.path.join(options["--repo"], "tools"))
import blenderang  # noqa: E402

blenderang.register()
import blenderang.bridge as bridge  # noqa: E402

OUT = options["--out"]
results = []


def record(name, passed, message=""):
    results.append({"name": "blender: " + name, "status": "pass" if passed else "fail",
                    "message": "" if passed else message})


try:
    with open(os.path.join(OUT, "startup_expr.py"), encoding="utf-8") as handle:
        exec(handle.read())
    scene = bpy.context.scene
    record("scene built from Godot's startup Python", scene.get(bridge.S_MANIFEST, "").endswith("basic.json"))

    bpy.data.objects["Crate"].location.x += 3
    bpy.data.objects["Character"].location.x += 2     # Helmet is a child, it moves along
    bpy.data.objects["InRotated"].rotation_euler.z += math.radians(45)
    copy = bpy.data.objects["Tower"].copy()
    copy.name = "TowerCopy"
    bpy.data.collections[bridge.COLL_LAYOUT].objects.link(copy)
    copy.location.x += 5
    bpy.data.objects.remove(bpy.data.objects["Barrel"], do_unlink=True)
    helper = bpy.data.objects.new("Helper", bpy.data.meshes.new("helper"))
    scene.collection.objects.link(helper)
    record("make source for Crate", bpy.ops.bb.promote_source(name="Crate") == {"FINISHED"})

    record("send to Godot", bpy.ops.bb.export_manifest() == {"FINISHED"})
except Exception as error:  # noqa: BLE001 — the error must end up in the results
    import traceback

    traceback.print_exc()
    record("(exception)", False, repr(error))

with open(os.path.join(OUT, "e2e_blender.json"), "w", encoding="utf-8") as handle:
    json.dump(results, handle, indent=2, ensure_ascii=False)
