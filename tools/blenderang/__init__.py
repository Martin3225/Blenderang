"""Blenderang: lay out Godot scenes and edit their models in Blender.

Two modes:

* **Scene**: Blender opened from Godot. The layout is built from the manifest
  and nothing is saved; the .tscn is the source of truth. "Send to Godot"
  writes the changes back.
* **Source editing**: the .blend of one asset is open. Locked context from the
  scene surrounds it, and saving regenerates the .glb. "Save and return to
  scene" rebuilds the scene from the manifest.
"""

from __future__ import annotations

import json
import os
import textwrap
import traceback

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import bridge


def _report(operator: bpy.types.Operator, error: Exception) -> set[str]:
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


# Why the last opening of a scene from Godot failed, for the panel: the popup
# goes away, and the failed scene leaves an empty file behind.
_OPEN_ERROR = {"message": ""}


def _open_scene(manifest: str) -> None:
    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        # After read_homefile the new scene is in the window; from a timer or a
        # handler bpy.context wouldn't point to the 3D view (see bridge.ui_context).
        with bpy.context.temp_override(**bridge.ui_context()):
            scene = bpy.context.scene
            bridge.build(scene, manifest)
            scene.name = os.path.splitext(os.path.basename(manifest))[0]
    except Exception as error:   # noqa: BLE001 — any failure must reach the user, not only the console
        _OPEN_ERROR["message"] = _open_failure(manifest, error)
        if not bpy.app.background:
            # Deferred: opening the sidebar inside the operator that just ran
            # read_homefile crashes Blender (5.3).
            bpy.app.timers.register(_show_panel, first_interval=0.1)
        raise bridge.BridgeError(_OPEN_ERROR["message"]) from error
    _frame_models()


def _open_failure(manifest: str, error: Exception) -> str:
    """A readable reason why the scene couldn't be built from ``manifest``."""
    if isinstance(error, bridge.BridgeError):
        return str(error)
    if isinstance(error, json.JSONDecodeError):
        return "the manifest %s is not valid JSON (%s)" % (manifest, error)
    if isinstance(error, OSError):
        return "cannot read %s (%s)" % (manifest, error.strerror or error)
    traceback.print_exc()
    return "unexpected error while building %s: %s: %s (details in the system console)" % (
        os.path.basename(manifest), type(error).__name__, error)


def _show_panel(attempts: int = 20) -> float | None:
    """Opens the sidebar on the Blenderang tab, where the error stays after the
    popup goes away. A timer: the tab can be picked only once the opened sidebar
    has drawn, until then the property is read-only."""
    pending = False
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            area.spaces.active.show_region_ui = True
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = BB_PT_panel.bl_category
                    except AttributeError:
                        pending = True
    if pending and attempts > 1:
        bpy.app.timers.register(lambda: _show_panel(attempts - 1), first_interval=0.1)
    return None


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
    """Turn a model imported from .glb into its own editable .blend"""

    bl_idname = "bb.promote_source"
    bl_label = "Make source from .glb"

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context: bpy.types.Context, properties: bpy.types.OperatorProperties) -> str:
        obj = _target(context, properties.name)
        if obj is None or bridge.P_SRC not in obj:
            return cls.__doc__
        target = bridge.new_source(context.scene.get(bridge.S_ROOT, ""), str(obj[bridge.P_SRC]))
        if target.startswith(bridge.MODELS_PREFIX):
            return "Create %s in the models folder from the .glb preview" % target[len(bridge.MODELS_PREFIX):]
        return "Create %s next to the asset from the .glb preview" % target

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj = _target(context, self.name)
        if obj is None or obj.get(bridge.P_TIER) != "none":
            return _report(self, bridge.BridgeError("select a model that is only a .glb preview"))
        root = context.scene.get(bridge.S_ROOT, "")
        try:
            created = bridge.promote_to_library(obj, root)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Source created: %s" % created)
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
            self.filepath = _pick_start(root, obj)
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


def _pick_start(root: str, obj: bpy.types.Object) -> str:
    """Where the file browser starts: the current source, otherwise the models
    folder, otherwise next to the asset where the source lives by convention."""
    stored = str(obj.get(bridge.P_SRC_BLEND, ""))
    current = bridge.source_abs(root, stored) if stored else ""
    if current:
        return current
    folder = bridge.models_folder(root)
    if folder:
        return folder + os.sep
    return os.path.join(root, bridge.expected_source(str(obj.get(bridge.P_SRC, ""))))


