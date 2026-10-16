"""Jádro mostu mezi Godot manifestem a Blender scénou.

Manifest nese pouze identity a transformace. Geometrie se nikdy nepřenáší —
assety se do layoutu linkují ze svých zdrojových .blend souborů, nebo leží
lokálně přímo v layoutu (tier ``local``).
"""

from __future__ import annotations

import json
import os
from typing import Any

import bpy
from mathutils import Matrix, Vector

# Vlastní properties, podle kterých addon pozná svoje objekty.
P_ID = "bb_id"
P_PATH = "bb_path"
P_SRC = "bb_src"
P_TIER = "bb_tier"
P_PARENT = "bb_parent"
P_SRC_BLEND = "bb_src_blend"
P_PREVIEW = "bb_preview"

S_MANIFEST = "bb_manifest"
S_ROOT = "bb_project_root"

COLL_LAYOUT = "BB_Layout"
COLL_LOCKED = "BB_Locked"
COLL_SOURCES = "BB_Sources"

# Godot: X vpravo, Y nahoru, -Z dopředu. Blender: X vpravo, Y dopředu, Z nahoru.
# Převod báze mezi soustavami; matice je ortogonální, takže inverze == transpozice.
_AXIS = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
_AXIS_INV = _AXIS.transposed()


class BridgeError(Exception):
    """Chyba, kterou má smysl ukázat uživateli v hlášce operátoru."""


# ---------------------------------------------------------------- transformace


def godot_to_blender(xform: list[float]) -> Matrix:
    """12 floatů z manifestu (tři sloupce báze, pak origin) na Blender matici."""
    if len(xform) != 12:
        raise BridgeError("transformace musí mít 12 složek, má %d" % len(xform))
    basis = Matrix((
        (xform[0], xform[3], xform[6]),
        (xform[1], xform[4], xform[7]),
        (xform[2], xform[5], xform[8]),
    ))
    converted = _AXIS @ basis @ _AXIS_INV
    origin = _AXIS @ Vector((xform[9], xform[10], xform[11]))
    return Matrix.Translation(origin) @ converted.to_4x4()


def blender_to_godot(matrix: Matrix) -> list[float]:
    """Opačný směr; výstup je přímo pole pro manifest."""
    basis = _AXIS_INV @ matrix.to_3x3() @ _AXIS
    origin = _AXIS_INV @ matrix.to_translation()
    return [
        basis[0][0], basis[1][0], basis[2][0],
        basis[0][1], basis[1][1], basis[2][1],
        basis[0][2], basis[1][2], basis[2][2],
        origin.x, origin.y, origin.z,
    ]


# --------------------------------------------------------------------- soubory


def load_manifest(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise BridgeError("manifest neexistuje: %s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") != 1:
        raise BridgeError("neznámá verze manifestu: %r" % data.get("format"))
    return data


def save_manifest(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent="\t", ensure_ascii=False)
        handle.write("\n")


def project_root_for(manifest_path: str) -> str:
    """Manifest leží v ``<kořen>/.pipeline/<scéna>.json``."""
    pipeline = os.path.dirname(os.path.abspath(manifest_path))
    if os.path.basename(pipeline) != ".pipeline":
        raise BridgeError("manifest musí ležet v adresáři .pipeline, je v %s" % pipeline)
    return os.path.dirname(pipeline)


def stored_manifest_path(scene: bpy.types.Scene) -> str:
    path = scene.get(S_MANIFEST, "")
    if not path:
        raise BridgeError("tato scéna nemá načtený manifest")
    return path


# ------------------------------------------------------------------- kolekce


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
    """Windows má cesty case-insensitive a míchá oddělovače."""
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _link_library_collection(blend_path: str, name: str) -> bpy.types.Collection:
    """Nalinkuje kolekci ze zdrojového .blend. Opakované volání nelinkuje znovu."""
    for collection in bpy.data.collections:
        library = collection.library
        if library is None:
            continue
        if _same_file(bpy.path.abspath(library.filepath), blend_path) and collection.name == name:
            return collection
    with bpy.data.libraries.load(blend_path, link=True) as (data_from, data_to):
        available = list(data_from.collections)
        if not available:
            raise BridgeError("%s neobsahuje žádnou kolekci" % blend_path)
        picked = name if name in available else available[0]
        data_to.collections = [picked]
    linked = data_to.collections[0]
    if linked is None:
        raise BridgeError("nepodařilo se nalinkovat kolekci z %s" % blend_path)
    return linked


def _import_asset(asset_abs: str, target: bpy.types.Collection) -> bool:
    """Naimportuje .glb/.gltf/.fbx do kolekce. Slouží jako náhled assetu,
    který ještě nemá zdrojový .blend, a jako základ při výrobě zdroje."""
    if not os.path.isfile(asset_abs):
        return False
    extension = os.path.splitext(asset_abs)[1].lower()
    objects_before = set(bpy.data.objects)
    collections_before = set(bpy.data.collections)
    if extension in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=asset_abs)
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=asset_abs)
    else:
        return False
    for obj in set(bpy.data.objects) - objects_before:
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        target.objects.link(obj)
    # Importér si zakládá pomocné kolekce (glTF_not_exported); po přesunu
    # objektů zůstanou prázdné a jen by zaplevelily outliner.
    for collection in set(bpy.data.collections) - collections_before:
        if collection is not target and not collection.all_objects:
            bpy.data.collections.remove(collection)
    return True


