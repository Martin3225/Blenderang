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

# On a collection in a source .blend, all shared with the team:
# C_ASSET: the asset its glTF exporter writes, as a ``res://`` path. The exporter's
#   own path is relative to the .blend and differs between disks; it's rebuilt from this.
# C_PROJECT: the Godot project's name (``config/name``), to find the project on this
#   disk when the .blend lies outside it and its models folder.
# C_AUTO: saving the .blend exports the model (default on).
# C_UID: Godot's ``uid://`` of the asset (from its ``.import``), to find the asset
#   again after it's moved or renamed in Godot.
# Together they make the .blend "linked": nothing about it is kept on this machine.
C_ASSET = "bb_asset"
C_PROJECT = "bb_project"
C_AUTO = "bb_auto_export"
C_UID = "bb_uid"

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


def _link_library_collection(blend_path: str, asset_src: str, root: str) -> bpy.types.Collection:
    """Links the collection that exports the asset from the source .blend.

    All collections of the file are linked once (the exporter is needed to tell
    which one is the asset); repeated calls reuse them.
    """
    linked = [c for c in bpy.data.collections
              if c.library is not None and _same_file(bpy.path.abspath(c.library.filepath), blend_path)]
    if not linked:
        with bpy.data.libraries.load(blend_path, link=True) as (data_from, data_to):
            if not data_from.collections:
                raise BridgeError("%s contains no collection" % blend_path)
            data_to.collections = list(data_from.collections)
        linked = [c for c in data_to.collections if c is not None]
    chosen = model_collection(linked, asset_src, root)
    if chosen is None:
        raise BridgeError("could not link a collection from %s" % blend_path)
    return chosen


def exported_asset(collection: bpy.types.Collection, root: str) -> str:
    """``res://`` path the collection exports to, or empty when it isn't in the project."""
    stored = str(collection.get(C_ASSET, ""))
    if stored:
        return stored
    exporter = gltf_exporter(collection)
    if exporter is None or not exporter.filepath or not root:
        return ""
    inside = _relative_inside(bpy.path.abspath(exporter.filepath, library=collection.library), root)
    return "res://" + inside if inside else ""


def model_collection(collections: list[bpy.types.Collection], asset_src: str, root: str) -> bpy.types.Collection | None:
    """The collection that is the asset's model.

    The one whose exporter writes the asset; then one whose exporter writes a
    file of that name (the project is elsewhere on this disk); for sources
    without exporters the one named after the asset, otherwise the first
    collection that doesn't export anything else.
    """
    collections = list(collections)
    for collection in collections:
        if exported_asset(collection, root) == asset_src:
            return collection
    name = os.path.basename(asset_src).lower()
    for collection in collections:
        exporter = gltf_exporter(collection)
        if exporter is not None and os.path.basename(exporter.filepath.replace("\\", "/")).lower() == name:
            return collection
    stem = name.rsplit(".", 1)[0]
    free = [c for c in collections if not len(c.exporters)]
    return next((c for c in free if c.name.lower() == stem), free[0] if free else None)


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
    """Path to the source .blend as kept on the model: relative to the project,
    ``models://…`` inside the models folder, absolute for a personal source;
    empty when there is none. ``source_abs`` turns it into a file path.

    Same rule as BBPaths in Godot: personal choice (only for you) →
    ``<asset>.bbsrc`` (shared) → ``.blend`` next to the asset →
    ``<name>.blend`` in the models folder. Blender evaluates it itself so it
    sees a newly picked source right away.
    """
    asset = entry.get("src", "")
    personal = local_sources(root).get(asset, "")
    if personal and os.path.isfile(personal):
        return personal
    override = asset_abs(root, asset) + ".bbsrc"
    if os.path.isfile(override):
        with open(override, encoding="utf-8") as handle:
            stored = handle.read().strip().replace("res://", "", 1)
    else:
        stored = expected_source(asset)
        if not os.path.isfile(os.path.join(root, stored)):
            stored = find_in_models_folder(root, asset)
    absolute = source_abs(root, stored) if stored else ""
    return stored if absolute and os.path.isfile(absolute) else ""


def source_abs(root: str, stored: str) -> str:
    """File path of a source as ``source_of`` returns it; empty for a
    ``models://`` path when the models folder isn't set."""
    if stored.startswith(MODELS_PREFIX):
        folder = models_folder(root)
        return os.path.join(folder, *stored[len(MODELS_PREFIX):].split("/")) if folder else ""
    return os.path.join(root, stored)   # an absolute (personal) path stays as it is


def _resolve_source(entry: dict[str, Any], root: str) -> tuple[bpy.types.Collection | None, str]:
    """The collection the instance will point to (linked source, or preview)
    and the stored path of the source, if there is one."""
    stored = source_of(entry, root)
    if stored:
        try:
            return _link_library_collection(source_abs(root, stored), entry.get("src", ""), root), stored
        except (OSError, BridgeError) as error:
            # A broken or empty .blend must not crash opening the whole scene.
            print("Blenderang: cannot load source %s (%s), using the .glb preview" % (stored, error))
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
    if message in WARNINGS:
        return
    WARNINGS.append(message)
    print("Blenderang:", message)