PERSONAL_SOURCE_NOTICE = (
    "The file is outside the Godot project and the models folder.",
    "The path is not saved in the project, it only applies to you.",
    "Others on the team won't see this source and can't edit the model;",
    "they will still see only the .glb.",
    "To give everyone the source, put the .blend inside the project",
    "or the models folder and pick it again.",
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


class BB_OT_set_models_folder(bpy.types.Operator):
    """Where the team's shared folder of source .blend files is on this disk.
    Saved only for you; shared paths into it are relative, so they work for everyone"""

    bl_idname = "bb.set_models_folder"
    bl_label = "Set models folder…"

    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})
    clear: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if self.clear:
            return self.execute(context)
        current = bridge.models_folder(context.scene.get(bridge.S_ROOT, ""))
        if current:
            self.directory = current + os.sep
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            bridge.set_models_folder(context.scene, "" if self.clear else self.directory)
        except (bridge.BridgeError, OSError) as error:
            return _report(self, error)
        root = context.scene.get(bridge.S_ROOT, "")
        self.report({"INFO"}, "Models folder: %s" % (bridge.models_folder(root) or "not set"))
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


class BB_MT_model_pie(bpy.types.Menu):
    bl_idname = "BB_MT_model_pie"
    bl_label = "Blenderang model"

    def draw(self, context: bpy.types.Context) -> None:
        obj = context.active_object
        # Pie slots fill in the order left, right, bottom, top.
        pie = self.layout.menu_pie()
        pie.operator(BB_OT_choose_source.bl_idname, icon="FILEBROWSER").name = obj.name
        if bridge.source_choice(context.scene.get(bridge.S_ROOT, ""), str(obj.get(bridge.P_SRC, ""))):
            pie.operator(BB_OT_clear_source.bl_idname, icon="X").name = obj.name
        else:
            pie.separator()
        pie.separator()
        if obj.get(bridge.P_TIER) == "library":
            pie.operator(BB_OT_edit_source.bl_idname, text="Edit model", icon="EDITMODE_HLT").name = obj.name
        else:
            pie.operator(BB_OT_promote_source.bl_idname, text="Make source", icon="FILE_NEW").name = obj.name


class BB_OT_model_pie(bpy.types.Operator):
    """Blenderang actions for the active model. Bound to Tab in the scene, where
    Blender would otherwise offer to open or make local the linked source"""

    bl_idname = "bb.model_pie"
    bl_label = "Blenderang model menu"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return (obj is not None and bridge.P_ID in obj and context.mode == "OBJECT"
                and context.scene.get(bridge.S_MANIFEST) is not None)

    def execute(self, context: bpy.types.Context) -> set[str]:
        bpy.ops.wm.call_menu_pie(name=BB_MT_model_pie.bl_idname)
        return {"FINISHED"}


# -------------------------------------------------------- source editing


class BB_OT_open_source(bpy.types.Operator):
    """Entry point Godot calls on "Open source in Blender": the model's .blend
    without a scene around it; saving regenerates the asset"""

    bl_idname = "bb.open_source"
    bl_label = "Open source from Godot"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(subtype="FILE_PATH")
    asset: StringProperty()
    root: StringProperty(subtype="DIR_PATH")

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            source = bridge.begin_source_edit(self.root, self.asset, self.filepath)
        except bridge.BridgeError as error:
            return _report(self, error)
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
        return {"FINISHED"}


class BB_OT_return_to_scene(bpy.types.Operator):
    """Save the model (which regenerates the .glb) and return to the scene"""

    bl_idname = "bb.return_to_scene"
    bl_label = "Save and return to scene"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        session = bridge.edit_session()
        return session is not None and bool(session["manifest"])

    def execute(self, context: bpy.types.Context) -> set[str]:
        session = bridge.edit_session()
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        try:
            _open_scene(bridge.end_edit(session))
        except bridge.BridgeError as error:
            return _report(self, error)
        return {"FINISHED"}


# The model whose export settings the panel shows, picked by its button. An
# excluded collection can't be made active, so the pick holds until the active
# collection changes; then the active collection is shown again.
_SHOWN = {"model": "", "over": ""}


