"""Jádro mostu mezi Godot manifestem a Blender scénou.

Manifest nese pouze identity a transformace. Geometrie se nikdy nepřenáší —
assety se do Blenderu linkují ze svých zdrojových .blend souborů, nebo se
naimportují z .glb jako náhled.

Scéna sama žádný .blend nemá. Rozmístění je vždycky v .tscn a Blender si ho
pokaždé postaví z manifestu, takže se s Godotem nemůže rozejít.
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
S_WARNINGS = "bb_warnings"

COLL_LAYOUT = "BB_Layout"
COLL_LOCKED = "BB_Locked"

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


# ------------------------------------------------------------------ kontext


def ui_context() -> dict[str, Any]:
    """Kontext 3D pohledu pro ``temp_override``.

    Godot spouští stavbu scény z časovače a handlery běží po načtení
    souboru; ani jedno nemá okno ani 3D pohled. glTF importér si ale u modelů
    s armaturou sahá na ``bpy.context.object`` a bez 3D pohledu spadne.
    Na pozadí (testy, ``--background``) se nic nepřebíjí.
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


# glTF importér si pro tvary kostí armatury zakládá pomocné objekty
# v kolekci „glTF_not_exported“. Patří jen kostem, ne do scény.
_IMPORTER_HELPERS = "glTF_not_exported"


def _import_file(path: str) -> tuple[list[bpy.types.Object], list[bpy.types.Object]]:
    """Naimportuje .glb/.gltf/.fbx a vrátí (objekty, pomocné objekty importéru).

    Všechny nové objekty odpojí ze scény — volající rozhodne, kam patří.
    Kolekce, které si importér založil, po sobě uklidí.
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
            raise BridgeError("nepodporovaný formát")
    except (RuntimeError, BridgeError) as error:
        # Po neúspěšném importu nesmí ve scéně nic zůstat napůl.
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
    """Kolekce s modelem naimportovaným z .glb pro asset bez zdrojového .blend.

    Kolekce není ve scéně — instance ji ve scéně mít nepotřebuje. Model je
    tak vidět jen jednou, na místě instance, a nikde se neválí v počátku.
    """
    stem = os.path.basename(entry.get("src", "")).rsplit(".", 1)[0]
    existing = bpy.data.collections.get(stem)
    if existing is not None and existing.get(P_PREVIEW):
        return existing
    path = asset_abs(root, entry.get("src", ""))
    if not os.path.isfile(path):
        warn("%s: asset %s neexistuje" % (entry.get("name"), entry.get("src")))
        return None
    try:
        objects, _ = _import_file(path)
    except BridgeError as error:
        warn("%s: náhled nejde načíst (%s)" % (entry.get("name"), error))
        return None
    collection = bpy.data.collections.new(stem)
    collection[P_PREVIEW] = True
    for obj in objects:
        collection.objects.link(obj)
    return collection


def source_of(entry: dict[str, Any], root: str) -> str:
    """Cesta ke zdrojovému .blend (relativní k projektu, u osobního zdroje
    absolutní), nebo prázdno.

    Stejné pravidlo jako BBPaths v Godotu: osobní výběr (jen u tebe) →
    ``<asset>.bbsrc`` (sdílený) → ``.blend`` vedle assetu. Blender ho
    vyhodnocuje sám, aby nově vybraný zdroj viděl hned.
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
    """Kolekce, kterou bude instance ukazovat (nalinkovaný zdroj, nebo náhled)
    a relativní cesta ke zdroji, pokud existuje."""
    relative = source_of(entry, root)
    if relative:
        stem = os.path.basename(entry.get("src", "")).rsplit(".", 1)[0]
        try:
            return _link_library_collection(os.path.join(root, relative), stem), relative
        except (OSError, BridgeError) as error:
            # Poškozený nebo prázdný .blend nesmí shodit otevření celé scény.
            print("Blender Bridge: zdroj %s nejde načíst (%s), použije se náhled z .glb" % (relative, error))
    return _preview_collection(entry, root), ""


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


