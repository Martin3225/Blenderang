"""GUI testy Blenderu (s oknem, na virtuálním displeji).

Pokrývá, co na pozadí nejde: start přes časovač ze startovního Pythonu
z Godotu, vykreslení panelu v obou režimech, zaměření pohledu po otevření
a přechody mezi scénou a úpravou modelu se skutečným oknem.

    blender --factory-startup --python-expr "<startovní Python z Godotu>" \
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
import blender_bridge  # noqa: E402

blender_bridge.register()
import blender_bridge.bridge as bridge  # noqa: E402

OUT = options["--out"]
results = []
drawn = []          # (režim, chyba nebo None) z každého vykreslení panelu


def record(name, passed, message=""):
    results.append({"name": "gui: " + name, "status": "pass" if passed else "fail",
                    "message": "" if passed else message})


class BB_PT_probe(blender_bridge.BB_PT_panel):
    """Stejný panel v záložce Item (ta je v sidebaru vidět výchozí), aby se
    vykreslil bez klikání na záložku Bridge. Zaznamená výjimky z draw()."""

    bl_idname = "BB_PT_probe"
    bl_category = "Item"

    def draw(self, context):
        mode = "edit" if bridge.edit_session() else ("scene" if context.scene.get(bridge.S_MANIFEST) else "empty")
        try:
            super().draw(context)
            drawn.append((mode, None))
        except Exception:  # noqa: BLE001
            drawn.append((mode, traceback.format_exc(limit=2)))


bpy.utils.register_class(BB_PT_probe)


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
    return bool(runs) and not errors, (errors[0] if errors else "panel se nevykreslil")


# Kroky běží přes časovače: mezi nimi musí Blender vykreslit okno a načíst
# soubory. Každý vrací pauzu před dalším krokem.

def step_scene_opened():
    scene = bpy.context.scene
    record("startovní Python z Godotu postaví scénu v okně",
           scene.get(bridge.S_MANIFEST, "").endswith("basic.json") and scene.name == "basic", scene.name)
    ok, message = panel_drew("scene")
    record("panel scény se vykreslí bez chyby", ok, message)

    window, area = view3d()
    space = area.spaces.active
    record("pohled dohlédne na terén (clip_end)", space.clip_end >= 20000, str(space.clip_end))
    models = [o.matrix_world.translation for o in bridge.scene_models(scene)]
    center = sum(models, models[0] * 0) / len(models)
    distance = (space.region_3d.view_location - center).length
    record("pohled je zaměřený na modely", distance < 10, "střed pohledu %.1f m od modelů" % distance)
    return 0.5


def step_promote_and_edit():
    window, area = view3d()
    with bpy.context.temp_override(window=window, area=area):
        record("vyrobit zdroj z tlačítka v seznamu", bpy.ops.bb.promote_source(name="Tower") == {"FINISHED"})
        record("upravit model z tlačítka v seznamu", bpy.ops.bb.edit_source(name="Tower") == {"FINISHED"})
    return 1.0


def step_in_edit():
    record("otevřel se zdroj modelu", bpy.data.filepath.endswith("tower.blend"), bpy.data.filepath)
    record("kolem modelu je kontext", bpy.data.collections.get(bridge.COLL_CONTEXT) is not None)
    ok, message = panel_drew("edit")
    record("panel úpravy se vykreslí bez chyby", ok, message)
    bpy.ops.wm.save_mainfile()
    window, area = view3d()
    with bpy.context.temp_override(window=window, area=area):
        record("uložit a zpět do scény", bpy.ops.bb.return_to_scene() == {"FINISHED"})
    return 1.0


def step_back_in_scene():
    record("po návratu je scéna bez souboru", bpy.data.filepath == "")
    record("Tower má zdroj", bpy.data.objects["Tower"].get(bridge.P_TIER) == "library")
    drawn.clear()
    ok, message = panel_drew("scene")
    record("panel scény po návratu", ok, message)
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
        record("(výjimka)", False, traceback.format_exc(limit=3))
        return finish()


def finish():
    with open(os.path.join(OUT, "gui.json"), "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
    bpy.ops.wm.quit_blender()
    return None


# Startovní Python z Godotu volá open_from_godot po 0,2 s; počká se déle.
bpy.app.timers.register(run_steps, first_interval=3.0, persistent=True)