def _show(view_layer: bpy.types.ViewLayer, collection: bpy.types.Collection) -> None:
    bridge.activate_collection(view_layer, collection)
    _SHOWN["model"] = collection.name
    _SHOWN["over"] = view_layer.active_layer_collection.collection.name


def _shown_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    active = context.collection
    if _SHOWN["model"] and active is not None and active.name == _SHOWN["over"]:
        picked = next((c for c in bridge.model_collections() if c.name == _SHOWN["model"]), None)
        if picked is not None:
            return picked
    return active


class BB_OT_show_model(bpy.types.Operator):
    """Show the collection's export settings below; it's made active unless it's excluded from the view layer"""

    bl_idname = "bb.show_model"
    bl_label = "Show export settings"
    bl_options = {"INTERNAL"}

    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        collection = next((c for c in bridge.model_collections() if c.name == self.name), None)
        if collection is None:
            return {"CANCELLED"}
        _show(context.view_layer, collection)
        return {"FINISHED"}


def _guess_root() -> str:
    """The Godot project of a .blend that isn't linked: found from its place,
    otherwise the only known project."""
    root, _ = bridge.project_for(bpy.data.filepath)
    known = bridge.projects()
    return root or (known[0] if len(known) == 1 else "")


def _export_file(collection: bpy.types.Collection) -> str:
    """The file the collection's glTF exporter writes, or empty when it has no path."""
    exporter = bridge.gltf_exporter(collection)
    return os.path.abspath(bpy.path.abspath(exporter.filepath)) if exporter is not None and exporter.filepath else ""


class BB_OT_set_export_path(bpy.types.Operator, ExportHelper):
    """Choose the file in the Godot project the collection exports to"""

    bl_idname = "bb.set_export_path"
    bl_label = "Export to"
    bl_options = {"UNDO", "INTERNAL"}

    filename_ext = ".glb"
    check_extension = None   # .gltf is fine too
    filter_glob: StringProperty(default="*.glb;*.gltf", options={"HIDDEN"})
    name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        collection = next((c for c in bridge.model_collections() if c.name == self.name), None)
        root = bridge.file_root() or _guess_root()
        if collection is None or not root:
            return _report(self, bridge.BridgeError("the file isn't linked to a Godot project"))
        current = _export_file(collection)
        if current:
            self.filepath = current
        else:
            # Next to where the .blend's own model goes, named after the collection.
            asset, _ = bridge.suggested_asset(root, bpy.data.filepath)
            folder = os.path.dirname(bridge.asset_abs(root, asset))
            while not os.path.isdir(folder) and len(folder) > len(root):
                folder = os.path.dirname(folder)
            self.filepath = os.path.join(folder, collection.name + ".glb")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context: bpy.types.Context) -> set[str]:
        collection = next((c for c in bridge.model_collections() if c.name == self.name), None)
        linked = bridge.file_root()
        root = linked or _guess_root()
        if collection is None or not root:
            return _report(self, bridge.BridgeError("the file isn't linked to a Godot project"))
        path = os.path.abspath(bpy.path.abspath(self.filepath))
        if not path.lower().endswith((".glb", ".gltf")):
            path += ".glb"
        if not bridge.res_path(root, path):
            return _report(self, bridge.BridgeError("pick a file inside the Godot project %s" % root))
        # A file that isn't linked yet only gets the path; Link to Godot links it.
        bridge.set_export_target(collection, path, linked)
        self.report({"INFO"}, "%s exports to %s" % (collection.name, bridge.res_path(root, path)))
        return {"FINISHED"}


def _dialog_root(props: bpy.types.OperatorProperties) -> str:
    """The Godot project picked in the dialog, or empty when it isn't one."""
    root = os.path.normpath(os.path.abspath(bpy.path.abspath(props.project))) if props.project.strip() else ""
    return root if root and os.path.isfile(os.path.join(root, "project.godot")) else ""


def _project_changed(props: bpy.types.OperatorProperties, _context: bpy.types.Context) -> None:
    root = _dialog_root(props)
    if root:
        props.models = bridge.models_folder(root)   # suggests the target in turn


def _models_changed(props: bpy.types.OperatorProperties, _context: bpy.types.Context) -> None:
    root = _dialog_root(props)
    if root and bpy.data.filepath:
        asset, _ = bridge.suggested_asset(root, bpy.data.filepath, props.models)
        props.target = bridge.asset_abs(root, asset)


