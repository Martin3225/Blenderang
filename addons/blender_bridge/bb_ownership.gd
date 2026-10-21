@tool
class_name BBOwnership
extends RefCounted

## Určuje, kdo vlastní pozici nodu. Blender smí zapisovat pouze do nodů
## označených metadatem [code]bb_id[/code]; všechno ostatní je pro něj
## zamčená reference.

const META_ID: StringName = &"bb_id"
const META_PINNED: StringName = &"bb_pinned"
const META_ROOT: StringName = &"bb_root"
## Všechna metadata mostu na nodu.
const MARKS: Array[StringName] = [META_ID, META_PINNED, META_ROOT]

## Přípony zdrojů, které jsou typicky autorované v Blenderu. Slouží jen
## jako nápověda pro hromadné označování, ne jako kritérium vlastnictví.
const ART_EXTENSIONS: PackedStringArray = ["glb", "gltf", "fbx", "blend", "obj"]


static func is_blender_owned(node: Node) -> bool:
	return node.has_meta(META_ID)


static func is_pinned(node: Node) -> bool:
	return node.get_meta(META_PINNED, false)


static func is_layout_root(node: Node) -> bool:
	return node.get_meta(META_ROOT, false)


static func get_id(node: Node) -> String:
	return str(node.get_meta(META_ID, ""))


static func generate_id() -> String:
	return "%08x%08x" % [randi(), randi()]


## Přidělí nodu nové id. Vrací [code]false[/code], pokud už nějaké má.
static func assign_id(node: Node, taken: Dictionary) -> bool:
	if is_blender_owned(node) and not taken.has(get_id(node)):
		return false
	var id: String = generate_id()
	while taken.has(id):
		id = generate_id()
	node.set_meta(META_ID, id)
	return true


## Nod je kandidátem na správu z Blenderu, pokud je to Node3D instancovaný
## z externí scény, jejíž zdroj je umělecký asset.
static func looks_like_prop(node: Node) -> bool:
	if not node is Node3D:
		return false
	var src: String = node.scene_file_path
	if src.is_empty():
		return false
	return ART_EXTENSIONS.has(src.get_extension().to_lower())


## Hromadné označování vynechává vnitřnosti cizích instancí a cokoli
## zavěšeného pod fyzikálním tělesem — to jsou gameplay celky, jejichž
## skladbu Blender měnit nesmí.
static func is_auto_markable(node: Node, root: Node) -> bool:
	if not looks_like_prop(node):
		return false
	if node.owner != root:
		return false
	var parent: Node = node.get_parent()
	while parent != null and parent != root:
		if parent is CollisionObject3D:
			return false
		parent = parent.get_parent()
	return true


## Projde strom a vrátí všechna již přidělená id. Duplicitní id (vzniklá
## kopírováním nodu v editoru) hlásí v [code]duplicates[/code].
static func collect_ids(root: Node, duplicates: Array[Node]) -> Dictionary:
	var taken: Dictionary = {}
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if is_blender_owned(node):
			var id: String = get_id(node)
			if id.is_empty() or taken.has(id):
				duplicates.append(node)
			else:
				taken[id] = node
		for child: Node in node.get_children():
			stack.push_back(child)
	return taken


## Značky všech nodů scény podle cesty od kořene. Godot při reimportu assetu
## nahradí jeho instance v otevřené scéně novými nody a metadata instance
## přitom zahodí — tímhle se dají vrátit, viz [method restore_marks].
static func snapshot_marks(root: Node) -> Dictionary:
	var marks: Dictionary = {}
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		var meta: Dictionary = {}
		for key: StringName in MARKS:
			if node.has_meta(key):
				meta[key] = node.get_meta(key)
		if not meta.is_empty():
			marks[root.get_path_to(node)] = {"src": node.scene_file_path, "meta": meta}
		for child: Node in node.get_children():
			stack.push_back(child)
	return marks


## Vrátí značky nodům, které o ně přišly. Node se musí shodovat cestou
## i assetem; kdo nějakou značku má, je nedotčený. Vrací počet opravených nodů.
static func restore_marks(root: Node, marks: Dictionary) -> int:
	var restored: int = 0
	for path: NodePath in marks:
		var node: Node = root.get_node_or_null(path)
		var record: Dictionary = marks[path]
		if node == null or node.scene_file_path != record["src"]:
			continue
		if MARKS.any(func(key: StringName) -> bool: return node.has_meta(key)):
			continue
		for key: StringName in record["meta"]:
			node.set_meta(key, record["meta"][key])
		restored += 1
	return restored