def _local_collection(stem: str, sources: bpy.types.Collection) -> bpy.types.Collection:
    collection = bpy.data.collections.get(stem)
    if collection is None:
        collection = bpy.data.collections.new(stem)
        sources.children.link(collection)
    return collection


def _resolve_source(
    entry: dict[str, Any],
    root: str,
    sources: bpy.types.Collection,
) -> bpy.types.Collection | None:
    """Kolekce, kterou bude instance ukazovat.

    Asset bez zdrojového .blend není prázdná osa — naimportuje se přímo
    z .glb, takže je vidět a dá se z něj jedním tlačítkem vyrobit zdroj.
    """
    tier = entry.get("tier", "none")
    stem = os.path.basename(entry.get("src", "")).rsplit(".", 1)[0]
    if tier == "local":
        return _local_collection(stem, sources)
    if tier == "library":
        blend_path = os.path.join(root, entry["src_blend"])
        if not os.path.isfile(blend_path):
            return None
        return _link_library_collection(blend_path, stem)

    existing = bpy.data.collections.get(stem)
    if existing is not None:
        return existing
    preview = _local_collection(stem, sources)
    asset_abs = os.path.join(root, entry.get("src", "").replace("res://", "", 1))
    if not _import_asset(asset_abs, preview):
        bpy.data.collections.remove(preview)
        return None
    preview[P_PREVIEW] = True
    return preview


# -------------------------------------------------------------------- stavba


def _clear_previous(scene: bpy.types.Scene) -> None:
    doomed = [obj for obj in scene.objects if P_ID in obj or P_PATH in obj]
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)


def _make_proxy_mesh(name: str, bounds: dict[str, Any]) -> bpy.types.Mesh:
    position = Vector(bounds["position"])
    size = Vector(bounds["size"])
    # Godot AABB je v Godot osách, proxy stavíme rovnou v Blender osách.
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


def build(scene: bpy.types.Scene, manifest_path: str) -> dict[str, int]:
    """Postaví layout z manifestu. Existující BB objekty nahradí."""
    manifest = load_manifest(manifest_path)
    root = project_root_for(manifest_path)

    _clear_previous(scene)
    layout = _ensure_collection(scene.collection, COLL_LAYOUT)
    locked = _ensure_collection(scene.collection, COLL_LOCKED)
    sources = _ensure_collection(scene.collection, COLL_SOURCES)
    locked.hide_select = True

    counts = {"props": 0, "proxies": 0, "preview": 0}
    for entry in manifest["nodes"]:
        if entry.get("owner") == "blender":
            obj = _build_prop(entry, root, sources)
            layout.objects.link(obj)
            counts["props"] += 1
            if entry.get("tier", "none") == "none":
                counts["preview"] += 1
        else:
            obj = _build_proxy(entry)
            locked.objects.link(obj)
            counts["proxies"] += 1

    _exclude(scene, COLL_SOURCES, True)
    scene[S_MANIFEST] = manifest_path
    scene[S_ROOT] = root
    return counts


def _exclude(scene: bpy.types.Scene, name: str, value: bool) -> None:
    """Vyřadí kolekci z view layeru, aby zdroje nezaplevelily layout.

    Instance se vykreslují dál — vyřazení z view layeru je neovlivní.
    """
    for window in bpy.data.window_managers[0].windows:
        layer = window.view_layer.layer_collection.children.get(name)
        if layer is not None:
            layer.exclude = value
    layer = bpy.context.view_layer.layer_collection.children.get(name)
    if layer is not None:
        layer.exclude = value