def build(scene: bpy.types.Scene, manifest_path: str) -> dict[str, int]:
    """Builds the scene from the manifest. Replaces existing BB objects.

    One broken file must not crash the whole build: a model without a preview stays
    as an empty axis at its place, a broken context is replaced by bounding boxes.
    """
    WARNINGS.clear()
    forget_models_index()   # the models folder may have changed (git pull)
    manifest = load_manifest(manifest_path)
    root = project_root_for(manifest_path)
    remember_project(root)

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
    counts = {"kept": 0, "moved": 0, "added": 0, "removed": 0}
    taken: set[str] = set()

    # Shift+D copies the id too. The object still named as the entry was sent is
    # the original, whatever the copy is called; otherwise the copy would take over
    # the Godot node and the original would come back as a new instance.
    models = sorted(scene_models(scene),
                    key=lambda obj: originals.get(str(obj.get(P_ID, "")), {}).get("name") != obj.name)
    for obj in models:
        entry, is_new = _entry_for(obj, originals, taken)
        if entry is None:
            continue
        taken.add(entry["bb_id"])
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
    Collisions are therefore resolved here, at export: the first object with the
    id keeps it, so ``export`` visits the one with the entry's name first.
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
    return template, True


def _xform_differs(left: list[float], right: list[float], epsilon: float = 1e-5) -> bool:
    return any(abs(a - b) > epsilon for a, b in zip(left, right))


# --------------------------------------------------- moving the source of truth


def expected_source(asset_src: str) -> str:
    """Convention: the source sits next to the asset with the same name."""
    return os.path.splitext(asset_src.replace("res://", "", 1))[0] + ".blend"


def asset_abs(root: str, asset_src: str) -> str:
    return os.path.join(root, asset_src.replace("res://", "", 1))


def gltf_exporter(collection: bpy.types.Collection) -> bpy.types.CollectionExport | None:
    exporter = next((e for e in collection.exporters if e.name.lower().startswith("gltf")), None)
    if exporter is None and len(collection.exporters):
        exporter = collection.exporters[0]
    return exporter


def set_export_target(collection: bpy.types.Collection, target: str, root: str,
                      blend_path: str = "") -> bpy.types.CollectionExport:
    """Points the collection's glTF exporter at the file, adding one with Blender's
    defaults (and *Apply modifiers* on) when it has none. The path is relative to
    ``blend_path`` (default: the open file). Inside the project the ``res://`` path
    and the project's name are kept on the collection too, so the .blend exports
    to the right place on every disk."""
    exporter = gltf_exporter(collection)
    if exporter is None:
        with bpy.context.temp_override(collection=collection):
            bpy.ops.collection.exporter_add(name="IO_FH_gltf2")
        exporter = collection.exporters[-1]
    # Blender copies it into export_properties.
    exporter.filepath = _export_path(target, blend_path or bpy.data.filepath)
    props = exporter.export_properties
    if hasattr(props, "export_format"):
        props.export_format = "GLTF_SEPARATE" if target.lower().endswith(".gltf") else "GLB"
    _apply_modifiers_by_default(exporter)
    _share_target(collection, _relative_inside(target, root) if root else "", root)
    return exporter


def _apply_modifiers_by_default(exporter: bpy.types.CollectionExport) -> None:
    """*Apply modifiers* on, so booleans and other modifiers end up in the .glb.
    Only while nobody set it: switched off by hand (shape keys), it stays off."""
    props = exporter.export_properties
    if hasattr(props, "export_apply") and not props.is_property_set("export_apply"):
        props.export_apply = True


def apply_modifiers_by_default() -> None:
    """``_apply_modifiers_by_default`` for every exporter of the open file's models,
    including ones added in Blender's own Collection Exporters UI."""
    for collection in model_collections():
        for exporter in collection.exporters:
            _apply_modifiers_by_default(exporter)


def _share_target(collection: bpy.types.Collection, inside: str, root: str) -> None:
    """Stores where the collection exports in the project (``inside``, relative to
    ``root``), or clears it for an exporter writing outside the project. Godot's
    uid belongs to the old asset, so another path drops it."""
    if not inside:
        for key in (C_ASSET, C_PROJECT, C_UID):
            collection.pop(key, None)
        return
    if collection.get(C_ASSET) != "res://" + inside:
        collection.pop(C_UID, None)
    for key, value in ((C_ASSET, "res://" + inside), (C_PROJECT, project_name(root))):
        if collection.get(key) != value:
            collection[key] = value


def _export_path(target: str, blend_path: str) -> str:
    """Exporter path for an absolute target: relative to the .blend (``//…``), so
    the shared file holds no path from one person's disk. Absolute while the .blend
    isn't saved, lies on another drive, or was opened through Flatpak's document
    portal (its folder there holds nothing else)."""
    if not blend_path or host_path(blend_path) != blend_path:
        return target
    try:
        relative = os.path.relpath(target, os.path.dirname(os.path.abspath(blend_path)))
    except ValueError:   # Windows: a different drive
        return target
    return "//" + relative.replace(os.sep, "/")


def model_collections() -> list[bpy.types.Collection]:
    """The models of the open .blend: its own collections with an exporter."""
    return [c for c in bpy.data.collections
            if c.library is None and len(c.exporters) and c.name != COLL_CONTEXT and not c.get(P_PREVIEW)]


def _has_path(collection: bpy.types.Collection) -> bool:
    exporter = gltf_exporter(collection)
    return exporter is not None and bool(exporter.filepath)


