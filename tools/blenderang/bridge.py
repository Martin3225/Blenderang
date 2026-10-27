"""Core of the bridge between the Godot manifest and the Blender scene.

The manifest carries only identities and transforms. Geometry is never
transferred: assets are linked into Blender from their source .blend files,
or imported from .glb as a preview.

The scene itself has no .blend. The layout always lives in the .tscn and Blender
builds it from the manifest every time, so it can't drift out of sync with Godot.
"""

from __future__ import annotations

import json
import os
from typing import Any

import bpy
from mathutils import Matrix, Vector

# Custom properties by which the add-on recognises its own objects.
P_ID = "bb_id"
P_PATH = "bb_path"
P_SRC = "bb_src"
P_TIER = "bb_tier"
P_PARENT = "bb_parent"
P_SRC_BLEND = "bb_src_blend"
P_PREVIEW = "bb_preview"

S_MANIFEST = "bb_manifest"
S_ROOT = "bb_project_root"
S_WARNINGS = "bb_warnings"

COLL_LAYOUT = "BB_Layout"
COLL_LOCKED = "BB_Locked"

# Godot: X right, Y up, -Z forward. Blender: X right, Y forward, Z up.
# Basis change between the systems; the matrix is orthogonal, so inverse == transpose.
_AXIS = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
_AXIS_INV = _AXIS.transposed()


class BridgeError(Exception):
    """An error worth showing to the user in an operator report."""


# ---------------------------------------------------------------- transforms


def godot_to_blender(xform: list[float]) -> Matrix:
    """12 floats from the manifest (three basis columns, then origin) to a Blender matrix."""
    if len(xform) != 12:
        raise BridgeError("a transform must have 12 components, it has %d" % len(xform))
    basis = Matrix((
        (xform[0], xform[3], xform[6]),
        (xform[1], xform[4], xform[7]),
        (xform[2], xform[5], xform[8]),
    ))
    converted = _AXIS @ basis @ _AXIS_INV
    origin = _AXIS @ Vector((xform[9], xform[10], xform[11]))
    return Matrix.Translation(origin) @ converted.to_4x4()


def blender_to_godot(matrix: Matrix) -> list[float]:
    """The opposite direction; the output is the array for the manifest."""
    basis = _AXIS_INV @ matrix.to_3x3() @ _AXIS
    origin = _AXIS_INV @ matrix.to_translation()
    return [
        basis[0][0], basis[1][0], basis[2][0],
        basis[0][1], basis[1][1], basis[2][1],
        basis[0][2], basis[1][2], basis[2][2],
        origin.x, origin.y, origin.z,
    ]


# ----------------------------------------------------------------------- files