class BB_OT_link(bpy.types.Operator):
    """Export the models of this .blend into a Godot project.
    Stored in the file, so it's linked the same way for everyone"""

    bl_idname = "bb.link_to_godot"
    bl_label = "Link to Godot"

    auto: BoolProperty(
        name="Export on every save", options={"SKIP_SAVE"},
        description="Ctrl+S exports too; otherwise only Export now does",
    )
    project: StringProperty(
        name="Godot project", subtype="DIR_PATH", options={"SKIP_SAVE"}, update=_project_changed,
        description="Folder of the Godot project (with project.godot)",
    )
    models: StringProperty(
        name="Models folder", subtype="DIR_PATH", options={"SKIP_SAVE"}, update=_models_changed,
        description="Where the models repository is on this disk. Saved only for you in the Godot "
                    "project's .pipeline/local/settings.json; Godot reads it too",
    )
    target: StringProperty(
        name="Export to", subtype="FILE_PATH", options={"SKIP_SAVE"},
        description="The .glb in the Godot project; it follows the .blend's place in the models folder",
    )

    @classmethod
    def description(cls, context: bpy.types.Context, properties: bpy.types.OperatorProperties) -> str:
        if properties.auto:
            return "Link to Godot and export into it on every save. Stored in the .blend, for everyone"
        return "Link to Godot without exporting on save; export with Export now. Stored in the .blend"

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if not bpy.data.filepath:
            return _report(self, bridge.BridgeError("save the file first; the path in Godot follows its place"))
        self.project = _guess_root()   # fills the rest
        return context.window_manager.invoke_props_dialog(self, width=640)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "project")
        real = bridge.host_path(bpy.data.filepath)
        if real != bpy.data.filepath:
            layout.label(text="The file manager opened the file from %s" % real, icon="INFO")
        if bridge.model_collections():
            layout.label(text="Exports the collections that already have an exporter.", icon="INFO")
        else:
            root = _dialog_root(self)
            layout.prop(self, "models")
            layout.prop(self, "target")
            column = layout.column(align=True)
            asset = bridge.res_path(root, self.target)
            if asset:
                column.label(text="In Godot: %s" % asset, icon="LINKED")
            elif root and self.target:
                note = column.row()
                note.alert = True
                note.label(text="Outside the Godot project; pick a file inside it.", icon="ERROR")
            if root and not bridge.suggested_asset(root, bpy.data.filepath, self.models)[1]:
                note = column.row()
                note.alert = True
                note.label(text="The .blend isn't in the models folder, so the path is only a guess "
                                "from its name.", icon="ERROR")
            active = context.view_layer.active_layer_collection.collection
            name = active.name if active != context.scene.collection else "a new collection with the scene's objects"
            column.label(text="Exported: %s" % name, icon="OUTLINER_COLLECTION")
        layout.prop(self, "auto")

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            root = _dialog_root(self)
            folder = os.path.normpath(os.path.abspath(bpy.path.abspath(self.models))) if self.models.strip() else ""
            if root and self.properties.is_property_set("models") and not bridge.model_collections() \
                    and folder != bridge.models_folder(root):
                bridge.store_models_folder(root, folder)
            bridge.link_file(context.scene, context.view_layer, self.project, self.target, self.auto)
        except bridge.BridgeError as error:
            return _report(self, error)
        self.report({"INFO"}, "Saving now exports to Godot" if self.auto else "Linked; Export now sends it to Godot")
        return {"FINISHED"}


class BB_OT_auto_export(bpy.types.Operator):
    """Export the models of this .blend into the Godot project on every save.
    Stored in the .blend, so it's the same for everyone"""

    bl_idname = "bb.auto_export"
    bl_label = "Auto save to Godot"
    bl_options = {"UNDO"}

    enable: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bool(bridge.file_root())

    def execute(self, context: bpy.types.Context) -> set[str]:
        bridge.set_auto_export(self.enable)
        return {"FINISHED"}


class BB_OT_export_now(bpy.types.Operator):
    """Export the models of this .blend into the Godot project now, without saving"""

    bl_idname = "bb.export_now"
    bl_label = "Export now"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bool(bridge.file_root())

    def execute(self, context: bpy.types.Context) -> set[str]:
        root = bridge.file_root()
        # Paths typed into the exporters' own File Path count, as on save.
        bridge.sync_export_paths(root)
        count = bridge.export_models(root)
        bridge.forget_models_index()
        if not count:
            return _report(self, bridge.BridgeError("no model has an export path"))
        self.report({"INFO"}, "Exported %d model%s" % (count, "" if count == 1 else "s"))
        return {"FINISHED"}


