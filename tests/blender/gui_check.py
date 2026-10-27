"""Blender GUI tests (with a window, on a virtual display).

Covers what can't be done in the background: starting via a timer from Godot's
startup Python, drawing the panel in both modes, framing the view after opening
and switching between the scene and model editing with a real window.

    blender --factory-startup --python-expr "<startup Python from Godot>" \
        --python tests/blender/gui_check.py -- --repo R --project P --out O
"""

import json
import os
import sys
import traceback

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
options = dict(zip(args[::2], args[1::2]))
sys.path.insert(0, os.path.join(options["--repo"], "tools"))
import blenderang  # noqa: E402

blenderang.register()
import blenderang.bridge as bridge  # noqa: E402

OUT = options["--out"]
results = []
drawn = []          # (mode, error or None) from each panel draw


def record(name, passed, message=""):
    results.append({"name": "gui: " + name, "status": "pass" if passed else "fail",
                    "message": "" if passed else message})


class BB_PT_probe(blenderang.BB_PT_panel):
    """The same panel in the Item tab (visible in the sidebar by default), so it
    draws without clicking the Blenderang tab. Records exceptions from draw()."""

    bl_idname = "BB_PT_probe"
    bl_category = "Item"

    def draw(self, context):
        mode = "edit" if bridge.edit_session() else ("scene" if context.scene.get(bridge.S_MANIFEST) else "empty")
        try:
            super().draw(context)
            drawn.append((mode, None))
        except Exception:  # noqa: BLE001
            drawn.append((mode, traceback.format_exc(limit=2)))


class BB_PT_probe_detail(blenderang.BB_PT_detail):
    """Detail panel in the Item tab, recording exceptions."""

    bl_idname = "BB_PT_probe_detail"
    bl_category = "Item"
    bl_parent_id = ""

    def draw(self, context):
        try:
            super().draw(context)
            drawn.append(("detail", None))
        except Exception:  # noqa: BLE001
            drawn.append(("detail", traceback.format_exc(limit=2)))


bpy.utils.register_class(BB_PT_probe)
bpy.utils.register_class(BB_PT_probe_detail)


def view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                return window, area
    return None, None


def redraw() -> None:
    window, area = view3d()
    if area is None:
        return
    area.spaces.active.show_region_ui = True
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)


def panel_drew(mode: str) -> tuple[bool, str]:
    redraw()
    runs = [error for kind, error in drawn if kind == mode]
    errors = [e for e in runs if e]
    return bool(runs) and not errors, (errors[0] if errors else "panel did not draw")


# Steps run through timers: between them Blender must draw the window and load
# files. Each returns the pause before the next step.

def step_scene_opened():
    scene = bpy.context.scene
    record("Godot's startup Python builds the scene in the window",
           scene.get(bridge.S_MANIFEST, "").endswith("basic.json") and scene.name == "basic", scene.name)
    ok, message = panel_drew("scene")
    record("scene panel draws without errors", ok, message)
    scene.bb_model_filter = "rotated"
    drawn.clear()
    ok, message = panel_drew("scene")
    record("panel with search draws", ok, message)
    scene.bb_model_filter = "nothing like this"
    drawn.clear()
    ok, message = panel_drew("scene")
    record("panel with no search results draws", ok, message)
    scene.bb_model_filter = ""
    for name in ("Crate", "Building"):
        bpy.context.view_layer.objects.active = bpy.data.objects[name]
        drawn.clear()
        ok, message = panel_drew("detail")
        record("detail for %s draws" % name, ok, message)

    window, area = view3d()
    space = area.spaces.active
    record("view reaches the terrain (clip_end)", space.clip_end >= 20000, str(space.clip_end))
    models = [o.matrix_world.translation for o in bridge.scene_models(scene)]
    center = sum(models, models[0] * 0) / len(models)
    distance = (space.region_3d.view_location - center).length
    record("view is framed on the models", distance < 10, "view centre %.1f m from the models" % distance)
    return 0.5


def step_promote_and_edit():
    window, area = view3d()
    with bpy.context.temp_override(window=window, area=area):
        record("make source from the list button", bpy.ops.bb.promote_source(name="Tower") == {"FINISHED"})
        record("edit model from the list button", bpy.ops.bb.edit_source(name="Tower") == {"FINISHED"})
    return 1.0


def step_in_edit():
    record("the model's source opened", bpy.data.filepath.endswith("tower.blend"), bpy.data.filepath)
    record("context surrounds the model", bpy.data.collections.get(bridge.COLL_CONTEXT) is not None)
    ok, message = panel_drew("edit")
    record("edit panel draws without errors", ok, message)
    bpy.ops.wm.save_mainfile()
    window, area = view3d()
    with bpy.context.temp_override(window=window, area=area):
        record("save and return to scene", bpy.ops.bb.return_to_scene() == {"FINISHED"})
    return 1.0


def step_back_in_scene():
    record("after returning the scene has no file", bpy.data.filepath == "")
    record("Tower has a source", bpy.data.objects["Tower"].get(bridge.P_TIER) == "library")
    drawn.clear()
    ok, message = panel_drew("scene")
    record("scene panel after returning", ok, message)

    # Source outside the project: notice in the window and warning in the Detail panel.
    outside = os.path.join(os.path.dirname(options["--project"]), "outside_sources", "gui_crate.blend")
    os.makedirs(os.path.dirname(outside), exist_ok=True)
    collection = bpy.data.collections.new("crate_master")
    collection.objects.link(bpy.data.objects.new("crate_master_body", None))
    bpy.data.libraries.write(outside, {collection}, fake_user=True)
    window, area = view3d()
    with bpy.context.temp_override(window=window, area=area):
        result = bpy.ops.bb.choose_source(name="Crate", filepath=outside)
    record("pick a source outside the project from the window", result == {"FINISHED"})
    record("a source outside the project is personal",
           bridge.source_choice(options["--project"], "res://fixtures/assets/crate.glb") == "personal")
    bpy.context.view_layer.objects.active = bpy.data.objects["Crate"]
    drawn.clear()
    ok, message = panel_drew("detail")
    record("detail with a personal source draws", ok, message)
    return None


STEPS = [step_scene_opened, step_promote_and_edit, step_in_edit, step_back_in_scene]


def run_steps():
    try:
        if not STEPS:
            return finish()
        delay = STEPS.pop(0)()
        if delay is None and not STEPS:
            return finish()
        return delay or 0.5
    except Exception:  # noqa: BLE001
        record("(exception)", False, traceback.format_exc(limit=3))
        return finish()


def finish():
    with open(os.path.join(OUT, "gui.json"), "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
    bpy.ops.wm.quit_blender()
    return None


# Godot's startup Python calls open_from_godot after 0.2 s; wait longer.
bpy.app.timers.register(run_steps, first_interval=3.0, persistent=True)
