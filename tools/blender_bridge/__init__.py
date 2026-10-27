"""Blender Bridge: lay out Godot scenes and edit their models in Blender.

Two modes:

* **Scene**: Blender opened from Godot. The layout is built from the manifest
  and nothing is saved; the .tscn is the source of truth. "Send to Godot"
  writes the changes back.
* **Source editing**: the .blend of one asset is open. Locked context from the
  scene surrounds it, and saving regenerates the .glb. "Save and return to
  scene" rebuilds the scene from the manifest.
"""

from __future__ import annotations

import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bridge


def _report(operator: bpy.types.Operator, error: Exception) -> set[str]:
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


def _open_scene(manifest: str) -> None:
    bpy.ops.wm.read_homefile(use_empty=True)
    # After read_homefile the new scene is in the window; from a timer or a
    # handler bpy.context wouldn't point to the 3D view (see bridge.ui_context).
    with bpy.context.temp_override(**bridge.ui_context()):
        scene = bpy.context.scene
        bridge.build(scene, manifest)
        scene.name = os.path.splitext(os.path.basename(manifest))[0]
    _frame_models()


def _frame_models() -> None:
    """After opening, frames the models and extends the clip distance, since
    terrain can be kilometres wide and the default view clip is 1 km."""
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
    """The model from a list button, otherwise the active object."""
    if name:
        return bpy.data.objects.get(name)
    return context.active_object


# ----------------------------------------------------------------- scene


class BB_OT_open_from_godot(bpy.types.Operator):
    """Entry point Godot calls on "Open in Blender\""""

    bl_idname = "bb.open_from_godot"
    bl_label = "Open from Godot"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_load_manifest(bpy.types.Operator, ImportHelper):
    """Build the scene from a manifest by hand, without launching from Godot"""

    bl_idname = "bb.load_manifest"
    bl_label = "Load manifest"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_export_manifest(bpy.types.Operator):
    """Write the changes back; Godot loads them automatically"""

    bl_idname = "bb.export_manifest"
    bl_label = "Send to Godot"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            counts = bridge.export(context.scene)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report(
            {"INFO"},
            "Sent: moved %d, added %d, removed %d"
            % (counts["moved"], counts["added"], counts["removed"]),
        )
        return {"FINISHED"}


class BB_OT_rebuild(bpy.types.Operator):
    """Reload the scene from Godot's last manifest; unsent changes are discarded"""

    bl_idname = "bb.rebuild"
    bl_label = "Reload from Godot"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            _open_scene(bridge.stored_manifest_path(context.scene))
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


class BB_OT_promote_source(bpy.types.Operator):
    """Turn a model imported from .glb into its own editable .blend next to
    the asset"""

    bl_idname = "bb.promote_source"
    bl_label = "Make source from .glb"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or obj.get(bridge.P_TIER) != "none":
            return _report(self, bridge.BridgeError("select a model that is only a .glb preview"))
        root = context.scene.get(bridge.S_ROOT, "")
        try:
            created = bridge.promote_to_library(obj, root)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Source created: %s" % os.path.relpath(created, root))
        return {"FINISHED"}


class BB_OT_edit_source(bpy.types.Operator):
    """Send changes to Godot and open the model's source .blend"""

    bl_idname = "bb.edit_source"
    bl_label = "Edit model"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or obj.get(bridge.P_TIER) != "library":
            return _report(self, bridge.BridgeError("the model has no source .blend; make one first"))
        try:
            source = bridge.begin_edit(context.scene, obj)
        except bridge.BridgeError as error:
            return _report(self, error)
        # The scene isn't saved anywhere; the changes are already in the manifest.
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
        return {"FINISHED"}


