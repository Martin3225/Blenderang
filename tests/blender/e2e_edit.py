"""E2E krok 2 (Blender): spustí přesně ten Python, který předává Godot,
a udělá v scéně typickou práci — posun, rotaci, duplikaci, smazání, pomocný
objekt a výrobu zdroje — a odešle ji do Godotu."""

import json
import math
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
options = dict(zip(args[::2], args[1::2]))
sys.path.insert(0, os.path.join(options["--repo"], "tools"))
import blender_bridge  # noqa: E402

blender_bridge.register()
import blender_bridge.bridge as bridge  # noqa: E402

OUT = options["--out"]
results = []


def record(name, passed, message=""):
    results.append({"name": "blender: " + name, "status": "pass" if passed else "fail",
                    "message": "" if passed else message})


try:
    with open(os.path.join(OUT, "startup_expr.py"), encoding="utf-8") as handle:
        exec(handle.read())
    scene = bpy.context.scene
    record("scéna postavena ze startovního Pythonu z Godotu", scene.get(bridge.S_MANIFEST, "").endswith("basic.json"))

    bpy.data.objects["Crate"].location.x += 3
    bpy.data.objects["Character"].location.x += 2     # Helmet je potomek, jde s ním
    bpy.data.objects["InRotated"].rotation_euler.z += math.radians(45)
    copy = bpy.data.objects["Tower"].copy()
    copy.name = "TowerCopy"
    bpy.data.collections[bridge.COLL_LAYOUT].objects.link(copy)
    copy.location.x += 5
    bpy.data.objects.remove(bpy.data.objects["Barrel"], do_unlink=True)
    helper = bpy.data.objects.new("Pomocna", bpy.data.meshes.new("pomocna"))
    scene.collection.objects.link(helper)
    record("vyrobit zdroj pro Crate", bpy.ops.bb.promote_source(name="Crate") == {"FINISHED"})

    record("odeslat do Godotu", bpy.ops.bb.export_manifest() == {"FINISHED"})
except Exception as error:  # noqa: BLE001 — chyba musí skončit ve výsledcích
    import traceback

    traceback.print_exc()
    record("(výjimka)", False, repr(error))

with open(os.path.join(OUT, "e2e_blender.json"), "w", encoding="utf-8") as handle:
    json.dump(results, handle, indent=2, ensure_ascii=False)