def lock(obj: bpy.types.Object) -> None:
    """Kontext z Godotu jde vybrat a zaměřit (numpad .), ale ne posunout.
    Změny by se stejně do Godotu nepropsaly."""
    obj.lock_location = (True, True, True)
    obj.lock_rotation = (True, True, True)
    obj.lock_rotation_w = True
    obj.lock_scale = (True, True, True)


# Problémy, které nezastaví stavbu scény (vadný asset, vadný kontext), ale
# uživatel o nich má vědět. Panel je ukáže, operátor nahlásí.
WARNINGS: list[str] = []


def warn(message: str) -> None:
    WARNINGS.append(message)
    print("Blender Bridge:", message)


def build(scene: bpy.types.Scene, manifest_path: str) -> dict[str, int]:
    """Postaví scénu z manifestu. Existující BB objekty nahradí.

    Jeden vadný soubor nesmí shodit celou stavbu: model bez náhledu zůstane
    jako osa na svém místě, vadný kontext se nahradí obálkami.
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
    """Model, který je v Godotu dítětem jiného modelu (výstroj na armatuře),
    je v Blenderu jeho potomkem — posun rodiče posune i děti."""
    for obj in models.values():
        parent = models.get(str(obj.get(P_PARENT, "")))
        if parent is None:
            continue
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world


def _readable_empties(objects: list[bpy.types.Object], size: float) -> None:
    """Osy prázdných objektů velké [size] metrů ve světě, bez ohledu na
    měřítko — glTF importér je dělá stovky metrů velké."""
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
    """Zamčené okolí z Godotu do kolekce [target].

    Skutečná geometrie z ``.context.glb``; starší manifest bez něj dostane
    obálky z ``bounds``. [matrix] posune celý kontext — při úpravě modelu
    do jeho lokálního prostoru. Vrací počet nodů z Godotu.
    """
    context_path = os.path.join(root, manifest.get("context_glb", ""))
    godot_entries = [e for e in manifest["nodes"] if e.get("owner") != "blender"]
    objects: list[bpy.types.Object] | None = None
    if manifest.get("context_glb") and os.path.isfile(context_path):
        try:
            objects, _ = _import_file(context_path)
        except BridgeError as error:
            warn("kontext z Godotu nejde načíst (%s), použijí se obálky" % error)
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
    """Zapíše transformace z Blenderu zpět do manifestu.

    Godot-owned položky se přenášejí beze změny — Blender je needituje.
    Objekty bez ``bb_id`` se ignorují, takže si v layoutu můžeš dělat
    pomocnou geometrii, aniž by skončila ve hře.
    """
    manifest_path = stored_manifest_path(scene)
    manifest = load_manifest(manifest_path)
    # matrix_world se po změně location přepočítá až s depsgraphem; ze
    # skriptu nebo hned po úpravě by jinak šla ven stará pozice.
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


def scene_models(scene: bpy.types.Scene) -> list[bpy.types.Object]:
    """Modely, které jdou do Godotu, seřazené podle jména (pro panel i export)."""
    return sorted((obj for obj in scene.objects if P_ID in obj), key=lambda obj: obj.name)


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


def expected_source(asset_src: str) -> str:
    """Konvence: zdroj leží vedle assetu se stejným názvem."""
    return os.path.splitext(asset_src.replace("res://", "", 1))[0] + ".blend"


def asset_abs(root: str, asset_src: str) -> str:
    return os.path.join(root, asset_src.replace("res://", "", 1))


def ensure_exporter(collection: bpy.types.Collection, target: str) -> None:
    """Collection Exporter na glTF do cesty assetu.

    Cesta se nastavuje vždy znovu: ``bpy.data.libraries.write`` ji do nového
    souboru neuloží a prázdná cesta by exportovala jinam (podle jména kolekce).
    """
    exporter = next((e for e in collection.exporters if e.name.lower().startswith("gltf")), None)
    if exporter is None and len(collection.exporters):
        exporter = collection.exporters[0]
    if exporter is None:
        with bpy.context.temp_override(collection=collection):
            bpy.ops.collection.exporter_add(name="IO_FH_gltf2")
        exporter = collection.exporters[-1]
    exporter.filepath = target
    exporter.export_properties.filepath = target


def export_collection(collection: bpy.types.Collection) -> None:
    """Vyexportuje kolekci jejím exporterem. ``wm.collection_export_all``
    nestačí — exportuje jen kolekce, které jsou ve view layeru."""
    with bpy.context.temp_override(collection=collection):
        bpy.ops.collection.export_all()


def promote_to_library(obj: bpy.types.Object, root: str) -> str:
    """Z náhledu naimportovaného z .glb udělá samostatný zdrojový .blend.

    Kolekce se zapíše do nového souboru vedle assetu i s nastaveným
    exportem, lokální kopie se zruší a místo ní se soubor nalinkuje — od té
    chvíle je zdrojem pravdy .blend.
    """
    collection = obj.instance_collection
    if collection is None:
        raise BridgeError("objekt nemá co uložit; chybí i .glb náhled")
    if collection.library is not None:
        raise BridgeError("asset už zdroj má")

    asset_src = str(obj.get(P_SRC, ""))
    target = os.path.join(root, expected_source(asset_src))
    if os.path.exists(target):
        raise BridgeError("%s už existuje; vyber ho v Godotu jako zdroj" % target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    collection.pop(P_PREVIEW, None)
    ensure_exporter(collection, asset_abs(root, asset_src))
    bpy.data.libraries.write(target, {collection}, fake_user=True)

    # Stejný asset může mít ve scéně víc instancí; všechny se přepojí.
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


# ------------------------------------------------------------ úprava zdroje
#
# „Upravit zdroj“ otevře .blend jednoho assetu. Aby nechybělo okolí, postaví
# se do něj z manifestu dočasná kolekce BB_Context s obálkami všeho ostatního
# ze scény, posunutá tak, jako by asset stál na svém místě. Kontext se před
# každým uložením odebere a po uložení vrátí — do zdrojového souboru se nikdy
# nezapíše.

COLL_CONTEXT = "BB_Context"
EDIT_MARKER = "bb_edit.json"


def _marker_path(root: str) -> str:
    return os.path.join(root, ".pipeline", EDIT_MARKER)


def _pointer_path() -> str:
    """Odkaz na rozpracovanou úpravu v uživatelské konfiguraci Blenderu.

    Zdroj modelu může ležet mimo projekt (osobní zdroj), takže se značka
    nedá najít procházením adresářů od otevřeného souboru.
    """
    return os.path.join(bpy.utils.user_resource("CONFIG", create=True), "blender_bridge_edit.json")


def begin_edit(scene: bpy.types.Scene, obj: bpy.types.Object) -> str:
    """Odešle rozpracované přesuny do Godotu a připraví úpravu zdroje.

    Vrátí cestu ke zdrojovému .blend, který se má otevřít.
    """
    root = scene.get(S_ROOT, "")
    relative = obj.get(P_SRC_BLEND, "")
    if not root or not relative:
        raise BridgeError("asset nemá zdrojový .blend")
    source = os.path.join(root, relative)   # osobní zdroj je absolutní
    if not os.path.isfile(source):
        raise BridgeError("zdroj neexistuje: %s" % source)
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
    """Údaje o rozpracované úpravě, pokud je otevřený právě její zdroj."""
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
    """Ukončí úpravu; vrátí manifest, ze kterého se má scéna znovu postavit."""
    for path in (_marker_path(session["root"]), _pointer_path()):
        if os.path.isfile(path):
            os.remove(path)
    return session["manifest"]


def build_context(session: dict[str, Any]) -> int:
    """Postaví zamčené okolí kolem upravovaného modelu.

    Godot část je skutečná geometrie z ``.context.glb``, ostatní modely
    jsou instance jejich náhledů. Další výskyty téhož assetu ukazují přímo
    na upravovanou kolekci, takže úpravy jsou vidět na všech místech naráz.
    Všechno je posunuté do prostoru modelu, jako by stál na svém místě.
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
    """Odebere kontext včetně všeho, co kvůli němu vzniklo (náhledy, meshe,
    materiály). Volá se před každým uložením — do zdroje se nic nedostane."""
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
    # Data bez uživatelů by se stejně neuložila; purge je jen uklidí z paměti,
    # aby se při dalším uložení nehromadila. Fake user se nemaže.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)