class BB_OT_choose_source(bpy.types.Operator, ImportHelper):
    """Pick an existing .blend as the model's source (for all its instances)"""

    bl_idname = "bb.choose_source"
    bl_label = "Pick source…"

    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})
    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        obj = _target(context, self.name)
        root = context.scene.get(bridge.S_ROOT, "")
        if obj is not None and root:
            # The browser starts next to the asset, where the source lives by convention.
            self.filepath = os.path.join(root, bridge.expected_source(str(obj.get(bridge.P_SRC, ""))))
        return ImportHelper.invoke(self, context, event)

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or bridge.P_ID not in obj:
            return _report(self, bridge.BridgeError("select a model"))
        try:
            path, personal = bridge.choose_source(context.scene, str(obj.get(bridge.P_SRC, "")), self.filepath)
        except (bridge.BridgeError, OSError) as error:
            return _report(self, error)
        if personal:
            self.report({"WARNING"}, "Source outside the project: it only applies to you, others won't see it")
            _notify_personal_source(context, path)
        else:
            self.report({"INFO"}, "Source: %s" % path)
        return {"FINISHED"}


PERSONAL_SOURCE_NOTICE = (
    "The file is outside the Godot project.",
    "The path is not saved in the project, it only applies to you.",
    "Others on the team won't see this source and can't edit the model;",
    "they will still see only the .glb.",
    "To give everyone the source, put the .blend inside the project and pick it again.",
)


def _notify_personal_source(context: bpy.types.Context, path: str) -> None:
    if bpy.app.background or context.window_manager is None:
        return

    def draw(menu: bpy.types.Menu, _context: bpy.types.Context) -> None:
        menu.layout.label(text=path, icon="FILE_BLEND")
        for line in PERSONAL_SOURCE_NOTICE:
            menu.layout.label(text=line)

    context.window_manager.popup_menu(draw, title="Source only for you", icon="ERROR")


class BB_OT_clear_source(bpy.types.Operator):
    """Clear the hand-picked source; the .blend next to the asset applies again, otherwise the preview"""

    bl_idname = "bb.clear_source"
    bl_label = "Clear source"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or bridge.P_ID not in obj:
            return _report(self, bridge.BridgeError("select a model"))
        bridge.clear_source(context.scene, str(obj.get(bridge.P_SRC, "")))
        return {"FINISHED"}


class BB_OT_select_model(bpy.types.Operator):
    """Select the model and frame it in the view"""

    bl_idname = "bb.select_model"
    bl_label = "Select model"
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


# -------------------------------------------------------- source editing


class BB_OT_return_to_scene(bpy.types.Operator):
    """Save the model (which regenerates the .glb) and return to the scene"""

    bl_idname = "bb.return_to_scene"
    bl_label = "Save and return to scene"

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


class BB_OT_export_now(bpy.types.Operator):
    """Regenerate the .glb now, without saving the .blend"""

    bl_idname = "bb.export_now"
    bl_label = "Export now"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        session = bridge.edit_session()
        return session is not None and bridge.collection_has_exporter(session)

    def execute(self, context: bpy.types.Context) -> set[str]:
        session = bridge.edit_session()
        bridge.export_collection(bridge.session_collection(session))
        self.report({"INFO"}, "Exported: %s" % session["asset"])
        return {"FINISHED"}


class BB_OT_reset_export(bpy.types.Operator):
    """Reset the model's export settings to the defaults from the add-on preferences"""

    bl_idname = "bb.reset_export"
    bl_label = "Reset to defaults"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        session = bridge.edit_session()
        return session is not None and bridge.collection_has_exporter(session)

    def execute(self, context: bpy.types.Context) -> set[str]:
        session = bridge.edit_session()
        bridge.apply_export_settings(bridge.session_collection(session), bridge.export_defaults())
        return {"FINISHED"}


# Labels of the export options in the panel and preferences (order = UI order).
EXPORT_LABELS = (
    ("export_apply", "Apply modifiers"),
    ("export_yup", "+Y up"),
    ("export_materials", "Materials"),
    ("export_image_format", "Images"),
    ("export_animations", "Animation"),
    ("export_skins", "Skinning"),
    ("export_morph", "Shape keys"),
    ("export_tangents", "Tangents"),
    ("export_extras", "Custom properties"),
    ("export_draco_mesh_compression_enable", "Draco compression"),
)