def _build_prop(entry: dict[str, Any], root: str, sources: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(entry["name"], None)
    collection = _resolve_source(entry, root, sources)
    if collection is not None:
        obj.instance_type = "COLLECTION"
        obj.instance_collection = collection
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.5
    obj[P_ID] = entry["bb_id"]
    obj[P_PATH] = entry["path"]
    obj[P_SRC] = entry["src"]
    obj[P_TIER] = entry.get("tier", "none")
    obj[P_PARENT] = entry.get("parent", ".")
    if entry.get("src_blend"):
        obj[P_SRC_BLEND] = entry["src_blend"]
    obj.matrix_world = godot_to_blender(entry["xform"])
    return obj


def _build_proxy(entry: dict[str, Any]) -> bpy.types.Object:
    bounds = entry.get("bounds")
    if bounds is None:
        obj = bpy.data.objects.new(entry["name"], None)
        obj.empty_display_type = "CUBE"
    else:
        obj = bpy.data.objects.new(entry["name"], _make_proxy_mesh(entry["name"], bounds))
    obj.display_type = "WIRE"
    obj.hide_select = True
    obj[P_PATH] = entry["path"]
    obj.matrix_world = godot_to_blender(entry["xform"])
    return obj


# -------------------------------------------------------------------- export


def _new_id(taken: set[str]) -> str:
    import random

    while True:
        candidate = "%08x%08x" % (random.getrandbits(32), random.getrandbits(32))
        if candidate not in taken:
            return candidate


def export(scene: bpy.types.Scene) -> dict[str, int]:
    """Zapíše transformace z Blenderu zpět do manifestu.

    Godot-owned položky se přenášejí beze změny — Blender je needituje.
    Objekty bez ``bb_id`` se ignorují, takže si v layoutu můžeš dělat
    pomocnou geometrii, aniž by skončila ve hře.
    """
    manifest_path = stored_manifest_path(scene)
    manifest = load_manifest(manifest_path)
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

    for obj in sorted(_layout_objects(scene), key=lambda item: item.name):
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


def _layout_objects(scene: bpy.types.Scene) -> list[bpy.types.Object]:
    return [obj for obj in scene.objects if P_ID in obj]


def _entry_for(
    obj: bpy.types.Object,
    originals: dict[str, dict[str, Any]],
    taken: set[str],
) -> tuple[dict[str, Any] | None, bool]:
    """Položka manifestu pro objekt.

    Duplikací objektu v Blenderu se zkopírují i custom properties včetně id.
    Kolize se proto řeší až tady, při exportu — dřív se o ní nedá spolehlivě
    rozhodnout, která kopie je ta původní.
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


# ------------------------------------------------------- přesun zdroje pravdy


def override_path(root: str, asset_src: str) -> str:
    """Soubor ``<asset>.bbsrc``, kterým se přebíjí konvence hledání zdroje."""
    return os.path.join(root, asset_src.replace("res://", "", 1) + ".bbsrc")


def expected_source(asset_src: str) -> str:
    """Konvence: zdroj leží vedle assetu se stejným názvem."""
    return os.path.splitext(asset_src.replace("res://", "", 1))[0] + ".blend"


def promote_to_library(obj: bpy.types.Object, root: str) -> str:
    """Z náhledu naimportovaného z .glb udělá samostatný zdrojový .blend.

    Kolekce se zapíše do nového souboru vedle assetu, lokální kopie se zruší
    a místo ní se soubor nalinkuje — od té chvíle je zdrojem pravdy .blend.
    """
    collection = obj.instance_collection
    if collection is None:
        raise BridgeError("objekt nemá co uložit; chybí i .glb náhled")
    if collection.library is not None:
        raise BridgeError("asset už zdroj má")

    asset_src = str(obj.get(P_SRC, ""))
    target = os.path.join(root, expected_source(asset_src))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    bpy.data.libraries.write(target, {collection}, fake_user=True)

    name = collection.name
    for child in list(collection.objects):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.collections.remove(collection)

    obj.instance_collection = _link_library_collection(target, name)
    obj[P_TIER] = "library"
    obj[P_SRC_BLEND] = os.path.relpath(target, root).replace(os.sep, "/")
    return target


def promote_to_local(obj: bpy.types.Object, root: str, layout_relative: str) -> str:
    """Nechá geometrii v layoutu a zapíše ``.bbsrc``, ať to Godot ví.

    Pro unikátní geometrii levelu — edituje se přímo, bez skákání do jiného
    souboru. Daní je, že layout drží geometrii, takže v něm nikdo jiný
    současně rozmisťovat nemůže.
    """
    collection = obj.instance_collection
    if collection is None:
        raise BridgeError("objekt nemá co uložit; chybí i .glb náhled")
    if collection.library is not None:
        raise BridgeError("linkovaný asset nejde zlokalizovat; nejdřív ho odpoj")

    if not os.path.isfile(os.path.join(root, layout_relative)):
        raise BridgeError(
            "layout musí být nejdřív uložený jako %s, jinak Godot zdroj nenajde" % layout_relative
        )

    asset_src = str(obj.get(P_SRC, ""))
    marker = override_path(root, asset_src)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(layout_relative)

    collection.pop(P_PREVIEW, None)
    obj[P_TIER] = "local"
    obj[P_SRC_BLEND] = layout_relative
    return marker