class BB_OT_add_project(bpy.types.Operator):
    """Add a Godot project that Link to Godot can export into"""

    bl_idname = "bb.add_project"
    bl_label = "Add Godot project…"

    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not os.path.isfile(os.path.join(self.directory, "project.godot")):
            return _report(self, bridge.BridgeError("pick the folder with project.godot"))
        bridge.remember_project(self.directory)
        return {"FINISHED"}


class BB_OT_remove_project(bpy.types.Operator):
    """Forget the Godot project; it's added again when Blender opens it from Godot"""

    bl_idname = "bb.remove_project"
    bl_label = "Remove Godot project"
    bl_options = {"INTERNAL"}

    root: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        bridge.forget_project(self.root)
        return {"FINISHED"}


class BB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Godot projects", icon="FILE_FOLDER")
        layout.label(text="Added when Blender opens a project from Godot. Link to Godot")
        layout.label(text="looks among them for the project a .blend belongs to.")
        column = layout.column(align=True)
        for root in bridge.projects():
            row = column.row(align=True)
            missing = not os.path.isfile(os.path.join(root, "project.godot"))
            row.label(text=root + (" (missing)" if missing else ""), icon="ERROR" if missing else "FILE_FOLDER")
            row.operator(BB_OT_remove_project.bl_idname, text="", icon="X").root = root
        layout.operator(BB_OT_add_project.bl_idname, icon="ADD")


# --------------------------------------------------------------- handlers


@persistent
def _on_load_post(_: object) -> None:
    bridge.forget_models_index()
    _SHOWN.update(model="", over="")
    _OPEN_ERROR["message"] = ""   # a failed build sets it again after its read_homefile
    session = bridge.edit_session() or bridge.take_opened_source()
    if session is not None and session["asset"]:
        scene = bpy.context.scene
        try:
            collection = bridge.setup_session_exporter(session)
        except bridge.BridgeError as error:
            print("Blenderang:", error)
            collection = None
        if collection is not None:
            # libraries.write saves the collection without a scene; without this
            # nothing would be visible after opening.
            if collection not in scene.collection.children_recursive:
                scene.collection.children.link(collection)
            # The panel shows the export settings of this collection.
            _show(bpy.context.view_layer, collection)
    root = bridge.file_root()
    if root:
        bridge.follow_moved_assets(root)
        bridge.localize_export_paths(root)
        bridge.remember_asset_uids(root)
        bridge.apply_modifiers_by_default()
    if session is not None and session["manifest"]:
        with bpy.context.temp_override(**bridge.ui_context()):
            bridge.build_context(session)


@persistent
def _on_save_pre(filepath: str, *_: object) -> None:
    bridge.clear_context()
    bridge.follow_save_as(filepath)
    root = bridge.file_root()
    if root:
        # Relative to where the file is being saved (Save As may move it).
        bridge.sync_export_paths(root, filepath)


@persistent
def _on_save_post(_: object, *__: object) -> None:
    root = bridge.file_root()
    if root:
        bridge.export_models(root, on_save=True)
    # A newly saved .blend may be the source Godot finds by name.
    bridge.forget_models_index()
    session = bridge.edit_session()
    if session is not None:
        with bpy.context.temp_override(**bridge.ui_context()):
            bridge.build_context(session)


_HANDLERS = (
    (bpy.app.handlers.load_post, _on_load_post),
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
)


# ------------------------------------------------------------------ panel


