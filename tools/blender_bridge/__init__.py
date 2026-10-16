"""Blender Bridge — rozmisťování objektů Godot scény v Blenderu.

Dva režimy:

* **Scéna** — Blender otevřený z Godotu. Layout se staví z manifestu, nic se
  neukládá; pravdou je .tscn. „Odeslat do Godotu“ zapíše přesuny zpět.
* **Úprava zdroje** — otevřený .blend jednoho assetu. Kolem něj je zamčený
  kontext ze scény, uložení regeneruje .glb. „Zpět do scény“ postaví scénu
  znovu z manifestu.
"""

from __future__ import annotations

import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bridge


def _report(operator: bpy.types.Operator, error: Exception) -> set[str]:
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


def _open_scene(manifest: str) -> None:
    bpy.ops.wm.read_homefile(use_empty=True)
    # Po read_homefile je nová scéna v okně; z časovače ani z handleru by
    # bpy.context neukazoval na 3D pohled (viz bridge.ui_context).
    with bpy.context.temp_override(**bridge.ui_context()):
        scene = bpy.context.scene
        bridge.build(scene, manifest)
        scene.name = os.path.splitext(os.path.basename(manifest))[0]
    _frame_models()


def _frame_models() -> None:
    """Po otevření zaměří pohled na modely a prodlouží dohled — terén má
    kilometry a výchozí ořez pohledu je 1 km."""
    if bpy.app.background or bpy.context.window_manager is None:
        return
    layout = bpy.data.collections.get(bridge.COLL_LAYOUT)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            area.spaces.active.clip_end = max(area.spaces.active.clip_end, 20000.0)
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None or layout is None or not layout.objects:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.object.select_all(action="DESELECT")
                for obj in layout.objects:
                    obj.select_set(True)
                bpy.ops.view3d.view_selected()
                bpy.ops.object.select_all(action="DESELECT")


def _target(context: bpy.types.Context, name: str) -> bpy.types.Object | None:
    """Model z tlačítka v seznamu, jinak aktivní objekt."""
    if name:
        return bpy.data.objects.get(name)
    return context.active_object


# ----------------------------------------------------------------- scéna


class BB_OT_open_from_godot(bpy.types.Operator):
    """Vstupní bod, který volá Godot při „Otevřít v Blenderu“"""

    bl_idname = "bb.open_from_godot"
    bl_label = "Otevřít z Godotu"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_load_manifest(bpy.types.Operator, ImportHelper):
    """Postaví scénu z manifestu ručně, bez spuštění z Godotu"""

    bl_idname = "bb.load_manifest"
    bl_label = "Načíst manifest"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_export_manifest(bpy.types.Operator):
    """Zapíše přesuny zpět; Godot si je načte sám"""

    bl_idname = "bb.export_manifest"
    bl_label = "Odeslat do Godotu"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            counts = bridge.export(context.scene)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report(
            {"INFO"},
            "Odesláno: přesunuto %d, přidáno %d, smazáno %d"
            % (counts["moved"], counts["added"], counts["removed"]),
        )
        return {"FINISHED"}


class BB_OT_rebuild(bpy.types.Operator):
    """Načte scénu znovu z posledního manifestu z Godotu; neodeslané změny zahodí"""

    bl_idname = "bb.rebuild"
    bl_label = "Znovu načíst z Godotu"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(bridge.stored_manifest_path(context.scene))
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_promote_source(bpy.types.Operator):
    """Z modelu naimportovaného z .glb udělá samostatný .blend vedle assetu,
    který jde upravovat"""

    bl_idname = "bb.promote_source"
    bl_label = "Vyrobit zdroj z .glb"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or obj.get(bridge.P_TIER) != "none":
            return _report(self, bridge.BridgeError("vyber model, který je jen náhled z .glb"))
        root = context.scene.get(bridge.S_ROOT, "")
        try:
            created = bridge.promote_to_library(obj, root)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Zdroj vytvořen: %s" % os.path.relpath(created, root))
        return {"FINISHED"}


class BB_OT_edit_source(bpy.types.Operator):
    """Odešle přesuny do Godotu a otevře zdrojový .blend modelu"""

    bl_idname = "bb.edit_source"
    bl_label = "Upravit model"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or obj.get(bridge.P_TIER) != "library":
            return _report(self, bridge.BridgeError("model nemá zdrojový .blend; nejdřív ho vyrob"))
        try:
            source = bridge.begin_edit(context.scene, obj)
        except bridge.BridgeError as error:
            return _report(self, error)
        # Scéna se nikam neukládá, přesuny už jsou v manifestu.
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
        return {"FINISHED"}