def _copies(models: list[bpy.types.Collection]) -> set[str]:
    """Names of models copied from another (Duplicate Collection): the copy keeps
    the ``res://`` path, but Blender clears its exporter's path. ``libraries.write``
    clears it too, so only a second model with the same ``res://`` path makes an
    exporter without a path a copy. The one with a path, otherwise the first, is the original."""
    groups: dict[str, list[bpy.types.Collection]] = {}
    for collection in models:
        if collection.get(C_ASSET):
            groups.setdefault(str(collection[C_ASSET]), []).append(collection)
    copies: set[str] = set()
    for group in groups.values():
        if len(group) > 1:
            original = next((c for c in group if _has_path(c)), group[0])
            copies.update(c.name for c in group if c != original and not _has_path(c))
    return copies


def linked_models() -> list[bpy.types.Collection]:
    """Models exporting into a Godot project (they carry its ``res://`` path)."""
    models = model_collections()
    copies = _copies(models)
    return [c for c in models if c.get(C_ASSET) and c.name not in copies]


def localize_export_paths(root: str, blend_path: str = "") -> None:
    """Exporter paths rebuilt from the shared ``res://`` paths for the project as
    it lies on this disk, relative to ``blend_path`` (default: the open file)."""
    blend_path = blend_path or bpy.data.filepath
    for collection in linked_models():
        exporter = gltf_exporter(collection)
        if exporter is not None:
            path = _export_path(asset_abs(root, str(collection[C_ASSET])), blend_path)
            if exporter.filepath != path:
                exporter.filepath = path


def remember_export_paths(root: str) -> None:
    """Before saving: the ``res://`` path of every exporter writing into the
    project, so the shared .blend finds the asset on another disk too. An
    exporter pointed outside the project keeps only its own path; a copied model
    without a path drops the one it was copied with."""
    models = model_collections()
    copies = _copies(models)
    for collection in models:
        exporter = gltf_exporter(collection)
        if collection.name in copies:
            _share_target(collection, "", root)
        elif exporter is not None and exporter.filepath:
            _share_target(collection, _relative_inside(bpy.path.abspath(exporter.filepath), root), root)


def _import_uid(import_path: str) -> str:
    """The ``uid://…`` in a Godot ``.import`` file, or empty."""
    try:
        with open(import_path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("uid="):
                    return line.split("=", 1)[1].strip().strip('"')
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def remember_asset_uids(root: str) -> None:
    """Godot's uid of each linked asset, once Godot has imported it (its ``.import``
    is in the project), so ``follow_moved_assets`` can find it after a move."""
    for collection in linked_models():
        uid = _import_uid(asset_abs(root, str(collection[C_ASSET])) + ".import")
        if uid and collection.get(C_UID) != uid:
            collection[C_UID] = uid


def follow_moved_assets(root: str) -> list[str]:
    """Models whose asset was moved or renamed in Godot export to the new path:
    the file at the stored path is gone, and the ``.import`` with its uid is
    elsewhere in the project. Otherwise the next export would recreate the asset
    at its old path. Returns the new ``res://`` paths."""
    lost = {str(c[C_UID]): c for c in linked_models()
            if c.get(C_UID) and not os.path.isfile(asset_abs(root, str(c[C_ASSET])))}
    moved: list[str] = []
    if not lost:
        return moved
    for folder, folders, files in os.walk(root):
        folders[:] = [name for name in folders if not name.startswith(".")]   # .godot, .git, .pipeline
        for name in files:
            if not name.endswith(".import"):
                continue
            collection = lost.pop(_import_uid(os.path.join(folder, name)), None)
            if collection is None:
                continue
            asset = os.path.join(folder, name[:-len(".import")])
            print("Blenderang: %s moved in Godot to %s" % (collection[C_ASSET], res_path(root, asset)))
            set_export_target(collection, asset, root)
            moved.append(res_path(root, asset))
            if not lost:
                return moved
    return moved


def sync_export_paths(root: str, blend_path: str = "") -> None:
    """Before saving or exporting: follow assets moved in Godot, take paths typed
    into the exporters, record Godot's uids, point the exporters at the project
    on this disk relative to ``blend_path`` (default: the open file), and turn
    *Apply modifiers* on for exporters added since."""
    follow_moved_assets(root)
    remember_export_paths(root)
    remember_asset_uids(root)
    localize_export_paths(root, blend_path)
    apply_modifiers_by_default()


def export_collection(collection: bpy.types.Collection) -> None:
    """Runs all exporters of the collection. ``wm.collection_export_all`` isn't
    enough; it only exports collections that are in the view layer.

    The exporters read evaluated objects. A model outside the view layer (not in
    the scene or excluded: the other models of a .blend while one is edited) would
    export empty or without its modifiers, so it's exported from a temporary scene
    of its own instead."""
    in_view_layer = set(bpy.context.view_layer.objects)
    if all(obj in in_view_layer for obj in collection.all_objects):
        with bpy.context.temp_override(collection=collection):
            bpy.ops.collection.export_all()
        return
    scene = bpy.data.scenes.new("BB_Export")
    try:
        scene.collection.children.link(collection)
        with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0], collection=collection):
            bpy.ops.collection.export_all()
    finally:
        bpy.data.scenes.remove(scene)


def export_models(root: str, on_save: bool = False) -> int:
    """Exports the models of the open .blend, on save only those with auto save
    on; returns how many. Each asset Godot wouldn't find this file for gets a
    ``.bbsrc`` pointing at it (``link_source``)."""
    forget_models_index()   # this file may be new in the models folder
    blend_path = host_path(bpy.data.filepath)
    exported = 0
    for collection in model_collections():
        if on_save and not collection.get(C_AUTO, True):
            continue
        if any(e.filepath for e in collection.exporters):
            export_collection(collection)
            exported += 1
            asset = exported_asset(collection, root)
            if asset and blend_path:
                link_source(root, asset, blend_path)
    return exported