class BB_PT_panel(bpy.types.Panel):
    bl_label = "Blenderang"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blenderang"

    def draw(self, context: bpy.types.Context) -> None:
        session = bridge.edit_session()
        root = bridge.file_root()
        if root:
            self._draw_file(context, session, root)
        elif context.scene.get(bridge.S_MANIFEST):
            self._draw_scene(context)
        else:
            self._draw_unbound(context)

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
                row.operator(BB_OT_choose_source.bl_idname, text="Pick source", icon="FILEBROWSER").name = obj.name
        if any(o.get(bridge.P_TIER) != "library" for o in models):
            box.label(text="Without a source, a model is only a .glb preview.", icon="INFO")

        folder = bridge.models_folder(scene.get(bridge.S_ROOT, ""))
        row = layout.row(align=True)
        row.label(text="Models folder: %s" % (folder or "not set"), icon="FILE_FOLDER")
        row.operator(BB_OT_set_models_folder.bl_idname, text="", icon="FILEBROWSER")
        if folder:
            row.operator(BB_OT_set_models_folder.bl_idname, text="", icon="X").clear = True

    def _draw_unbound(self, context: bpy.types.Context) -> None:
        layout = self.layout
        if _OPEN_ERROR["message"]:
            error = layout.box()
            error.alert = True
            error.label(text="Opening from Godot failed:", icon="ERROR")
            # Labels don't wrap; roughly the characters that fit the sidebar.
            width = max(20, int(context.region.width / (8 * context.preferences.system.ui_scale)))
            for line in textwrap.wrap(_OPEN_ERROR["message"], width):
                error.label(text=line)
        layout.label(text="Open a scene from Godot with the Blender button.", icon="INFO")
        box = layout.box()
        if not bpy.data.filepath:
            box.label(text="Save the file first; the path in Godot follows its place.")
            return
        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator(BB_OT_link.bl_idname, text="Link to Godot", icon="LINKED").auto = False
        row.operator(BB_OT_link.bl_idname, text="Auto save to Godot", icon="CHECKBOX_DEHLT").auto = True
        root = _guess_root()
        column = box.column(align=True)
        real = bridge.host_path(bpy.data.filepath)
        if real != bpy.data.filepath:
            column.label(text="Opened from %s" % real, icon="INFO")
        if root:
            column.label(text="Project: %s" % root, icon="FILE_FOLDER")
            column.label(text="Models folder: %s" % (bridge.models_folder(root) or "not set"), icon="FILE_FOLDER")
        else:
            column.label(text="No known Godot project; pick it when linking.")
        models = bridge.model_collections()
        if models:
            column.label(text="The file already exports (its exporters):")
            for collection in models:
                _draw_model(column, context, collection, root)
        elif root:
            asset, follows = bridge.suggested_asset(root, bpy.data.filepath)
            column.label(text="Exports to: %s" % asset, icon="EXPORT")
            if not follows:
                note = column.row()
                note.alert = True
                note.label(text="Not in the models folder; the path is a guess from the name.", icon="ERROR")
            _draw_status(column, root, asset)

    def _draw_file(self, context: bpy.types.Context, session: dict | None, root: str) -> None:
        layout = self.layout
        if session is not None:
            layout.label(text="Editing: %s" % os.path.basename(session["asset"]), icon="EDITMODE_HLT")
            back = layout.row()
            back.scale_y = 1.6
            back.operator(BB_OT_return_to_scene.bl_idname, icon="LOOP_BACK")
        else:
            layout.label(text="File: %s" % os.path.basename(bpy.data.filepath), icon="FILE_BLEND")
        on = bridge.auto_export()
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            BB_OT_auto_export.bl_idname, depress=on,
            icon="CHECKBOX_HLT" if on else "CHECKBOX_DEHLT",
        ).enable = not on
        row.operator(BB_OT_export_now.bl_idname, icon="EXPORT")
        column = layout.column(align=True)
        column.label(text="Ctrl+S saves and exports to Godot" if on else "Saving doesn't export",
                     icon="CHECKMARK" if on else "INFO")
        column.label(text="The switch is saved in the .blend, for everyone.")
        column.label(text="Project: %s" % root)
        if session is not None:
            column.label(text="The surrounding scene is only for reference and isn't saved.")

        box = layout.box()
        box.label(text="Models (collections with an exporter)", icon="OUTLINER_COLLECTION")
        models = bridge.model_collections()
        if not models:
            box.label(text="Nothing exports yet; add an exporter to a collection.")
        for collection in models:
            _draw_model(box, context, collection, root)
        # Blender's own Collection Exporters UI for the picked model or the active
        # collection. Overriding the context shows a collection that can't be made
        # active (excluded from the view layer); its buttons get it from the layout.
        shown = _shown_collection(context)
        if shown is None or shown == context.scene.collection or shown.library is not None \
                or shown.name == bridge.COLL_CONTEXT:
            box.label(text="Click a model (or make a collection active) for its export settings.")
            return
        box.label(text="Export settings of %s (saved with the .blend)" % shown.name, icon="SETTINGS")
        settings = box.column()
        settings.context_pointer_set("collection", shown)
        with context.temp_override(collection=shown):
            settings.template_collection_exporters()
        _draw_limit(settings, shown)