def session_collection(session: dict[str, Any]) -> bpy.types.Collection | None:
    return bpy.data.collections.get(session.get("collection", ""))


def collection_has_exporter(session: dict[str, Any]) -> bool:
    collection = session_collection(session)
    return collection is not None and any(e.filepath for e in collection.exporters)


def setup_session_exporter(session: dict[str, Any]) -> str:
    collection = bpy.data.collections.get(session.get("collection", ""))
    if collection is None:
        raise BridgeError("v souboru chybí kolekce %s" % session.get("collection"))
    target = asset_abs(session["root"], session["asset"])
    ensure_exporter(collection, target)
    return target


# ------------------------------------------------------------------ detail


def _source_label(obj: bpy.types.Object, tier: str, source: str) -> str:
    if tier != "library":
        return "není — vyrobí se %s" % expected_source(str(obj.get(P_SRC, "")))
    if os.path.isabs(source):
        return "%s (jen u tebe, mimo projekt)" % source
    return source


def describe(obj: bpy.types.Object) -> tuple[str, list[tuple[str, str]]]:
    """Co panel Detail ukáže o objektu: druh a řádky (popisek, hodnota).

    Druhy: ``model`` (posílá se do Godotu), ``godot`` (kontext z Godotu,
    jen pro orientaci), ``helper`` (pomocný objekt, do Godotu se neposílá).
    """
    if P_ID in obj:
        tier = obj.get(P_TIER, "none")
        source = obj.get(P_SRC_BLEND, "")
        rows = [
            ("Node v Godotu", str(obj.get(P_PATH, ""))),
            ("Rodič", str(obj.get(P_PARENT, "."))),
            ("Asset", str(obj.get(P_SRC, "")).replace("res://", "", 1)),
            ("Zdroj", _source_label(obj, tier, source)),
            ("Id", str(obj.get(P_ID, ""))),
        ]
        return "model", rows
    unit = obj
    while unit.parent is not None and unit.parent.parent is not None:
        unit = unit.parent
    if obj.get(P_PATH) == "context" or unit.get(P_PATH) == "context":
        return "godot", [("Node v Godotu", unit.name)]
    return "helper", []