def load_manifest(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise BridgeError("manifest does not exist: %s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") != 1:
        raise BridgeError("unknown manifest version: %r" % data.get("format"))
    return data


def save_manifest(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent="\t", ensure_ascii=False)
        handle.write("\n")


def project_root_for(manifest_path: str) -> str:
    """The manifest lives in ``<root>/.pipeline/<scene>.json``."""
    pipeline = os.path.dirname(os.path.abspath(manifest_path))
    if os.path.basename(pipeline) != ".pipeline":
        raise BridgeError("the manifest must be in the .pipeline folder, it is in %s" % pipeline)
    return os.path.dirname(pipeline)


def stored_manifest_path(scene: bpy.types.Scene) -> str:
    path = scene.get(S_MANIFEST, "")
    if not path:
        raise BridgeError("this scene has no manifest loaded")
    return path


# ------------------------------------------------------------------ context


def ui_context() -> dict[str, Any]:
    """3D view context for ``temp_override``.

    Godot starts the scene build from a timer and handlers run after a file
    loads; neither has a window or a 3D view. But the glTF importer reaches for
    ``bpy.context.object`` on models with an armature and crashes without a 3D view.
    In the background (tests, ``--background``) nothing is overridden.
    """
    manager = bpy.context.window_manager
    if bpy.app.background or manager is None or not manager.windows:
        return {}
    for window in manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            return {"window": window, "screen": window.screen, "area": area, "region": region,
                    "scene": window.scene, "view_layer": window.view_layer}
    window = manager.windows[0]
    return {"window": window, "screen": window.screen, "scene": window.scene, "view_layer": window.view_layer}


# --------------------------------------------------------------- collections


def _ensure_collection(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    existing = parent.children.get(name)
    if existing is not None:
        return existing
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def _same_file(left: str, right: str) -> bool:
    """Windows paths are case-insensitive and mix separators."""
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _link_library_collection(blend_path: str, name: str) -> bpy.types.Collection:
    """Links the collection from the source .blend. Repeated calls don't link again."""
    for collection in bpy.data.collections:
        library = collection.library
        if library is None:
            continue
        if _same_file(bpy.path.abspath(library.filepath), blend_path) and collection.name == name:
            return collection
    with bpy.data.libraries.load(blend_path, link=True) as (data_from, data_to):
        available = list(data_from.collections)
        if not available:
            raise BridgeError("%s contains no collection" % blend_path)
        picked = name if name in available else available[0]
        data_to.collections = [picked]
    linked = data_to.collections[0]
    if linked is None:
        raise BridgeError("could not link a collection from %s" % blend_path)
    return linked


# The glTF importer creates helper objects for armature bone shapes
# in a "glTF_not_exported" collection. They belong to the bones, not the scene.
_IMPORTER_HELPERS = "glTF_not_exported"


def _import_file(path: str) -> tuple[list[bpy.types.Object], list[bpy.types.Object]]:
    """Imports a .glb/.gltf/.fbx and returns (objects, importer helper objects).

    Unlinks all new objects from the scene; the caller decides where they belong.
    Cleans up any collections the importer created.
    """
    extension = os.path.splitext(path)[1].lower()
    objects_before = set(bpy.data.objects)
    collections_before = set(bpy.data.collections)
    try:
        if extension in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif extension == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        else:
            raise BridgeError("unsupported format")
    except (RuntimeError, BridgeError) as error:
        # After a failed import nothing may be left half-done in the scene.
        for obj in set(bpy.data.objects) - objects_before:
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in set(bpy.data.collections) - collections_before:
            bpy.data.collections.remove(collection)
        message = str(error).strip().splitlines()[-1] if str(error).strip() else type(error).__name__
        raise BridgeError("%s: %s" % (os.path.basename(path), message)) from error
    objects: list[bpy.types.Object] = []
    helpers: list[bpy.types.Object] = []
    for obj in set(bpy.data.objects) - objects_before:
        is_helper = any(c.name.startswith(_IMPORTER_HELPERS) for c in obj.users_collection)
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        (helpers if is_helper else objects).append(obj)
    for collection in set(bpy.data.collections) - collections_before:
        bpy.data.collections.remove(collection)
    return objects, helpers


def _preview_collection(entry: dict[str, Any], root: str) -> bpy.types.Collection | None:
    """Collection with the model imported from .glb for an asset with no source .blend.

    The collection isn't in the scene; the instance doesn't need it there. So the
    model is visible only once, at the instance's place, and never lies around at the origin.
    """
    stem = os.path.basename(entry.get("src", "")).rsplit(".", 1)[0]
    existing = bpy.data.collections.get(stem)
    if existing is not None and existing.get(P_PREVIEW):
        return existing
    path = asset_abs(root, entry.get("src", ""))
    if not os.path.isfile(path):
        warn("%s: asset %s does not exist" % (entry.get("name"), entry.get("src")))
        return None
    try:
        objects, _ = _import_file(path)
    except BridgeError as error:
        warn("%s: cannot load preview (%s)" % (entry.get("name"), error))
        return None
    collection = bpy.data.collections.new(stem)
    collection[P_PREVIEW] = True
    for obj in objects:
        collection.objects.link(obj)
    return collection


def source_of(entry: dict[str, Any], root: str) -> str:
    """Path to the source .blend (relative to the project, absolute for a
    personal source), or empty.

    Same rule as BBPaths in Godot: personal choice (only for you) →
    ``<asset>.bbsrc`` (shared) → ``.blend`` next to the asset. Blender
    evaluates it itself so it sees a newly picked source right away.
    """
    asset = entry.get("src", "")
    personal = local_sources(root).get(asset, "")
    if personal and os.path.isfile(personal):
        return personal
    override = asset_abs(root, asset) + ".bbsrc"
    if os.path.isfile(override):
        with open(override, encoding="utf-8") as handle:
            relative = handle.read().strip().replace("res://", "", 1)
    else:
        relative = expected_source(asset)
    return relative if os.path.isfile(os.path.join(root, relative)) else ""


def _resolve_source(entry: dict[str, Any], root: str) -> tuple[bpy.types.Collection | None, str]:
    """The collection the instance will point to (linked source, or preview)
    and the relative path to the source, if there is one."""
    relative = source_of(entry, root)
    if relative:
        stem = os.path.basename(entry.get("src", "")).rsplit(".", 1)[0]
        try:
            return _link_library_collection(os.path.join(root, relative), stem), relative
        except (OSError, BridgeError) as error:
            # A broken or empty .blend must not crash opening the whole scene.
            print("Blenderang: cannot load source %s (%s), using the .glb preview" % (relative, error))
    return _preview_collection(entry, root), ""


# --------------------------------------------------------------------- build


def _clear_previous(scene: bpy.types.Scene) -> None:
    doomed = [obj for obj in scene.objects if P_ID in obj or P_PATH in obj]
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)


def _make_proxy_mesh(name: str, bounds: dict[str, Any]) -> bpy.types.Mesh:
    position = Vector(bounds["position"])
    size = Vector(bounds["size"])
    # The Godot AABB is in Godot axes; we build the proxy directly in Blender axes.
    low = _AXIS @ position
    high = _AXIS @ (position + size)
    minimum = Vector((min(low.x, high.x), min(low.y, high.y), min(low.z, high.z)))
    maximum = Vector((max(low.x, high.x), max(low.y, high.y), max(low.z, high.z)))
    mesh = bpy.data.meshes.new(name)
    corners = [
        (minimum.x, minimum.y, minimum.z), (maximum.x, minimum.y, minimum.z),
        (maximum.x, maximum.y, minimum.z), (minimum.x, maximum.y, minimum.z),
        (minimum.x, minimum.y, maximum.z), (maximum.x, minimum.y, maximum.z),
        (maximum.x, maximum.y, maximum.z), (minimum.x, maximum.y, maximum.z),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(corners, [], faces)
    mesh.update()
    return mesh


def lock(obj: bpy.types.Object) -> None:
    """Context from Godot can be selected and framed (numpad .), but not moved.
    Changes wouldn't make it to Godot anyway."""
    obj.lock_location = (True, True, True)
    obj.lock_rotation = (True, True, True)
    obj.lock_rotation_w = True
    obj.lock_scale = (True, True, True)


# Problems that don't stop the scene build (broken asset, broken context), but
# the user should know about. The panel shows them, the operator reports them.
WARNINGS: list[str] = []


def warn(message: str) -> None:
    WARNINGS.append(message)
    print("Blenderang:", message)


def build(scene: bpy.types.Scene, manifest_path: str) -> dict[str, int]:
    """Builds the scene from the manifest. Replaces existing BB objects.

    One broken file must not crash the whole build: a model without a preview stays
    as an empty axis at its place, a broken context is replaced by bounding boxes.
    """
    WARNINGS.clear()
    manifest = load_manifest(manifest_path)
    root = project_root_for(manifest_path)

    _clear_previous(scene)
    layout = _ensure_collection(scene.collection, COLL_LAYOUT)
    locked = _ensure_collection(scene.collection, COLL_LOCKED)

    counts = {"props": 0, "proxies": 0, "preview": 0}
    models: dict[str, bpy.types.Object] = {}
    for entry in manifest["nodes"]:
        if entry.get("owner") != "blender":
            continue
        obj = _build_prop(entry, root)
        layout.objects.link(obj)
        models[entry["path"]] = obj
        counts["props"] += 1
        if obj.get(P_TIER) == "none":
            counts["preview"] += 1
    _parent_models(models)
    _readable_empties(list(models.values()), 0.5)

    counts["proxies"] = import_context(root, manifest, locked, Matrix.Identity(4))
    scene[S_MANIFEST] = manifest_path
    scene[S_ROOT] = root
    scene[S_WARNINGS] = list(WARNINGS)
    return counts


def _parent_models(models: dict[str, bpy.types.Object]) -> None:
    """A model that is a child of another model in Godot (gear on an armature)
    is its child in Blender too, so moving the parent moves the children."""
    for obj in models.values():
        parent = models.get(str(obj.get(P_PARENT, "")))
        if parent is None:
            continue
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world


def _readable_empties(objects: list[bpy.types.Object], size: float) -> None:
    """Empty object axes [size] metres in world space, regardless of
    scale; the glTF importer makes them hundreds of metres big."""
    bpy.context.view_layer.update()
    for obj in objects:
        if obj.type != "EMPTY":
            continue
        scale = max(abs(v) for v in obj.matrix_world.to_scale()) or 1.0
        obj.empty_display_size = size / scale


def import_context(
    root: str,
    manifest: dict[str, Any],
    target: bpy.types.Collection,
    matrix: Matrix,
) -> int:
    """Locked surroundings from Godot into collection [target].

    Real geometry from ``.context.glb``; an older manifest without it gets
    bounding boxes from ``bounds``. [matrix] moves the whole context, into the
    model's local space when editing a model. Returns the number of Godot nodes.
    """
    context_path = os.path.join(root, manifest.get("context_glb", ""))
    godot_entries = [e for e in manifest["nodes"] if e.get("owner") != "blender"]
    objects: list[bpy.types.Object] | None = None
    if manifest.get("context_glb") and os.path.isfile(context_path):
        try:
            objects, _ = _import_file(context_path)
        except BridgeError as error:
            warn("cannot load context from Godot (%s), using bounding boxes" % error)
    if objects is not None:
        for obj in objects:
            target.objects.link(obj)
            obj[P_PATH] = "context"
            lock(obj)
            if obj.parent is None:
                obj.matrix_world = matrix @ obj.matrix_world
        _readable_empties(objects, 1.0)
        return len(godot_entries)

    boxes = []
    for entry in godot_entries:
        obj = _build_box(entry, matrix)
        target.objects.link(obj)
        boxes.append(obj)
    _readable_empties(boxes, 1.0)
    return len(godot_entries)


def _build_prop(entry: dict[str, Any], root: str) -> bpy.types.Object:
    obj = bpy.data.objects.new(entry["name"], None)
    collection, relative = _resolve_source(entry, root)
    if collection is not None:
        obj.instance_type = "COLLECTION"
        obj.instance_collection = collection
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.5
    obj[P_ID] = entry["bb_id"]
    obj[P_PATH] = entry["path"]
    obj[P_SRC] = entry["src"]
    obj[P_PARENT] = entry.get("parent", ".")
    obj[P_TIER] = "library" if relative else "none"
    if relative:
        obj[P_SRC_BLEND] = relative
    obj.matrix_world = godot_to_blender(entry["xform"])
    return obj


def _build_box(entry: dict[str, Any], matrix: Matrix) -> bpy.types.Object:
    bounds = entry.get("bounds")
    if bounds is None:
        obj = bpy.data.objects.new(entry["name"], None)
        obj.empty_display_type = "CUBE"
    else:
        obj = bpy.data.objects.new(entry["name"], _make_proxy_mesh(entry["name"], bounds))
    obj.display_type = "WIRE"
    obj[P_PATH] = entry.get("path", "context")
    obj.matrix_world = matrix @ godot_to_blender(entry["xform"])
    lock(obj)
    return obj


# -------------------------------------------------------------------- export


def _new_id(taken: set[str]) -> str:
    import random

    while True:
        candidate = "%08x%08x" % (random.getrandbits(32), random.getrandbits(32))
        if candidate not in taken:
            return candidate


def export(scene: bpy.types.Scene) -> dict[str, int]:
    """Writes transforms from Blender back to the manifest.

    Godot-owned entries pass through unchanged; Blender doesn't edit them.
    Objects without ``bb_id`` are ignored, so you can make helper geometry
    in the layout without it ending up in the game.
    """
    manifest_path = stored_manifest_path(scene)
    manifest = load_manifest(manifest_path)
    # matrix_world is recomputed after a location change only with the depsgraph;
    # from a script or right after an edit the old position would go out.
    bpy.context.view_layer.update()
    originals = {
        entry["bb_id"]: entry
        for entry in manifest["nodes"]
        if entry.get("owner") == "blender"
    }

    nodes: list[dict[str, Any]] = [
        entry for entry in manifest["nodes"] if entry.get("owner") != "blender"
    ]
    counts = {"kept": 0, "moved": 0, "added": 0, "removed": 0, "pinned": 0}
    taken: set[str] = set()

    for obj in scene_models(scene):
        entry, is_new = _entry_for(obj, originals, taken)
        if entry is None:
            continue
        taken.add(entry["bb_id"])
        if entry.get("pinned"):
            counts["pinned"] += 1
            nodes.append(entry)
            continue
        xform = blender_to_godot(obj.matrix_world)
        if is_new:
            counts["added"] += 1
        elif _xform_differs(entry["xform"], xform):
            counts["moved"] += 1
        else:
            counts["kept"] += 1
        entry["xform"] = xform
        entry["name"] = obj.name
        nodes.append(entry)

    counts["removed"] = len(set(originals) - taken)
    manifest["nodes"] = nodes
    save_manifest(manifest_path, manifest)
    return counts


def filter_models(models: list[bpy.types.Object], text: str) -> list[bpy.types.Object]:
    """Models whose name, Godot path or asset contains [text]
    (case-insensitive; several words = all must match)."""
    words = text.lower().split()
    if not words:
        return list(models)

    def haystack(obj: bpy.types.Object) -> str:
        return " ".join((obj.name, str(obj.get(P_PATH, "")), os.path.basename(str(obj.get(P_SRC, ""))))).lower()

    return [obj for obj in models if all(word in haystack(obj) for word in words)]


def scene_models(scene: bpy.types.Scene) -> list[bpy.types.Object]:
    """Models that go to Godot, sorted by name (for the panel and export)."""
    return sorted((obj for obj in scene.objects if P_ID in obj), key=lambda obj: obj.name)


def _entry_for(
    obj: bpy.types.Object,
    originals: dict[str, dict[str, Any]],
    taken: set[str],
) -> tuple[dict[str, Any] | None, bool]:
    """Manifest entry for an object.

    Duplicating an object in Blender also copies its custom properties, id included.
    Collisions are therefore resolved here, at export; earlier there's no reliable
    way to decide which copy is the original.
    """
    current = str(obj.get(P_ID, ""))
    source = originals.get(current)
    if source is not None and current not in taken:
        return dict(source), False

    template = dict(source) if source is not None else {
        "owner": "blender",
        "src": str(obj.get(P_SRC, "")),
        "tier": str(obj.get(P_TIER, "none")),
        "parent": str(obj.get(P_PARENT, ".")),
    }
    if not template.get("src"):
        return None, False
    fresh = _new_id(taken | set(originals))
    obj[P_ID] = fresh
    template["bb_id"] = fresh
    template["path"] = "%s/%s" % (template.get("parent", "."), obj.name)
    template.pop("pinned", None)
    return template, True


def _xform_differs(left: list[float], right: list[float], epsilon: float = 1e-5) -> bool:
    return any(abs(a - b) > epsilon for a, b in zip(left, right))


# --------------------------------------------------- moving the source of truth


def expected_source(asset_src: str) -> str:
    """Convention: the source sits next to the asset with the same name."""
    return os.path.splitext(asset_src.replace("res://", "", 1))[0] + ".blend"


def asset_abs(root: str, asset_src: str) -> str:
    return os.path.join(root, asset_src.replace("res://", "", 1))


# glTF export options the add-on sets and shows in the panel. The defaults
# apply to new sources; the user changes them in the add-on preferences.
EXPORT_DEFAULTS: dict[str, Any] = {
    "export_apply": True,
    "export_yup": True,
    "export_materials": "EXPORT",
    "export_image_format": "AUTO",
    "export_animations": True,
    "export_skins": True,
    "export_morph": True,
    "export_tangents": False,
    "export_extras": False,
    "export_draco_mesh_compression_enable": False,
}

# A collection the default export settings have already been applied to once.
# After that, whatever the source has saved applies and preferences don't overwrite it.
C_EXPORT_SET = "bb_export_set"


def export_defaults() -> dict[str, Any]:
    """Default export options from the add-on preferences (built-in ones without them)."""
    defaults = dict(EXPORT_DEFAULTS)
    addon = bpy.context.preferences.addons.get(__package__ or "")
    if addon is not None:
        for key in defaults:
            if hasattr(addon.preferences, key):
                defaults[key] = getattr(addon.preferences, key)
    return defaults


def gltf_exporter(collection: bpy.types.Collection) -> bpy.types.CollectionExport | None:
    exporter = next((e for e in collection.exporters if e.name.lower().startswith("gltf")), None)
    if exporter is None and len(collection.exporters):
        exporter = collection.exporters[0]
    return exporter


def apply_export_settings(collection: bpy.types.Collection, settings: dict[str, Any]) -> None:
    """Writes the options into the collection's exporter; they're saved with the source .blend."""
    exporter = gltf_exporter(collection)
    if exporter is None:
        return
    props = exporter.export_properties
    for key, value in settings.items():
        if not hasattr(props, key):
            continue   # different version of the glTF add-on
        try:
            setattr(props, key, value)
        except (TypeError, ValueError):
            warn("export: option %s=%r cannot be set" % (key, value))
    collection[C_EXPORT_SET] = True


def ensure_exporter(collection: bpy.types.Collection, target: str) -> None:
    """Collection Exporter to glTF at the asset's path.

    The path is always set again: ``bpy.data.libraries.write`` doesn't save it into
    the new file, and an empty path would export elsewhere (by collection name).

    The collection gets the default options (mainly applying modifiers) only once:
    a new source, and an older source that doesn't have them yet. Further changes
    in the panel stay in the source.
    """
    exporter = gltf_exporter(collection)
    if exporter is None:
        with bpy.context.temp_override(collection=collection):
            bpy.ops.collection.exporter_add(name="IO_FH_gltf2")
        exporter = collection.exporters[-1]
    exporter.filepath = target
    props = exporter.export_properties
    props.filepath = target
    if hasattr(props, "export_format"):
        props.export_format = "GLTF_SEPARATE" if target.lower().endswith(".gltf") else "GLB"
    if not collection.get(C_EXPORT_SET):
        apply_export_settings(collection, export_defaults())


def export_collection(collection: bpy.types.Collection) -> None:
    """Exports the collection with its exporter. ``wm.collection_export_all``
    isn't enough; it only exports collections that are in the view layer."""
    with bpy.context.temp_override(collection=collection):
        bpy.ops.collection.export_all()


def promote_to_library(obj: bpy.types.Object, root: str) -> str:
    """Turns a preview imported from .glb into its own source .blend.

    The collection is written to a new file next to the asset with the export
    already set up, the local copy is removed and the file is linked in its place.
    From then on the .blend is the source of truth.
    """
    collection = obj.instance_collection
    if collection is None:
        raise BridgeError("the object has nothing to save; the .glb preview is missing too")
    if collection.library is not None:
        raise BridgeError("the asset already has a source")

    asset_src = str(obj.get(P_SRC, ""))
    target = os.path.join(root, expected_source(asset_src))
    if os.path.exists(target):
        raise BridgeError("%s already exists; pick it as the source in Godot" % target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    collection.pop(P_PREVIEW, None)
    ensure_exporter(collection, asset_abs(root, asset_src))
    bpy.data.libraries.write(target, {collection}, fake_user=True)

    # The same asset can have several instances in the scene; all are relinked.
    instances = [o for o in bpy.data.objects if o.instance_collection == collection]
    name = collection.name
    for child in list(collection.all_objects):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.collections.remove(collection)

    linked = _link_library_collection(target, name)
    relative = os.path.relpath(target, root).replace(os.sep, "/")
    for instance in instances:
        instance.instance_collection = linked
        instance[P_TIER] = "library"
        instance[P_SRC_BLEND] = relative
    return target


# ------------------------------------------------------------ source editing
#
# "Edit source" opens the .blend of one asset. So the surroundings aren't missing,
# a temporary BB_Context collection with everything else from the scene is built
# into it from the manifest, offset as if the asset stood at its place. The context
# is removed before every save and restored after, so it's never written into the
# source file.

COLL_CONTEXT = "BB_Context"
EDIT_MARKER = "bb_edit.json"


def _marker_path(root: str) -> str:
    return os.path.join(root, ".pipeline", EDIT_MARKER)


def _pointer_path() -> str:
    """Pointer to the edit in progress, in Blender's user config.

    The model's source can be outside the project (personal source), so the marker
    can't be found by walking folders up from the open file.
    """
    return os.path.join(bpy.utils.user_resource("CONFIG", create=True), "blenderang_edit.json")


def begin_edit(scene: bpy.types.Scene, obj: bpy.types.Object) -> str:
    """Sends pending changes to Godot and prepares source editing.

    Returns the path to the source .blend to open.
    """
    root = scene.get(S_ROOT, "")
    relative = obj.get(P_SRC_BLEND, "")
    if not root or not relative:
        raise BridgeError("the asset has no source .blend")
    source = os.path.join(root, relative)   # a personal source is absolute
    if not os.path.isfile(source):
        raise BridgeError("source does not exist: %s" % source)
    manifest = stored_manifest_path(scene)
    export(scene)
    marker = _marker_path(root)
    with open(marker, "w", encoding="utf-8") as handle:
        json.dump({
            "manifest": manifest,
            "bb_id": str(obj.get(P_ID, "")),
            "source": source,
            "asset": str(obj.get(P_SRC, "")),
            "collection": obj.instance_collection.name if obj.instance_collection else "",
        }, handle)
    with open(_pointer_path(), "w", encoding="utf-8") as handle:
        json.dump({"marker": marker, "root": root}, handle)
    return source


def edit_session() -> dict[str, Any] | None:
    """Details of the edit in progress, if its source is the file currently open."""
    if not bpy.data.filepath or not os.path.isfile(_pointer_path()):
        return None
    try:
        with open(_pointer_path(), encoding="utf-8") as handle:
            pointer = json.load(handle)
        with open(pointer["marker"], encoding="utf-8") as handle:
            session = json.load(handle)
    except (OSError, ValueError, KeyError):
        return None
    if not _same_file(session.get("source", ""), bpy.data.filepath):
        return None
    session["root"] = pointer["root"]
    return session


def end_edit(session: dict[str, Any]) -> str:
    """Ends the edit; returns the manifest to rebuild the scene from."""
    for path in (_marker_path(session["root"]), _pointer_path()):
        if os.path.isfile(path):
            os.remove(path)
    return session["manifest"]


def build_context(session: dict[str, Any]) -> int:
    """Builds locked surroundings around the model being edited.

    The Godot part is real geometry from ``.context.glb``, other models are
    instances of their previews. Other occurrences of the same asset point directly
    at the collection being edited, so edits show up everywhere at once.
    Everything is moved into the model's space, as if it stood at its place.
    """
    clear_context()
    WARNINGS.clear()
    manifest = load_manifest(session["manifest"])
    focus = next((e for e in manifest["nodes"] if e.get("bb_id") == session["bb_id"]), None)
    if focus is None:
        return 0
    root = session["root"]
    to_local = godot_to_blender(focus["xform"]).inverted()
    edited = bpy.data.collections.get(session.get("collection", ""))

    context = bpy.data.collections.new(COLL_CONTEXT)
    bpy.context.scene.collection.children.link(context)
    built = import_context(root, manifest, context, to_local)
    for entry in manifest["nodes"]:
        if entry.get("owner") != "blender" or entry is focus:
            continue
        if entry.get("src") == session.get("asset") and edited is not None:
            source = edited
        else:
            source = _preview_collection(entry, root)
        if source is None:
            obj = _build_box(entry, to_local)
        else:
            obj = bpy.data.objects.new(entry["name"], None)
            obj.instance_type = "COLLECTION"
            obj.instance_collection = source
            obj.matrix_world = to_local @ godot_to_blender(entry["xform"])
            lock(obj)
        context.objects.link(obj)
        built += 1
    return built


def clear_context() -> None:
    """Removes the context including everything created for it (previews, meshes,
    materials). Called before every save, so nothing gets into the source."""
    context = bpy.data.collections.get(COLL_CONTEXT)
    if context is None:
        return
    for obj in list(context.all_objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(context)
    for collection in [c for c in bpy.data.collections if c.get(P_PREVIEW)]:
        for obj in list(collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
    # Data without users wouldn't be saved anyway; purge just clears it from memory
    # so it doesn't pile up on the next save. Fake users aren't deleted.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)


def session_collection(session: dict[str, Any]) -> bpy.types.Collection | None:
    return bpy.data.collections.get(session.get("collection", ""))


def collection_has_exporter(session: dict[str, Any]) -> bool:
    collection = session_collection(session)
    return collection is not None and any(e.filepath for e in collection.exporters)


def setup_session_exporter(session: dict[str, Any]) -> str:
    collection = bpy.data.collections.get(session.get("collection", ""))
    if collection is None:
        raise BridgeError("the file is missing collection %s" % session.get("collection"))
    target = asset_abs(session["root"], session["asset"])
    ensure_exporter(collection, target)
    return target


# ------------------------------------------------------------------ detail


def _source_label(obj: bpy.types.Object, tier: str, source: str) -> str:
    if tier != "library":
        return "none, will be created at %s" % expected_source(str(obj.get(P_SRC, "")))
    if os.path.isabs(source):
        return "%s (only for you, outside the project)" % source
    return source


def describe(obj: bpy.types.Object) -> tuple[str, list[tuple[str, str]]]:
    """What the Detail panel shows about an object: kind and rows (label, value).

    Kinds: ``model`` (sent to Godot), ``godot`` (context from Godot,
    for reference only), ``helper`` (helper object, not sent to Godot).
    """
    if P_ID in obj:
        tier = obj.get(P_TIER, "none")
        source = obj.get(P_SRC_BLEND, "")
        rows = [
            ("Godot node", str(obj.get(P_PATH, ""))),
            ("Parent", str(obj.get(P_PARENT, "."))),
            ("Asset", str(obj.get(P_SRC, "")).replace("res://", "", 1)),
            ("Source", _source_label(obj, tier, source)),
            ("Id", str(obj.get(P_ID, ""))),
        ]
        return "model", rows
    unit = obj
    while unit.parent is not None and unit.parent.parent is not None:
        unit = unit.parent
    if obj.get(P_PATH) == "context" or unit.get(P_PATH) == "context":
        return "godot", [("Godot node", unit.name)]
    return "helper", []



# ---------------------------------------------------------- source choice


def override_path(root: str, asset_src: str) -> str:
    """``<asset>.bbsrc``: exact path to the source, shared with Godot."""
    return asset_abs(root, asset_src) + ".bbsrc"


# Personal choice of sources outside the project. Godot reads the same file (BBPaths).
# The folder has a .gitignore with "*", so it's never committed.
LOCAL_DIR = os.path.join(".pipeline", "local")
LOCAL_SOURCES = os.path.join(LOCAL_DIR, "sources.json")


def local_sources(root: str) -> dict[str, str]:
    path = os.path.join(root, LOCAL_SOURCES)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_local(root: str, asset_src: str, path: str) -> None:
    sources = local_sources(root)
    if path:
        sources[asset_src] = path
    else:
        sources.pop(asset_src, None)
    directory = os.path.join(root, LOCAL_DIR)
    os.makedirs(directory, exist_ok=True)
    ignore = os.path.join(directory, ".gitignore")
    if not os.path.isfile(ignore):
        with open(ignore, "w", encoding="utf-8") as handle:
            handle.write("*\n")
    with open(os.path.join(root, LOCAL_SOURCES), "w", encoding="utf-8") as handle:
        json.dump(sources, handle, indent="\t")


def source_choice(root: str, asset_src: str) -> str:
    """How the source is chosen: ``personal`` (only for you), ``shared`` (.bbsrc),
    or empty (convention: .blend next to the asset)."""
    if asset_src in local_sources(root):
        return "personal"
    if os.path.isfile(override_path(root, asset_src)):
        return "shared"
    return ""


def _models_of(scene: bpy.types.Scene, asset_src: str) -> list[bpy.types.Object]:
    return [o for o in scene_models(scene) if o.get(P_SRC) == asset_src]


def choose_source(scene: bpy.types.Scene, asset_src: str, blend_path: str) -> tuple[str, bool]:
    """Sets an existing .blend as the asset's source and relinks all its
    instances. Returns (path, personal).

    Inside the project it's saved to the shared ``.bbsrc`` (relative to the root).
    Outside the project it's saved only for you; others on the team won't see it.
    """
    root = scene.get(S_ROOT, "")
    if not root:
        raise BridgeError("the scene has no manifest loaded")
    absolute = os.path.abspath(blend_path)
    if not os.path.isfile(absolute) or not absolute.lower().endswith(".blend"):
        raise BridgeError("pick an existing .blend file")
    try:
        relative = os.path.relpath(absolute, root)
    except ValueError:   # Windows: a different drive than the project
        relative = absolute
    personal = relative.startswith("..") or os.path.isabs(relative)

    stem = os.path.basename(asset_src).rsplit(".", 1)[0]
    collection = _link_library_collection(absolute, stem)
    if personal:
        stored = absolute
        _write_local(root, asset_src, absolute)
    else:
        stored = relative.replace(os.sep, "/")
        marker = override_path(root, asset_src)
        if stored == expected_source(asset_src):
            if os.path.isfile(marker):
                os.remove(marker)
        else:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(stored)
        if asset_src in local_sources(root):
            _write_local(root, asset_src, "")
    for obj in _models_of(scene, asset_src):
        obj.instance_collection = collection
        obj[P_TIER] = "library"
        obj[P_SRC_BLEND] = stored
    return stored, personal


def clear_source(scene: bpy.types.Scene, asset_src: str) -> None:
    """Clears the hand-picked source, personal first, then shared. Whatever is
    left applies again: the shared .bbsrc, the .blend next to the asset, otherwise the .glb preview."""
    root = scene.get(S_ROOT, "")
    if source_choice(root, asset_src) == "personal":
        _write_local(root, asset_src, "")
    elif os.path.isfile(override_path(root, asset_src)):
        os.remove(override_path(root, asset_src))
    for obj in _models_of(scene, asset_src):
        entry = {"name": obj.name, "src": asset_src}
        collection, relative = _resolve_source(entry, root)
        obj.instance_collection = collection
        obj[P_TIER] = "library" if relative else "none"
        if relative:
            obj[P_SRC_BLEND] = relative
        else:
            obj.pop(P_SRC_BLEND, None)
