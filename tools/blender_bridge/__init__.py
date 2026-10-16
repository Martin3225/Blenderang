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
    bridge.build(bpy.context.scene, manifest)
    bpy.context.scene.name = os.path.splitext(os.path.basename(manifest))[0]


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
    """Zahodí neodeslané přesuny a postaví scénu znovu z manifestu"""

    bl_idname = "bb.rebuild"
    bl_label = "Zahodit změny"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(bridge.stored_manifest_path(context.scene))
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_promote_source(bpy.types.Operator):
    """Z modelu naimportovaného z .glb udělá samostatný .blend vedle assetu"""

    bl_idname = "bb.promote_source"
    bl_label = "Vyrobit zdroj z .glb"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.get(bridge.P_TIER) == "none"

    def execute(self, context: bpy.types.Context) -> set[str]:
        root = context.scene.get(bridge.S_ROOT, "")
        try:
            created = bridge.promote_to_library(context.active_object, root)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Zdroj vytvořen: %s" % os.path.relpath(created, root))
        return {"FINISHED"}


class BB_OT_edit_source(bpy.types.Operator):
    """Odešle přesuny do Godotu a otevře zdrojový .blend assetu"""

    bl_idname = "bb.edit_source"
    bl_label = "Upravit model"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.get(bridge.P_TIER) == "library"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            source = bridge.begin_edit(context.scene, context.active_object)
        except bridge.BridgeError as error:
            return _report(self, error)
        # Scéna se nikam neukládá, přesuny už jsou v manifestu.
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
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


class BB_OT_setup_exporter(bpy.types.Operator):
    """Nastaví export kolekce do .glb assetu, aby ho uložení přegenerovalo"""

    bl_idname = "bb.setup_exporter"
    bl_label = "Nastavit glTF export"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bridge.edit_session() is not None

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            target = bridge.setup_session_exporter(bridge.edit_session())
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Export nastaven na %s" % target)
        return {"FINISHED"}


class BB_OT_show_sources(bpy.types.Operator):
    """Přepne viditelnost kolekce se zdrojovou geometrií"""

    bl_idname = "bb.show_sources"
    bl_label = "Zobrazit zdroje"

    def execute(self, context: bpy.types.Context) -> set[str]:
        layer = context.view_layer.layer_collection.children.get(bridge.COLL_SOURCES)
        if layer is None:
            return _report(self, bridge.BridgeError("scéna nemá kolekci %s" % bridge.COLL_SOURCES))
        layer.exclude = not layer.exclude
        return {"FINISHED"}


# --------------------------------------------------------------- handlery


@persistent
def _on_load_post(_: object) -> None:
    session = bridge.edit_session()
    if session is None:
        return
    collection = bpy.data.collections.get(session.get("collection", ""))
    # libraries.write zapíše kolekci bez scény; bez tohohle by po otevření
    # nebylo nic vidět.
    if collection is not None and collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(collection)
    bridge.build_context(session)


@persistent
def _on_save_pre(_: object) -> None:
    bridge.clear_context()


@persistent
def _on_save_post(_: object) -> None:
    session = bridge.edit_session()
    if session is None:
        return
    if bridge.collection_has_exporter(session):
        bpy.ops.wm.collection_export_all()
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
        row = layout.row(align=True)
        row.operator(BB_OT_rebuild.bl_idname, icon="LOOP_BACK")
        row.operator(BB_OT_show_sources.bl_idname, icon="OUTLINER")

        obj = context.active_object
        if obj is None or bridge.P_ID not in obj:
            return
        box = layout.box()
        box.label(text=obj.name, icon="OBJECT_DATA")
        if obj.get(bridge.P_TIER) == "library":
            box.operator(BB_OT_edit_source.bl_idname, icon="EDITMODE_HLT")
        else:
            box.label(text="Jen náhled z .glb, úpravy se neuloží.", icon="INFO")
            box.operator(BB_OT_promote_source.bl_idname, icon="FILE_NEW")

    def _draw_edit(self, session: dict) -> None:
        layout = self.layout
        layout.label(text="Úprava: %s" % os.path.basename(session["asset"]), icon="EDITMODE_HLT")
        back = layout.row()
        back.scale_y = 1.6
        back.operator(BB_OT_return_to_scene.bl_idname, icon="LOOP_BACK")
        if bridge.collection_has_exporter(session):
            layout.label(text="Ctrl+S přegeneruje .glb", icon="CHECKMARK")
        else:
            layout.operator(BB_OT_setup_exporter.bl_idname, icon="EXPORT")


_CLASSES = (
    BB_OT_open_from_godot,
    BB_OT_load_manifest,
    BB_OT_export_manifest,
    BB_OT_rebuild,
    BB_OT_promote_source,
    BB_OT_edit_source,
    BB_OT_return_to_scene,
    BB_OT_setup_exporter,
    BB_OT_show_sources,
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