def _draw_export_options(layout: bpy.types.UILayout, data: object) -> None:
    column = layout.column(align=True)
    for key, label in EXPORT_LABELS:
        if hasattr(data, key):
            column.prop(data, key, text=label)


class BB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    export_apply: BoolProperty(
        name="Apply modifiers", default=True,
        description="Export geometry after modifiers (except armature), as seen in the viewport",
    )
    export_yup: BoolProperty(name="+Y up", default=True)
    export_materials: EnumProperty(
        name="Materials", default="EXPORT",
        items=(
            ("EXPORT", "Export", "Materials including textures"),
            ("PLACEHOLDER", "Placeholder", "Material slots only, no data"),
            ("NONE", "None", "No materials"),
        ),
    )
    export_image_format: EnumProperty(
        name="Images", default="AUTO",
        items=(
            ("AUTO", "Automatic", "PNG, or JPEG if the source is JPEG"),
            ("JPEG", "JPEG", "Smaller, lossy"),
            ("WEBP", "WebP", "Smaller, supported by Godot"),
            ("NONE", "None", "Textures are not exported"),
        ),
    )
    export_animations: BoolProperty(name="Animation", default=True)
    export_skins: BoolProperty(name="Skinning", default=True)
    export_morph: BoolProperty(name="Shape keys", default=True)
    export_tangents: BoolProperty(name="Tangents", default=False)
    export_extras: BoolProperty(name="Custom properties", default=False)
    export_draco_mesh_compression_enable: BoolProperty(name="Draco compression", default=False)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Default .glb export for sources", icon="EXPORT")
        layout.label(text="Applies to new sources and to sources that don't have their own settings yet.")
        layout.label(text="A specific model is set up in the Bridge panel while editing it.")
        _draw_export_options(layout, self)


# --------------------------------------------------------------- handlers


