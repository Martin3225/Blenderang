@tool
extends EditorPlugin

## Controls for the Godot ↔ Blender bridge.
##
## The main path is one click on each side: [i]Open in Blender[/i]
## here (button in the 3D editor toolbar, right-click on a scene tab or on
## a [code].tscn[/code] in the FileSystem), [i]Send to Godot[/i] in Blender.
## Changes from Blender are loaded into the open scene automatically.

const MENU_NAME: String = "Blenderang"
const PERSONAL_SOURCE_NOTICE: String = """%s is outside the Godot project.

The path is not saved in the project, it only applies to you. Others on the team won't see this source and can't edit the model; they will still see only the .glb.

To give everyone the source, put the .blend inside the project and pick it again."""
const WATCH_INTERVAL: float = 1.0

enum Action {
	OPEN_IN_BLENDER,
	MARK_SELECTION,
	UNMARK_SELECTION,
	MARK_PROPS,
	PICK_SOURCE,
	EXPORT_MANIFEST,
	IMPORT_MANIFEST,
}

var _menu: PopupMenu
var _toolbar_button: Button
var _context_menus: Array[EditorContextMenuPlugin] = []
var _watch: Timer
## The last manifest content the plugin knows about (it wrote it itself, or
## has already imported it). Different content on disk means a change from Blender.
var _known_md5: Dictionary = {}
## Node marks of open scenes from just before a reimport, keyed by scene path.
var _marks_before_reimport: Dictionary = {}


func _enter_tree() -> void:
	_menu = PopupMenu.new()
	_menu.add_item("Open scene in Blender", Action.OPEN_IN_BLENDER)
	_menu.add_separator("Advanced")
	_menu.add_item("Mark selection as Blender-owned", Action.MARK_SELECTION)
	_menu.add_item("Unmark selection", Action.UNMARK_SELECTION)
	_menu.add_item("Mark all art instances in scene", Action.MARK_PROPS)
	_menu.add_item("Pick source .blend for selection…", Action.PICK_SOURCE)
	_menu.add_separator()
	_menu.add_item("Export manifest only", Action.EXPORT_MANIFEST)
	_menu.add_item("Load changes from Blender manually", Action.IMPORT_MANIFEST)
	_menu.id_pressed.connect(_on_action)
	add_tool_submenu_item(MENU_NAME, _menu)

	_toolbar_button = Button.new()
	_toolbar_button.text = "Blender"
	_toolbar_button.icon = BBIcons.blender()
	_toolbar_button.flat = true
	_toolbar_button.tooltip_text = "Open scene in Blender"
	_toolbar_button.pressed.connect(_on_toolbar_pressed)
	add_control_to_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_button)

	for slot: int in [
		EditorContextMenuPlugin.CONTEXT_SLOT_SCENE_TABS,
		EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM,
	]:
		var menu: EditorContextMenuPlugin = preload("bb_context_menu.gd").new(open_scene_in_blender)
		add_context_menu_plugin(slot, menu)
		_context_menus.append(menu)

	_watch = Timer.new()
	_watch.wait_time = WATCH_INTERVAL
	_watch.timeout.connect(_poll_manifest)
	add_child(_watch)
	_watch.start()

	BBTerrain.register_settings()

	var filesystem: EditorFileSystem = EditorInterface.get_resource_filesystem()
	filesystem.resources_reimporting.connect(_on_reimporting)
	filesystem.resources_reimported.connect(_on_reimported)


func _exit_tree() -> void:
	remove_tool_menu_item(MENU_NAME)
	_menu = null
	remove_control_from_container(CONTAINER_SPATIAL_EDITOR_MENU, _toolbar_button)
	_toolbar_button.queue_free()
	_toolbar_button = null
	for menu: EditorContextMenuPlugin in _context_menus:
		remove_context_menu_plugin(menu)
	_context_menus.clear()
	var filesystem: EditorFileSystem = EditorInterface.get_resource_filesystem()
	filesystem.resources_reimporting.disconnect(_on_reimporting)
	filesystem.resources_reimported.disconnect(_on_reimported)
	_watch.queue_free()
	_watch = null


func _on_toolbar_pressed() -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null:
		push_warning("Blenderang: no scene is open.")
		return
	_open_in_blender(root)