# --------------------------------------------------------- výběr zdroje


def override_path(root: str, asset_src: str) -> str:
    """``<asset>.bbsrc`` — přesná cesta ke zdroji, sdílená s Godotem."""
    return asset_abs(root, asset_src) + ".bbsrc"


# Osobní výběr zdrojů mimo projekt. Stejný soubor čte Godot (BBPaths).
# Adresář má .gitignore s „*“, takže se nikdy necommitne.
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
    """Jak je zdroj zvolený: ``personal`` (jen u tebe), ``shared`` (.bbsrc),
    nebo prázdno (konvence: .blend vedle assetu)."""
    if asset_src in local_sources(root):
        return "personal"
    if os.path.isfile(override_path(root, asset_src)):
        return "shared"
    return ""


def _models_of(scene: bpy.types.Scene, asset_src: str) -> list[bpy.types.Object]:
    return [o for o in scene_models(scene) if o.get(P_SRC) == asset_src]


def choose_source(scene: bpy.types.Scene, asset_src: str, blend_path: str) -> tuple[str, bool]:
    """Nastaví existující .blend jako zdroj assetu a přepojí všechny jeho
    instance. Vrací (cesta, osobní).

    V projektu se uloží do sdíleného ``.bbsrc`` (relativně ke kořeni).
    Mimo projekt se uloží jen u tebe — ostatní v týmu ho neuvidí.
    """
    root = scene.get(S_ROOT, "")
    if not root:
        raise BridgeError("scéna nemá načtený manifest")
    absolute = os.path.abspath(blend_path)
    if not os.path.isfile(absolute) or not absolute.lower().endswith(".blend"):
        raise BridgeError("vyber existující .blend soubor")
    try:
        relative = os.path.relpath(absolute, root)
    except ValueError:   # Windows: jiný disk než projekt
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
    """Zruší ručně vybraný zdroj — nejdřív osobní, pak sdílený. Platí zase
    to, co zbylo: sdílený .bbsrc, .blend vedle assetu, jinak náhled z .glb."""
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