def _draw_limit(layout: bpy.types.UILayout, collection: bpy.types.Collection) -> None:
    """glTF's Include ▸ Limit to. The glTF add-on draws it only in the File ▸ Export
    dialog, yet the collection exporter honours these three. Active Collection and
    Active Scene don't apply there: the collection is what gets exported."""
    exporter = bridge.gltf_exporter(collection)
    props = exporter.export_properties if exporter is not None else None
    if props is None or not hasattr(props, "use_visible"):
        return
    header, body = layout.panel("BB_export_limit")
    header.label(text="glTF Include: Limit to")
    if body is None:
        return
    column = body.column(heading="Limit to", align=True)
    column.use_property_split = True
    column.use_property_decorate = False
    for name in ("use_selection", "use_visible", "use_renderable"):
        column.prop(props, name)


def _draw_model(layout: bpy.types.UILayout, context: bpy.types.Context,
                collection: bpy.types.Collection, root: str) -> None:
    """A model's row: its collection, where it exports (the button changes it) and
    what that means in Godot."""
    row = layout.row(align=True)
    row.operator(BB_OT_show_model.bl_idname, text=collection.name, icon="OUTLINER_COLLECTION",
                 depress=_shown_collection(context) == collection).name = collection.name
    path = _export_file(collection)
    # From the exporter itself, so a path typed into its File Path shows at once.
    asset = bridge.res_path(root, path) if root and path else ""
    label = row.row(align=True)
    label.alert = not path
    label.label(text=asset or path or "no path")
    if root:
        row.operator(BB_OT_set_export_path.bl_idname, text="" if path else "Set path…",
                     icon="FILEBROWSER").name = collection.name
    clash = [c.name for c in bridge.model_collections()
             if c != collection and path and _export_file(c) and bridge._same_file(_export_file(c), path)]
    if clash:
        note = layout.row()
        note.alert = True
        note.label(text="%s exports the same file; one overwrites the other" % ", ".join(clash), icon="ERROR")
    if asset:
        _draw_status(layout, root, asset)


def _draw_status(layout: bpy.types.UILayout, root: str, asset: str) -> None:
    text, problem = bridge.godot_status(root, asset)
    row = layout.row()
    row.alert = problem
    row.label(text=text, icon="ERROR" if problem else "LINKED")


class BB_PT_detail(bpy.types.Panel):
    """Details of the selected object: where it comes from and what happens to it."""

    bl_label = "Detail"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blenderang"
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
                note.label(text="Source is outside the project and the models folder, only for you.", icon="ERROR")
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
    BB_OT_export_manifest,
    BB_OT_rebuild,
    BB_OT_promote_source,
    BB_OT_edit_source,
    BB_OT_choose_source,
    BB_OT_clear_source,
    BB_OT_set_models_folder,
    BB_OT_select_model,
    BB_MT_model_pie,
    BB_OT_model_pie,
    BB_OT_open_source,
    BB_OT_return_to_scene,
    BB_OT_show_model,
    BB_OT_set_export_path,
    BB_OT_link,
    BB_OT_auto_export,
    BB_OT_export_now,
    BB_OT_add_project,
    BB_OT_remove_project,
    BB_Preferences,
    BB_PT_panel,
    BB_PT_detail,
)


# Tab on a model: Blenderang's menu instead of Blender's "linked data" one, whose
# Open skips everything Edit does. Elsewhere the poll fails and Tab works as usual.
_KEYMAPS: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


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
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:   # None in background mode
        keymap = keyconfig.keymaps.new(name="Object Mode", space_type="EMPTY")
        _KEYMAPS.append((keymap, keymap.keymap_items.new(BB_OT_model_pie.bl_idname, "TAB", "PRESS")))


def unregister() -> None:
    for keymap, item in _KEYMAPS:
        keymap.keymap_items.remove(item)
    _KEYMAPS.clear()
    del bpy.types.Scene.bb_model_filter
    for handlers, callback in _HANDLERS:
        if callback in handlers:
            handlers.remove(callback)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