@persistent
def _on_load_post(_: object) -> None:
    session = bridge.edit_session()
    if session is None:
        return
    collection = bridge.session_collection(session)
    if collection is not None:
        # libraries.write saves the collection without a scene; without this
        # nothing would be visible after opening.
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
            self.layout.label(text="Open a scene from Godot with the Blender button.")
            self.layout.operator(BB_OT_load_manifest.bl_idname, icon="IMPORT")

    def _draw_scene(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        layout.label(text="Scene: %s" % scene.name, icon="SCENE_DATA")
        send = layout.row()
        send.scale_y = 1.6
        send.operator(BB_OT_export_manifest.bl_idname, icon="EXPORT")
        layout.operator(BB_OT_rebuild.bl_idname, icon="FILE_REFRESH")

        warnings = list(scene.get(bridge.S_WARNINGS, []))
        if warnings:
            box = layout.box()
            box.alert = True
            box.label(text="Loaded with problems:", icon="ERROR")
            for message in warnings:
                box.label(text=message)

        box = layout.box()
        models = bridge.scene_models(scene)
        shown = bridge.filter_models(models, scene.bb_model_filter)
        header = box.row()
        header.label(text="Models", icon="OUTLINER_COLLECTION")
        header.label(text="%d of %d" % (len(shown), len(models)) if len(shown) != len(models) else str(len(models)))
        box.prop(scene, "bb_model_filter", text="", icon="VIEWZOOM")
        if not shown:
            box.label(text="Nothing matches the search.")
        for obj in shown:
            row = box.row(align=True)
            pick = row.operator(
                BB_OT_select_model.bl_idname, text=obj.name, emboss=obj == context.active_object,
                icon="LINKED" if obj.get(bridge.P_TIER) == "library" else "FILE_3D",
            )
            pick.name = obj.name
            if obj.get(bridge.P_TIER) == "library":
                row.operator(BB_OT_edit_source.bl_idname, text="Edit", icon="EDITMODE_HLT").name = obj.name
            else:
                row.operator(BB_OT_promote_source.bl_idname, text="Make source", icon="FILE_NEW").name = obj.name
        if any(o.get(bridge.P_TIER) != "library" for o in models):
            box.label(text="Without a source, a model is only a .glb preview.", icon="INFO")

    def _draw_edit(self, session: dict) -> None:
        layout = self.layout
        layout.label(text="Editing: %s" % os.path.basename(session["asset"]), icon="EDITMODE_HLT")
        back = layout.row()
        back.scale_y = 1.6
        back.operator(BB_OT_return_to_scene.bl_idname, icon="LOOP_BACK")
        layout.label(text="Ctrl+S saves the model and regenerates the .glb", icon="CHECKMARK")
        column = layout.column(align=True)
        column.label(text="Export: %s" % session["asset"].replace("res://", "", 1))
        column.label(text="The surrounding scene is only for reference and isn't saved.")

        collection = bridge.session_collection(session)
        exporter = bridge.gltf_exporter(collection) if collection is not None else None
        if exporter is None:
            return
        box = layout.box()
        box.label(text="Export settings", icon="SETTINGS")
        _draw_export_options(box, exporter.export_properties)
        row = box.row(align=True)
        row.operator(BB_OT_export_now.bl_idname, icon="EXPORT")
        row.operator(BB_OT_reset_export.bl_idname, icon="LOOP_BACK")
        box.label(text="Saved with the model; other options in Collection › Exporters.", icon="INFO")


class BB_PT_detail(bpy.types.Panel):
    """Details of the selected object: where it comes from and what happens to it."""

    bl_label = "Detail"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bridge"
    bl_parent_id = "BB_PT_panel"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.scene.get(bridge.S_MANIFEST) is not None and bridge.edit_session() is None

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        obj = context.active_object
        if obj is None:
            layout.label(text="Select an object.")
            return
        kind, rows = bridge.describe(obj)
        if kind == "model":
            layout.label(text=obj.name, icon="OBJECT_DATA")
            actions = layout.row(align=True)
            if obj.get(bridge.P_TIER) == "library":
                actions.operator(BB_OT_edit_source.bl_idname, text="Edit", icon="EDITMODE_HLT").name = obj.name
            else:
                actions.operator(BB_OT_promote_source.bl_idname, text="Make source", icon="FILE_NEW").name = obj.name
            actions.operator(BB_OT_choose_source.bl_idname, icon="FILEBROWSER").name = obj.name
            choice = bridge.source_choice(context.scene.get(bridge.S_ROOT, ""), str(obj.get(bridge.P_SRC, "")))
            if choice == "personal":
                note = layout.column(align=True)
                note.alert = True
                note.label(text="Source is outside the project, only for you.", icon="ERROR")
                note.label(text="Others on the team don't have it.")
            if choice:
                layout.operator(BB_OT_clear_source.bl_idname, icon="X").name = obj.name
        elif kind == "godot":
            layout.label(text="%s (from Godot)" % obj.name, icon="LOCKED")
            layout.label(text="For reference only, changes aren't sent.")
        else:
            layout.label(text="%s (helper object)" % obj.name, icon="GHOST_ENABLED")
            layout.label(text="Not sent to Godot and gone next time.")
        column = layout.column(align=True)
        for label, value in rows:
            split = column.split(factor=0.35)
            split.label(text=label)
            split.label(text=value)


_CLASSES = (
    BB_OT_open_from_godot,
    BB_OT_load_manifest,
    BB_OT_export_manifest,
    BB_OT_rebuild,
    BB_OT_promote_source,
    BB_OT_edit_source,
    BB_OT_choose_source,
    BB_OT_clear_source,
    BB_OT_select_model,
    BB_OT_return_to_scene,
    BB_OT_export_now,
    BB_OT_reset_export,
    BB_Preferences,
    BB_PT_panel,
    BB_PT_detail,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bb_model_filter = StringProperty(
        name="Search",
        description="Filter the model list by name, Godot path or asset",

        options={"TEXTEDIT_UPDATE", "SKIP_SAVE"},
    )
    for handlers, callback in _HANDLERS:
        handlers.append(callback)


def unregister() -> None:
    del bpy.types.Scene.bb_model_filter
    for handlers, callback in _HANDLERS:
        if callback in handlers:
            handlers.remove(callback)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