class BB_OT_select_model(bpy.types.Operator):
    """Vybere model a zaměří na něj pohled"""

    bl_idname = "bb.select_model"
    bl_label = "Vybrat model"
    bl_options = {"INTERNAL"}

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {"CANCELLED"}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        if context.area is not None and context.area.type == "VIEW_3D":
            bpy.ops.view3d.view_selected()
        return {"FINISHED"}


# --------------------------------------------------------- úprava zdroje


class BB_OT_return_to_scene(bpy.types.Operator):
    """Uloží model (tím se přegeneruje .glb) a vrátí se do scény"""

    bl_idname = "bb.return_to_scene"
    bl_label = "Uložit a zpět do scény"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bridge.edit_session() is not None

    def execute(self, context: bpy.types.Context) -> set[str]:
        session = bridge.edit_session()
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        try:
            _open_scene(bridge.end_edit(session))
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


# --------------------------------------------------------------- handlery


@persistent
def _on_load_post(_: object) -> None:
    session = bridge.edit_session()
    if session is None:
        return
    collection = bridge.session_collection(session)
    if collection is not None:
        # libraries.write zapíše kolekci bez scény; bez tohohle by po otevření
        # nebylo nic vidět.
        if collection.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(collection)
        bridge.setup_session_exporter(session)
    with bpy.context.temp_override(**bridge.ui_context()):
        bridge.build_context(session)


@persistent
def _on_save_pre(_: object) -> None:
    bridge.clear_context()


@persistent
def _on_save_post(_: object) -> None:
    session = bridge.edit_session()
    if session is None:
        return
    collection = bridge.session_collection(session)
    if collection is not None and bridge.collection_has_exporter(session):
        bridge.export_collection(collection)
    with bpy.context.temp_override(**bridge.ui_context()):
        bridge.build_context(session)


_HANDLERS = (
    (bpy.app.handlers.load_post, _on_load_post),
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
)


# ------------------------------------------------------------------ panel


class BB_PT_panel(bpy.types.Panel):
    bl_label = "Blender Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bridge"

    def draw(self, context: bpy.types.Context) -> None:
        session = bridge.edit_session()
        if session is not None:
            self._draw_edit(session)
        elif context.scene.get(bridge.S_MANIFEST):
            self._draw_scene(context)
        else:
            self.layout.label(text="Otevři scénu z Godotu tlačítkem Blender.")
            self.layout.operator(BB_OT_load_manifest.bl_idname, icon="IMPORT")

    def _draw_scene(self, context: bpy.types.Context) -> None:
        layout = self.layout
        send = layout.row()
        send.scale_y = 1.6
        send.operator(BB_OT_export_manifest.bl_idname, icon="EXPORT")
        layout.operator(BB_OT_rebuild.bl_idname, icon="FILE_REFRESH")

        box = layout.box()
        box.label(text="Modely", icon="OUTLINER_COLLECTION")
        for obj in bridge.scene_models(context.scene):
            row = box.row(align=True)
            pick = row.operator(
                BB_OT_select_model.bl_idname, text=obj.name, emboss=obj == context.active_object,
                icon="LINKED" if obj.get(bridge.P_TIER) == "library" else "FILE_3D",
            )
            pick.name = obj.name
            if obj.get(bridge.P_TIER) == "library":
                row.operator(BB_OT_edit_source.bl_idname, text="Upravit", icon="EDITMODE_HLT").name = obj.name
            else:
                row.operator(BB_OT_promote_source.bl_idname, text="Vyrobit zdroj", icon="FILE_NEW").name = obj.name
        if any(o.get(bridge.P_TIER) != "library" for o in bridge.scene_models(context.scene)):
            box.label(text="Bez zdroje je model jen náhled z .glb.", icon="INFO")

    def _draw_edit(self, session: dict) -> None:
        layout = self.layout
        layout.label(text="Úprava: %s" % os.path.basename(session["asset"]), icon="EDITMODE_HLT")
        back = layout.row()
        back.scale_y = 1.6
        back.operator(BB_OT_return_to_scene.bl_idname, icon="LOOP_BACK")
        layout.label(text="Ctrl+S uloží model a přegeneruje .glb", icon="CHECKMARK")


_CLASSES = (
    BB_OT_open_from_godot,
    BB_OT_load_manifest,
    BB_OT_export_manifest,
    BB_OT_rebuild,
    BB_OT_promote_source,
    BB_OT_edit_source,
    BB_OT_select_model,
    BB_OT_return_to_scene,
    BB_PT_panel,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    for handlers, callback in _HANDLERS:
        handlers.append(callback)


def unregister() -> None:
    for handlers, callback in _HANDLERS:
        if callback in handlers:
            handlers.remove(callback)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
