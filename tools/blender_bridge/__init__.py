"""Blender Bridge — rozmisťování objektů Godot scény v Blenderu."""

from __future__ import annotations

import os

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bridge

RETURN_MARKER = "bb_return.txt"


def _report(operator: bpy.types.Operator, error: Exception) -> set[str]:
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


class BB_OT_load_manifest(bpy.types.Operator, ImportHelper):
    """Postaví layout z manifestu vyexportovaného z Godotu"""

    bl_idname = "bb.load_manifest"
    bl_label = "Načíst manifest"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            counts = bridge.build(context.scene, self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report(
            {"WARNING"} if counts["preview"] else {"INFO"},
            "Layout: %d assetů (%d zatím jen náhled z .glb), %d zamčených proxy"
            % (counts["props"], counts["preview"], counts["proxies"]),
        )
        return {"FINISHED"}


class BB_OT_open_from_godot(bpy.types.Operator):
    """Vstupní bod, který volá Godot při „Otevřít scénu v Blenderu“.

    Zahodí výchozí startup scénu (kostka, kamera, světlo) a postaví layout
    z manifestu. Uživatel tak po spuštění nemusí nic vybírat ani načítat.
    """

    bl_idname = "bb.open_from_godot"
    bl_label = "Otevřít z Godotu"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context: bpy.types.Context) -> set[str]:
        bpy.ops.wm.read_homefile(use_empty=True)
        try:
            counts = bridge.build(bpy.context.scene, self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        bpy.context.scene.name = os.path.splitext(os.path.basename(self.filepath))[0]
        self.report(
            {"INFO"},
            "Z Godotu: %d assetů, %d zamčených proxy" % (counts["props"], counts["proxies"]),
        )
        return {"FINISHED"}


class BB_OT_rebuild(bpy.types.Operator):
    """Znovu postaví layout z posledního manifestu; zahodí neuložené přesuny"""

    bl_idname = "bb.rebuild"
    bl_label = "Přestavět z manifestu"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            counts = bridge.build(context.scene, bridge.stored_manifest_path(context.scene))
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Přestavěno: %d assetů" % counts["props"])
        return {"FINISHED"}


class BB_OT_export_manifest(bpy.types.Operator):
    """Zapíše transformace zpět do manifestu pro Godot"""

    bl_idname = "bb.export_manifest"
    bl_label = "Odeslat do Godotu"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            counts = bridge.export(context.scene)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report(
            {"INFO"},
            "Přesunuto %d, přidáno %d, smazáno %d, beze změny %d, zamčeno %d"
            % (
                counts["moved"], counts["added"], counts["removed"],
                counts["kept"], counts["pinned"],
            ),
        )
        return {"FINISHED"}


class BB_OT_reload_libraries(bpy.types.Operator):
    """Načte znovu všechny linkované zdrojové .blend soubory"""

    bl_idname = "bb.reload_libraries"
    bl_label = "Reload libraries"

    def execute(self, context: bpy.types.Context) -> set[str]:
        for library in bpy.data.libraries:
            library.reload()
        self.report({"INFO"}, "Načteno znovu: %d knihoven" % len(bpy.data.libraries))
        return {"FINISHED"}


class BB_OT_edit_source(bpy.types.Operator):
    """Uloží layout a otevře zdrojový .blend aktivního assetu"""

    bl_idname = "bb.edit_source"
    bl_label = "Upravit zdroj"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.get(bridge.P_TIER) == "library"

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object
        root = context.scene.get(bridge.S_ROOT, "")
        relative = obj.get(bridge.P_SRC_BLEND, "")
        if not root or not relative:
            return _report(self, bridge.BridgeError("asset nemá zdrojový .blend"))
        target = os.path.join(root, relative)
        if not os.path.isfile(target):
            return _report(self, bridge.BridgeError("zdroj neexistuje: %s" % target))
        if not bpy.data.filepath:
            return _report(self, bridge.BridgeError("layout musí být nejdřív uložený"))
        layout_path = bpy.data.filepath
        bpy.ops.wm.save_mainfile()
        with open(os.path.join(root, ".pipeline", RETURN_MARKER), "w", encoding="utf-8") as handle:
            handle.write(layout_path)
        bpy.ops.wm.open_mainfile(filepath=target)
        return {"FINISHED"}


class BB_OT_return_to_layout(bpy.types.Operator):
    """Vrátí se do layoutu, ze kterého jsi skočil do zdroje"""

    bl_idname = "bb.return_to_layout"
    bl_label = "Zpět do layoutu"

    def execute(self, context: bpy.types.Context) -> set[str]:
        marker = _find_return_marker()
        if marker is None:
            return _report(self, bridge.BridgeError("není kam se vracet"))
        with open(marker, "r", encoding="utf-8") as handle:
            layout_path = handle.read().strip()
        if not os.path.isfile(layout_path):
            return _report(self, bridge.BridgeError("layout neexistuje: %s" % layout_path))
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        os.remove(marker)
        bpy.ops.wm.open_mainfile(filepath=layout_path)
        return {"FINISHED"}


def _find_return_marker() -> str | None:
    """Zdrojový .blend neví, odkud se do něj skočilo; značka leží u manifestu."""
    current = os.path.dirname(os.path.abspath(bpy.data.filepath))
    while current and current != os.path.dirname(current):
        candidate = os.path.join(current, ".pipeline", RETURN_MARKER)
        if os.path.isfile(candidate):
            return candidate
        current = os.path.dirname(current)
    return None


class BB_OT_setup_exporter(bpy.types.Operator):
    """Nastaví Collection Exporter aktivního assetu na správnou cestu .glb"""

    bl_idname = "bb.setup_exporter"
    bl_label = "Nastavit glTF export"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.instance_collection is not None

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object
        collection = obj.instance_collection
        if collection.library is not None:
            return _report(self, bridge.BridgeError("linkovanou kolekci nelze konfigurovat; uprav zdroj"))
        root = context.scene.get(bridge.S_ROOT, "")
        src = str(obj.get(bridge.P_SRC, ""))
        if not root or not src:
            return _report(self, bridge.BridgeError("asset nemá cílovou cestu .glb"))
        target = os.path.join(root, src.replace("res://", "", 1))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with context.temp_override(collection=collection):
            bpy.ops.collection.exporter_add(name="IO_FH_gltf2")
        collection.exporters[-1].export_properties.filepath = target
        self.report({"INFO"}, "Export nastaven na %s" % target)
        return {"FINISHED"}


class BB_OT_promote_source(bpy.types.Operator):
    """Z modelu naimportovaného z .glb udělá zdroj pravdy, který lze upravovat"""

    bl_idname = "bb.promote_source"
    bl_label = "Vyrobit zdroj z .glb"

    destination: bpy.props.EnumProperty(
        name="Kam",
        items=(
            ("LIBRARY", "Samostatný .blend",
             "Vedle .glb; asset půjde použít i v jiných scénách"),
            ("LOCAL", "Do layoutu scény",
             "Unikátní geometrie levelu; edituje se přímo, ale layout pak drží jen jeden člověk"),
        ),
        default="LIBRARY",
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.get(bridge.P_TIER) == "none"

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = context.active_object
        root = context.scene.get(bridge.S_ROOT, "")
        if not root:
            return _report(self, bridge.BridgeError("scéna nemá načtený manifest"))
        try:
            if self.destination == "LIBRARY":
                created = bridge.promote_to_library(obj, root)
            else:
                manifest = bridge.load_manifest(bridge.stored_manifest_path(context.scene))
                created = bridge.promote_to_local(obj, root, manifest["layout_blend"])
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Zdroj vytvořen: %s" % os.path.relpath(created, root))
        return {"FINISHED"}


class BB_OT_show_sources(bpy.types.Operator):
    """Přepne viditelnost kolekce se zdrojovou geometrií"""

    bl_idname = "bb.show_sources"
    bl_label = "Zobrazit zdroje"

    def execute(self, context: bpy.types.Context) -> set[str]:
        layer = context.view_layer.layer_collection.children.get(bridge.COLL_SOURCES)
        if layer is None:
            return _report(self, bridge.BridgeError("layout nemá kolekci %s" % bridge.COLL_SOURCES))
        layer.exclude = not layer.exclude
        self.report({"INFO"}, "Zdroje %s" % ("skryté" if layer.exclude else "viditelné"))
        return {"FINISHED"}


class BB_PT_panel(bpy.types.Panel):
    bl_label = "Blender Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bridge"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        manifest = scene.get(bridge.S_MANIFEST, "")

        if not manifest:
            layout.operator(BB_OT_load_manifest.bl_idname, icon="IMPORT")
            if _find_return_marker() is not None:
                layout.operator(BB_OT_return_to_layout.bl_idname, icon="LOOP_BACK")
            return

        layout.label(text=os.path.basename(manifest))
        send = layout.row()
        send.scale_y = 1.6
        send.operator(BB_OT_export_manifest.bl_idname, icon="EXPORT")
        column = layout.column(align=True)
        column.operator(BB_OT_rebuild.bl_idname, icon="FILE_REFRESH")
        column.operator(BB_OT_reload_libraries.bl_idname, icon="LINKED")
        layout.operator(BB_OT_load_manifest.bl_idname, text="Načíst jiný manifest", icon="IMPORT")

        obj = context.active_object
        if obj is None or bridge.P_ID not in obj:
            return
        box = layout.box()
        box.label(text=obj.name, icon="OBJECT_DATA")
        box.label(text="tier: %s" % obj.get(bridge.P_TIER, "?"))
        box.label(text="godot: %s" % obj.get(bridge.P_PATH, "?"))
        box.operator(BB_OT_edit_source.bl_idname, icon="FILE_BLEND")
        box.operator(BB_OT_setup_exporter.bl_idname, icon="EXPORT")
        box.operator(BB_OT_promote_source.bl_idname, icon="FILE_NEW")
        box.operator(BB_OT_show_sources.bl_idname, icon="OUTLINER")


_CLASSES = (
    BB_OT_load_manifest,
    BB_OT_open_from_godot,
    BB_OT_rebuild,
    BB_OT_export_manifest,
    BB_OT_reload_libraries,
    BB_OT_edit_source,
    BB_OT_return_to_layout,
    BB_OT_setup_exporter,
    BB_OT_promote_source,
    BB_OT_show_sources,
    BB_PT_panel,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