def shared_source(root: str, blend_path: str) -> str:
    """How ``.bbsrc`` stores the .blend for everyone: relative to the project, or
    ``models://…`` inside the models folder; empty for a file outside both."""
    absolute = os.path.abspath(blend_path)
    stored = _relative_inside(absolute, root)
    if not stored:
        inside_models = _relative_inside(absolute, models_folder(root))
        stored = MODELS_PREFIX + inside_models if inside_models else ""
    return stored


def link_source(root: str, asset_src: str, blend_path: str) -> bool:
    """Makes Godot find ``blend_path`` as the asset's source when it finds none
    (the .blend is named differently, or exports several models): writes the
    shared ``<asset>.bbsrc``. An asset with another source keeps it; a .blend
    outside the project and the models folder can't be shared. True when written."""
    if source_of({"src": asset_src}, root):
        return False
    stored = shared_source(root, blend_path)
    if not stored:
        return False
    with open(override_path(root, asset_src), "w", encoding="utf-8") as handle:
        handle.write(stored)
    return True


def auto_export() -> bool:
    """Does saving the .blend export it? Stored in the file, the same for everyone."""
    models = model_collections()
    return bool(models) and all(bool(c.get(C_AUTO, True)) for c in models)


def set_auto_export(enabled: bool) -> None:
    for collection in model_collections():
        collection[C_AUTO] = enabled