## Entry point from the context menus. A scene that isn't active in the
## editor is opened first, since the manifest and bb_id marks come from the open tree.
func open_scene_in_blender(path: String) -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path != path:
		EditorInterface.open_scene_from_path(path)
		root = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path != path:
		push_error("Blenderang: could not open scene %s." % path)
		return
	_open_in_blender(root)


func _on_action(id: int) -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null:
		push_warning("Blenderang: no scene is open.")
		return
	match id:
		Action.OPEN_IN_BLENDER:
			_open_in_blender(root)
		Action.MARK_SELECTION:
			_mark(EditorInterface.get_selection().get_selected_nodes(), root)
		Action.UNMARK_SELECTION:
			_unmark(EditorInterface.get_selection().get_selected_nodes())
		Action.MARK_PROPS:
			_mark(_find_props(root), root)
		Action.PICK_SOURCE:
			_pick_source()
		Action.EXPORT_MANIFEST:
			_export(root)
		Action.IMPORT_MANIFEST:
			_import(root, false)


## The whole Godot → Blender path in one click. On first use in a scene it
## marks the art instances by itself, so nothing needs preparing.
func _open_in_blender(root: Node) -> void:
	var duplicates: Array[Node] = []
	if BBOwnership.collect_ids(root, duplicates).is_empty():
		_mark(_find_props(root), root)
	if root.scene_file_path.is_empty():
		push_warning("Blenderang: save the scene first, the manifest is named after it.")
		return
	# The bb_id marks must be on disk, otherwise the import wouldn't find them.
	if EditorInterface.save_scene() != OK:
		push_error("Blenderang: could not save the scene.")
		return
	var path: String = _export(root)
	if path.is_empty():
		return
	if BBLauncher.launch(ProjectSettings.globalize_path(path)) == OK:
		print("Blenderang: launching Blender with scene %s." % root.scene_file_path.get_file())


## Sets the exact path to the source .blend of the selected asset. It's
## written to a file next to the asset, so it applies to all its instances
## and to the whole team.
func _pick_source() -> void:
	var selected: Array[Node] = EditorInterface.get_selection().get_selected_nodes()
	if selected.size() != 1 or selected[0].scene_file_path.is_empty():
		push_warning("Blenderang: select exactly one instanced node.")
		return
	var asset: String = selected[0].scene_file_path
	var dialog: EditorFileDialog = EditorFileDialog.new()
	dialog.file_mode = EditorFileDialog.FILE_MODE_OPEN_FILE
	# Whole disk: the source doesn't have to be in the project, not everyone on the team has the sources.
	dialog.access = EditorFileDialog.ACCESS_FILESYSTEM
	dialog.add_filter("*.blend", "Blender files")
	dialog.title = "Source .blend for %s" % asset.get_file()
	dialog.current_path = ProjectSettings.globalize_path("res://" + BBPaths.expected_source_for(asset))
	dialog.file_selected.connect(func(path: String) -> void:
		dialog.queue_free()
		var personal: bool = BBPaths.choose_source(asset, path)
		EditorInterface.get_resource_filesystem().scan()
		print("Blenderang: %s → %s%s" % [asset.get_file(), path, " (only for you)" if personal else ""])
		if personal:
			_warn_personal_source(path)
	)
	dialog.canceled.connect(dialog.queue_free)
	EditorInterface.get_base_control().add_child(dialog)
	dialog.popup_centered_ratio(0.6)


func _warn_personal_source(path: String) -> void:
	var notice: AcceptDialog = AcceptDialog.new()
	notice.title = "Source outside the project"
	notice.dialog_text = PERSONAL_SOURCE_NOTICE % path
	notice.confirmed.connect(notice.queue_free)
	notice.canceled.connect(notice.queue_free)
	EditorInterface.get_base_control().add_child(notice)
	notice.popup_centered()


func _mark(nodes: Array[Node], root: Node) -> void:
	var duplicates: Array[Node] = []
	var taken: Dictionary = BBOwnership.collect_ids(root, duplicates)
	var undo: EditorUndoRedoManager = get_undo_redo()
	undo.create_action("Blenderang: mark nodes")
	var marked: int = 0
	for node: Node in nodes + duplicates:
		if not node is Node3D:
			continue
		if BBOwnership.is_blender_owned(node) and not duplicates.has(node):
			continue
		var id: String = BBOwnership.generate_id()
		while taken.has(id):
			id = BBOwnership.generate_id()
		taken[id] = node
		marked += 1
		undo.add_do_method(node, &"set_meta", BBOwnership.META_ID, id)
		undo.add_undo_method(node, &"remove_meta", BBOwnership.META_ID)
	undo.commit_action()
	print("Blenderang: marked %d nodes." % marked)