def promote_to_library(obj: bpy.types.Object, root: str) -> str:
    """Turns a preview imported from .glb into its own source .blend.

    The collection is written to a new file (``new_source``) with the export
    already set up, the local copy is removed and the file is linked in its place.
    From then on the .blend is the source of truth.
    """
    collection = obj.instance_collection
    if collection is None:
        raise BridgeError("the object has nothing to save; the .glb preview is missing too")
    if collection.library is not None:
        raise BridgeError("the asset already has a source")

    asset_src = str(obj.get(P_SRC, ""))
    stored = new_source(root, asset_src)
    target = source_abs(root, stored)
    if os.path.exists(target):
        raise BridgeError("%s already exists; pick it as the source" % target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    collection.pop(P_PREVIEW, None)
    set_export_target(collection, asset_abs(root, asset_src), root, target)
    bpy.data.libraries.write(target, {collection}, fake_user=True)
    forget_models_index()

    # The same asset can have several instances in the scene; all are relinked.
    instances = [o for o in bpy.data.objects if o.instance_collection == collection]
    for child in list(collection.all_objects):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.collections.remove(collection)

    linked = _link_library_collection(target, asset_src, root)
    for instance in instances:
        instance.instance_collection = linked
        instance[P_TIER] = "library"
        instance[P_SRC_BLEND] = stored
    return stored


def new_source(root: str, asset_src: str) -> str:
    """Where *Make source* creates the .blend: at the asset's own path inside
    the models folder when one is set (so the name search finds it for
    everyone), otherwise next to the asset."""
    if models_folder(root):
        return MODELS_PREFIX + models_relative(root, asset_src)
    return expected_source(asset_src)


# ------------------------------------------------------------ source editing
#
# "Edit source" opens the .blend of one asset. So the surroundings aren't missing,
# a temporary BB_Context collection with everything else from the scene is built
# into it from the manifest, offset as if the asset stood at its place. The context
# is removed before every save and restored after, so it's never written into the
# source file.

COLL_CONTEXT = "BB_Context"


def _sessions_path() -> str:
    """Model edits from a scene in progress, in Blender's user config, keyed by
    source file: the manifest to return to and the model to build the context around.
    An entry without a manifest is a source Godot just asked to open; it's taken
    when the file loads. One entry per source lets several Blender windows each
    edit a different model. What a .blend exports to isn't kept here, it's in the file.
    """
    return os.path.join(bpy.utils.user_resource("CONFIG", create=True), "blenderang_edit.json")


def _projects_path() -> str:
    """Godot projects known on this machine, in Blender's user config. A project
    is added when Blender opens it from Godot; *Link to Godot* looks among
    them for the one a .blend belongs to."""
    return os.path.join(bpy.utils.user_resource("CONFIG", create=True), "blenderang_projects.json")


def projects() -> list[str]:
    try:
        with open(_projects_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [str(p) for p in data] if isinstance(data, list) else []


def _write_projects(roots: list[str]) -> None:
    with open(_projects_path(), "w", encoding="utf-8") as handle:
        json.dump(roots, handle, indent="\t")


def remember_project(root: str) -> None:
    root = os.path.normpath(os.path.abspath(root))
    known = projects()
    if not any(_same_file(root, other) for other in known):
        _write_projects(sorted(known + [root]))


def forget_project(root: str) -> None:
    _write_projects([other for other in projects() if not _same_file(root, other)])


def _known_projects() -> list[str]:
    return [root for root in projects() if os.path.isfile(os.path.join(root, "project.godot"))]


def project_for(blend_path: str, name: str = "") -> tuple[str, str]:
    """(Godot project, ``res://`` path of the .glb) a .blend exports to by
    convention: next to it when it lies in a project, at the mirrored path when
    it lies in a project's models folder (the project called ``name`` wins when
    several share the folder). Elsewhere only the project called ``name``, with
    no path. Empty strings when nothing fits."""
    blend_path = host_path(blend_path)
    known = _known_projects()
    for root in known:
        inside = _relative_inside(blend_path, root)
        if inside:
            return root, "res://" + os.path.splitext(inside)[0] + ".glb"
    mirrors = [(root, inside) for root in known
               for inside in [_relative_inside(blend_path, models_folder(root))] if inside]
    if mirrors:
        root, inside = next((m for m in mirrors if name and project_name(m[0]) == name), mirrors[0])
        return root, models_asset(root, inside)
    if name:
        return next((root for root in known if project_name(root) == name), ""), ""
    return "", ""


def suggested_asset(root: str, blend_path: str, folder: str | None = None) -> tuple[str, bool]:
    """``res://`` path of the .glb a .blend exports to in the project ``root``, and
    whether it follows the file's place: inside the project next to it, inside
    the models folder (``folder``, default the project's) at the mirrored path.
    Elsewhere only a guess, the mirrored folder + the file's name."""
    blend_path = host_path(blend_path)
    inside = _relative_inside(blend_path, root)
    if inside:
        return "res://" + os.path.splitext(inside)[0] + ".glb", True
    folder = models_folder(root) if folder is None else os.path.abspath(bpy.path.abspath(folder)) if folder else ""
    inside = _relative_inside(blend_path, folder)
    if inside:
        return models_asset(root, inside), True
    return models_asset(root, os.path.basename(blend_path)), False


def _session_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _read_sessions() -> dict[str, Any]:
    try:
        with open(_sessions_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_sessions(sessions: dict[str, Any]) -> None:
    path = _sessions_path()
    if not sessions:
        if os.path.isfile(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(sessions, handle, indent="\t")


def _start_session(session: dict[str, Any]) -> None:
    """Writes the session; entries of files that no longer exist are dropped."""
    key = _session_key(session["source"])
    sessions = {other: value for other, value in _read_sessions().items()
                if isinstance(value, dict) and os.path.isfile(str(value.get("source", "")))}
    sessions[key] = session
    _write_sessions(sessions)


def begin_edit(scene: bpy.types.Scene, obj: bpy.types.Object) -> str:
    """Sends pending changes to Godot and prepares source editing.

    Returns the path to the source .blend to open.
    """
    root = scene.get(S_ROOT, "")
    stored = obj.get(P_SRC_BLEND, "")
    if not root or not stored:
        raise BridgeError("the asset has no source .blend")
    source = source_abs(root, stored)
    if not source:
        raise BridgeError("%s needs the models folder; set it in the Blenderang panel" % stored)
    if not os.path.isfile(source):
        raise BridgeError("source does not exist: %s" % source)
    manifest = stored_manifest_path(scene)
    export(scene)
    _start_session({
        "manifest": manifest,
        "bb_id": str(obj.get(P_ID, "")),
        "source": os.path.abspath(source),
        "asset": str(obj.get(P_SRC, "")),
        "root": root,
    })
    return source


def begin_source_edit(root: str, asset_src: str, source: str) -> str:
    """Prepares editing a source opened straight from Godot's FileSystem: no
    scene around it. Loading the file takes the entry (``take_opened_source``)
    and makes the model export to the asset."""
    if not os.path.isfile(source):
        raise BridgeError("source does not exist: %s" % source)
    with bpy.data.libraries.load(source) as (data_from, _):
        available = list(data_from.collections)
    if not available:
        raise BridgeError("%s contains no collection" % source)
    remember_project(root)
    _start_session({
        "manifest": "",
        "bb_id": "",
        "source": os.path.abspath(source),
        "asset": asset_src,
        "root": root,
    })
    return source


def _open_file_session() -> dict[str, Any] | None:
    if not bpy.data.filepath:
        return None
    session = _read_sessions().get(_session_key(bpy.data.filepath))
    return dict(session) if isinstance(session, dict) and "root" in session else None


def edit_session() -> dict[str, Any] | None:
    """The model edit from a scene in progress, if its source is the file currently open."""
    session = _open_file_session()
    return session if session is not None and session.get("manifest") else None


def take_opened_source() -> dict[str, Any] | None:
    """The open file's entry from *Open source in Blender*, removed once taken.
    Entries from older versions, which bound a source to its asset on this
    machine, are taken the same way; the binding moves into the file."""
    session = _open_file_session()
    if session is None or session.get("manifest"):
        return None
    sessions = _read_sessions()
    sessions.pop(_session_key(bpy.data.filepath), None)
    _write_sessions(sessions)
    return session


def file_root() -> str:
    """The Godot project the open .blend exports into, on this disk; empty when
    it isn't linked. Found from the file's place (in a project or its models
    folder), then by the project name the file carries; a file without a name
    uses the only known project."""
    session = edit_session()
    if session is not None:
        return session["root"]
    models = linked_models()
    if not models or not bpy.data.filepath:
        return ""
    name = next((str(c[C_PROJECT]) for c in models if c.get(C_PROJECT)), "")
    root = project_for(bpy.data.filepath, name)[0]
    if not root and not name:
        known = _known_projects()
        root = known[0] if len(known) == 1 else ""
    return root


def follow_save_as(filepath: str) -> None:
    """Save As and incremental save during a model edit from a scene: the new
    file goes on with the edit. The link to Godot needs nothing, it's in the file."""
    if not filepath or not bpy.data.filepath or _same_file(filepath, bpy.data.filepath):
        return
    session = edit_session()
    if session is not None:
        session["source"] = os.path.abspath(filepath)
        _start_session(session)


def link_file(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, project: str, target: str, auto: bool) -> None:
    """*Link to Godot*: the models of the open .blend export into the project with
    *Export now*, with ``auto`` on every save too. All of it is stored in the
    file, so it's linked the same way for everyone.

    A file that exports nothing yet gets a glTF exporter for ``target`` (``res://``
    path or file path) on the active collection; with the Scene Collection active,
    on a new collection named after the file that takes over the scene's objects.
    Apply modifiers is on so booleans end up in the .glb; the rest is Blender's defaults.
    A file that already exports (linked elsewhere, renamed) keeps its targets.
    """
    if not bpy.data.filepath:
        raise BridgeError("save the file first")
    root = os.path.normpath(os.path.abspath(bpy.path.abspath(project))) if project.strip() else ""
    if not root or not os.path.isfile(os.path.join(root, "project.godot")):
        raise BridgeError("pick the Godot project folder (the one with project.godot)")
    if not model_collections():
        target = target.strip()
        if not target:
            raise BridgeError("set where in the project the model is exported to")
        absolute = asset_abs(root, target) if target.startswith("res://") else os.path.abspath(bpy.path.abspath(target))
        if not absolute.lower().endswith((".glb", ".gltf")):
            raise BridgeError("export to a .glb or .gltf file")
        if not _relative_inside(absolute, root):
            raise BridgeError("export into the Godot project")
        collection = view_layer.active_layer_collection.collection
        if collection.library is not None:
            raise BridgeError("the active collection is linked from another file")
        if collection == scene.collection:
            collection = bpy.data.collections.new(os.path.splitext(os.path.basename(bpy.data.filepath))[0])
            scene.collection.children.link(collection)
            for obj in list(scene.collection.objects):
                collection.objects.link(obj)
                scene.collection.objects.unlink(obj)
            activate_collection(view_layer, collection)
        set_export_target(collection, absolute, root)
    apply_modifiers_by_default()   # exporters added in Blender's UI before linking
    remember_export_paths(root)
    if not linked_models():
        raise BridgeError("the file's exporters don't write into the Godot project")
    set_auto_export(auto)
    remember_project(root)
    localize_export_paths(root)
    forget_models_index()


def godot_status(root: str, asset_src: str) -> tuple[str, bool]:
    """What exporting the asset means in Godot, for the open file: (text, problem).

    Linked: Godot resolves the asset's source to this .blend (``source_of``, the
    same rule as BBPaths), so *Edit* in Godot opens it. An asset without a source
    gets linked by the export (``link_source``). A problem is an asset whose source
    is another .blend, or a file outside the project and the models folder, which
    Godot can't be told about.
    """
    exists = os.path.isfile(asset_abs(root, asset_src))
    stored = source_of({"src": asset_src}, root)
    source = source_abs(root, stored) if stored else ""
    blend_path = host_path(bpy.data.filepath)
    if source and _same_file(source, blend_path):
        return ("in Godot, linked to this file; export overwrites it" if exists
                else "new in Godot, linked to this file"), False
    if source:
        return "in Godot, its source is %s; export overwrites it" % stored, True
    if shared_source(root, blend_path):
        return ("in Godot without a source; export overwrites it and links this file" if exists
                else "new in Godot; export links this file as its source"), False
    return ("in Godot; export overwrites it, but Godot can't find this file outside the project "
            "and the models folder" if exists
            else "new in Godot; it can't find this file outside the project and the models folder"), True


def end_edit(session: dict[str, Any]) -> str:
    """Ends the model edit from a scene. The source stays linked to its asset by
    the file itself, so reopening it by hand still exports on save, without the
    scene context. Returns the manifest to rebuild the scene from."""
    sessions = _read_sessions()
    sessions.pop(_session_key(session["source"]), None)
    _write_sessions(sessions)
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
    if not session.get("manifest"):
        return 0   # opened from Godot's FileSystem, there is no scene around
    manifest = load_manifest(session["manifest"])
    focus = next((e for e in manifest["nodes"] if e.get("bb_id") == session["bb_id"]), None)
    if focus is None:
        return 0
    root = session["root"]
    to_local = godot_to_blender(focus["xform"]).inverted()
    edited = session_collection(session)

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
    """The collection of the model being edited from Godot, if there is one."""
    if not session.get("asset"):
        return None
    own = [c for c in bpy.data.collections
           if c.library is None and c.name != COLL_CONTEXT and not c.get(P_PREVIEW)]
    return model_collection(own, session["asset"], session["root"])


def activate_collection(view_layer: bpy.types.ViewLayer, collection: bpy.types.Collection) -> bool:
    """Makes the collection active in the outliner; Blender's exporter UI follows it."""
    pending = [view_layer.layer_collection]
    while pending:
        layer = pending.pop()
        if layer.collection == collection:
            view_layer.active_layer_collection = layer
            return True
        pending.extend(layer.children)
    return False


def setup_session_exporter(session: dict[str, Any]) -> bpy.types.Collection | None:
    """Makes sure the edited model exports to its asset: an exporter for a source
    that has none, the asset's path for one exported elsewhere (made on another
    disk before the path was shared). Other settings stay as they are."""
    collection = session_collection(session)
    if collection is None:
        if session.get("asset"):
            raise BridgeError("the file has no collection for %s" % session["asset"])
        return None
    asset = session["asset"]
    if exported_asset(collection, session["root"]) != asset or collection.get(C_ASSET) != asset:
        set_export_target(collection, asset_abs(session["root"], asset), session["root"])
    return collection


# ------------------------------------------------------------------ detail


def _source_label(obj: bpy.types.Object, tier: str, source: str) -> str:
    if tier != "library":
        root = bpy.context.scene.get(S_ROOT, "")
        return "none, will be created at %s" % new_source(root, str(obj.get(P_SRC, "")))
    if source.startswith(MODELS_PREFIX):
        return "%s (models folder)" % source[len(MODELS_PREFIX):]
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


# Personal files, never committed (the folder has a .gitignore with "*").
# Godot reads the same files (BBPaths).
# sources.json: personal choice of sources outside the project and the models folder.
# settings.json: where the models folder is on this disk.
LOCAL_DIR = os.path.join(".pipeline", "local")
LOCAL_SOURCES = os.path.join(LOCAL_DIR, "sources.json")
LOCAL_SETTINGS = os.path.join(LOCAL_DIR, "settings.json")

# Shared paths into the models folder: ``models://<path inside the folder>``.
# The folder is somewhere else on every disk; the path inside it is the same.
MODELS_PREFIX = "models://"


def _read_local_json(root: str, name: str) -> dict[str, Any]:
    path = os.path.join(root, name)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_local_json(root: str, name: str, data: dict[str, Any]) -> None:
    directory = os.path.join(root, LOCAL_DIR)
    os.makedirs(directory, exist_ok=True)
    ignore = os.path.join(directory, ".gitignore")
    if not os.path.isfile(ignore):
        with open(ignore, "w", encoding="utf-8") as handle:
            handle.write("*\n")
    with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent="\t")


def local_sources(root: str) -> dict[str, str]:
    return _read_local_json(root, LOCAL_SOURCES)


def _write_local(root: str, asset_src: str, path: str) -> None:
    sources = local_sources(root)
    if path:
        sources[asset_src] = path
    else:
        sources.pop(asset_src, None)
    _write_local_json(root, LOCAL_SOURCES, sources)


def models_folder(root: str) -> str:
    """Absolute path of the models folder on this disk, or empty when not set."""
    folder = str(_read_local_json(root, LOCAL_SETTINGS).get("models_folder", ""))
    return os.path.normpath(folder) if folder else ""


# Project setting (Project Settings ▸ Blenderang ▸ Models ▸ Project Folder): the
# folder of the Godot project the models folder mirrors. With the default, the
# source of ``res://assets/levels/castle.glb`` is ``levels/castle.blend`` in the
# models folder. Godot doesn't write a default value to project.godot.
SETTING_MIRROR_SECTION = "blenderang"
SETTING_MIRROR_KEY = "models/project_folder"
DEFAULT_MIRROR = "assets"


def _project_setting(root: str, section: str, key: str, default: str) -> str:
    """A string value from ``project.godot``; ``default`` when it isn't there."""
    value = default
    current = ""
    try:
        with open(os.path.join(root, "project.godot"), encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("["):
                    current = line.strip("[]")
                elif current == section and line.startswith(key + "="):
                    value = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return value


def models_mirror(root: str) -> str:
    """The project folder the models folder mirrors, without slashes; may be empty."""
    value = _project_setting(root, SETTING_MIRROR_SECTION, SETTING_MIRROR_KEY, DEFAULT_MIRROR)
    return value.replace("\\", "/").strip("/")


def project_name(root: str) -> str:
    """The project's name (``application/config/name``); a .blend keeps it to find
    the project on another disk."""
    return _project_setting(root, "application", "config/name", "")


def models_relative(root: str, asset_src: str) -> str:
    """Where the asset's source sits in the models folder by convention: the
    asset's path without the mirrored project folder (``res://assets/levels/castle.glb``
    → ``levels/castle.blend``). Assets outside that folder keep their whole path."""
    expected = expected_source(asset_src)
    mirror = models_mirror(root)
    return expected[len(mirror) + 1:] if mirror and expected.startswith(mirror + "/") else expected


def models_asset(root: str, relative_blend: str) -> str:
    """The opposite direction: ``res://`` path of the .glb a .blend at this path
    in the models folder exports to by convention."""
    mirror = models_mirror(root)
    base = os.path.splitext(relative_blend.replace(os.sep, "/"))[0] + ".glb"
    return "res://" + (mirror + "/" if mirror else "") + base


# .blend files in the models folder: folder → lowercase name → sorted paths inside it.
# Scanned once per scene build; ``forget_models_index`` drops it.
_MODELS_INDEX: dict[str, dict[str, list[str]]] = {}


def forget_models_index() -> None:
    _MODELS_INDEX.clear()


def _models_index(folder: str) -> dict[str, list[str]]:
    index = _MODELS_INDEX.get(folder)
    if index is not None:
        return index
    index = {}
    for current, directories, files in os.walk(folder):
        directories[:] = [name for name in directories if not name.startswith(".")]   # .git
        inside = os.path.relpath(current, folder)
        for name in files:
            if name.lower().endswith(".blend"):
                path = name if inside == os.curdir else os.path.join(inside, name)
                index.setdefault(name.lower(), []).append(path.replace(os.sep, "/"))
    for paths in index.values():
        paths.sort()
    _MODELS_INDEX[folder] = index
    return index


def find_in_models_folder(root: str, asset_src: str) -> str:
    """``models://…`` path of ``<asset name>.blend`` in the models folder, or empty.

    The name is matched case-insensitively at any depth. With several matches the
    one at the asset's mirrored path (``models_relative``) wins, otherwise
    the first alphabetically; picking the source by hand makes it explicit.
    """
    folder = models_folder(root)
    if not folder:
        return ""
    expected = models_relative(root, asset_src)
    name = os.path.basename(expected)
    matches = _models_index(folder).get(name.lower(), [])
    if not matches:
        return ""
    if expected in matches:
        return MODELS_PREFIX + expected
    if len(matches) > 1:
        warn("several %s in the models folder, using %s; pick the source to choose another" % (name, matches[0]))
    return MODELS_PREFIX + matches[0]


def _relative_inside(path: str, folder: str) -> str:
    """``path`` relative to ``folder`` with forward slashes, or empty when it's outside."""
    if not folder:
        return ""
    try:
        relative = os.path.relpath(path, folder)
    except ValueError:   # Windows: a different drive
        return ""
    if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
        return ""
    return relative.replace(os.sep, "/")


def res_path(root: str, path: str) -> str:
    """``res://`` path of a file path inside the project, or empty when it's outside."""
    inside = _relative_inside(os.path.abspath(bpy.path.abspath(path)), root) if root and path else ""
    return "res://" + inside if inside else ""


def host_path(path: str) -> str:
    """Where the file really is. Flatpak Blender gets a file opened from the file
    manager through the document portal, as ``/run/user/<uid>/doc/<id>/<name>``;
    the portal keeps the real path in an extended attribute. Other paths are
    returned as they are."""
    if path and hasattr(os, "getxattr"):
        try:
            return os.fsdecode(os.getxattr(path, "user.document-portal.host-path"))
        except OSError:
            pass
    return path


def source_choice(root: str, asset_src: str) -> str:
    """How the source is chosen: ``personal`` (only for you), ``shared`` (.bbsrc),
    or empty (convention: .blend next to the asset or found in the models folder)."""
    if asset_src in local_sources(root):
        return "personal"
    if os.path.isfile(override_path(root, asset_src)):
        return "shared"
    return ""


def _models_of(scene: bpy.types.Scene, asset_src: str) -> list[bpy.types.Object]:
    return [o for o in scene_models(scene) if o.get(P_SRC) == asset_src]


def choose_source(scene: bpy.types.Scene, asset_src: str, blend_path: str) -> tuple[str, bool]:
    """Sets an existing .blend as the asset's source and relinks all its
    instances. Returns (stored path, personal).

    Inside the project it's saved to the shared ``.bbsrc`` relative to the root,
    inside the models folder as ``models://…``. Anywhere else it's saved only
    for you; others on the team won't see it.
    """
    root = scene.get(S_ROOT, "")
    if not root:
        raise BridgeError("the scene has no manifest loaded")
    absolute = os.path.abspath(blend_path)
    if not os.path.isfile(absolute) or not absolute.lower().endswith(".blend"):
        raise BridgeError("pick an existing .blend file")
    stored = shared_source(root, absolute)
    personal = not stored

    collection = _link_library_collection(absolute, asset_src, root)
    if personal:
        stored = absolute
        _write_local(root, asset_src, absolute)
    else:
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
    left applies again: the shared .bbsrc, the .blend next to the asset or in the
    models folder, otherwise the .glb preview."""
    root = scene.get(S_ROOT, "")
    if source_choice(root, asset_src) == "personal":
        _write_local(root, asset_src, "")
    elif os.path.isfile(override_path(root, asset_src)):
        os.remove(override_path(root, asset_src))
    _relink(scene, root, asset_src)


def set_models_folder(scene: bpy.types.Scene, folder: str) -> None:
    """Sets where the models folder is on this disk (empty unsets it) and
    relinks every model, so sources found there show up without a rebuild."""
    root = scene.get(S_ROOT, "")
    if not root:
        raise BridgeError("the scene has no manifest loaded")
    store_models_folder(root, folder)
    for asset_src in sorted({str(obj.get(P_SRC, "")) for obj in scene_models(scene)}):
        _relink(scene, root, asset_src)


def store_models_folder(root: str, folder: str) -> None:
    """Writes where the project's models folder is on this disk (empty unsets it)
    to its personal settings, which Godot reads too."""
    settings = _read_local_json(root, LOCAL_SETTINGS)
    if folder:
        folder = os.path.abspath(bpy.path.abspath(folder))
        if not os.path.isdir(folder):
            raise BridgeError("pick an existing models folder")
        settings["models_folder"] = folder.replace(os.sep, "/")
    else:
        settings.pop("models_folder", None)
    _write_local_json(root, LOCAL_SETTINGS, settings)
    forget_models_index()


def _relink(scene: bpy.types.Scene, root: str, asset_src: str) -> None:
    """Points all instances of the asset at its source as resolved now."""
    for obj in _models_of(scene, asset_src):
        collection, stored = _resolve_source({"name": obj.name, "src": asset_src}, root)
        obj.instance_collection = collection
        obj[P_TIER] = "library" if stored else "none"
        if stored:
            obj[P_SRC_BLEND] = stored
        else:
            obj.pop(P_SRC_BLEND, None)