func _unmark(nodes: Array[Node]) -> void:
	var undo: EditorUndoRedoManager = get_undo_redo()
	undo.create_action("Blenderang: unmark nodes")
	for node: Node in nodes:
		if not BBOwnership.is_blender_owned(node):
			continue
		var id: String = BBOwnership.get_id(node)
		undo.add_do_method(node, &"remove_meta", BBOwnership.META_ID)
		undo.add_undo_method(node, &"set_meta", BBOwnership.META_ID, id)
	undo.commit_action()


func _find_props(root: Node) -> Array[Node]:
	var found: Array[Node] = []
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		for child: Node in node.get_children():
			stack.push_back(child)
		if node != root and BBOwnership.is_auto_markable(node, root):
			found.append(node)
	return found


func _export(root: Node) -> String:
	var path: String = BBManifest.write(root)
	if path.is_empty():
		return ""
	_known_md5[path] = FileAccess.get_md5(path)
	print("Blenderang: manifest written to %s" % path)
	return path


## Saving a source in Blender regenerates the .glb and Godot reimports it.
## In open scenes Godot replaces its instances with new nodes without metadata,
## so the model would stop being editable in Blender and the parent node
## (NavigationRegion3D) would swallow the terrain too. The marks are
## therefore remembered before the reimport and restored after it.
func _on_reimporting(_resources: PackedStringArray) -> void:
	_marks_before_reimport.clear()
	for root: Node in EditorInterface.get_open_scene_roots():
		if not root.scene_file_path.is_empty():
			_marks_before_reimport[root.scene_file_path] = BBOwnership.snapshot_marks(root)


func _on_reimported(_resources: PackedStringArray) -> void:
	# The editor rebuilds the scenes only after this signal.
	_restore_marks.call_deferred()


func _restore_marks() -> void:
	for root: Node in EditorInterface.get_open_scene_roots():
		var marks: Dictionary = _marks_before_reimport.get(root.scene_file_path, {})
		var restored: int = BBOwnership.restore_marks(root, marks)
		if restored > 0:
			print("Blenderang: restored marks on %d nodes in scene %s after reimport." % [restored, root.scene_file_path.get_file()])
	_marks_before_reimport.clear()


## Changes from Blender load automatically: after "Send to Godot" Blender
## rewrites the manifest, which is detected here by a change in content.
## Only the manifest of the currently open scene is checked.
func _poll_manifest() -> void:
	var root: Node = EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path.is_empty():
		return
	var path: String = BBManifest.manifest_path(root)
	if not FileAccess.file_exists(path):
		return
	var md5: String = FileAccess.get_md5(path)
	if not _known_md5.has(path):
		# A manifest from earlier that this editor session doesn't know about.
		# Don't load it blindly, just remember it.
		_known_md5[path] = md5
		return
	if _known_md5[path] == md5:
		return
	_known_md5[path] = md5
	_import(root, true)


func _import(root: Node, automatic: bool) -> void:
	var path: String = BBManifest.manifest_path(root)
	var manifest: Dictionary = BBApply.read_json(path)
	if manifest.is_empty():
		push_warning("Blenderang: manifest is missing, open the scene in Blender first.")
		return
	var baseline: Dictionary = BBApply.read_json(BBManifest.baseline_path(root))
	var plan: BBApply.Plan = BBApply.plan(root, manifest, baseline)
	if plan.is_empty():
		if not automatic:
			print("Blenderang: no changes.")
		return
	BBApply.commit(root, BBApply.operations(root, plan), get_undo_redo())
	BBManifest.store(BBManifest.baseline_path(root), JSON.stringify(manifest, "\t"))
	_known_md5[path] = FileAccess.get_md5(path)
	print("Blenderang: from Blender %s (Ctrl+Z to undo)" % plan.summary())
	for problem: String in plan.unresolved:
		push_warning("Blenderang: %s" % problem)
	for name: String in plan.pinned:
		push_warning("Blenderang: %s is pinned in Godot, change from Blender ignored." % name)
