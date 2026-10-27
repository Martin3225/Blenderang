extends RefCounted

## Scene fingerprint: for each node its path, class, instance source and world
## transform. Used to verify the import changed only what it should.


static func snapshot(root: Node) -> Dictionary:
	var result: Dictionary = {}
	for node: Node in root.find_children("*", "", true, true):
		var item: Dictionary = {"class": node.get_class(), "src": node.scene_file_path}
		var spatial: Node3D = node as Node3D
		if spatial != null:
			var x: Transform3D = BBManifest.global_xform(spatial, root)
			item["xform"] = [x.basis.x.x, x.basis.x.y, x.basis.x.z, x.basis.y.x, x.basis.y.y, x.basis.y.z,
				x.basis.z.x, x.basis.z.y, x.basis.z.z, x.origin.x, x.origin.y, x.origin.z]
		result[str(root.get_path_to(node))] = item
	return result


static func same(a: Dictionary, b: Dictionary) -> bool:
	if a.get("class") != b.get("class") or a.get("src") != b.get("src"):
		return false
	var xa: Array = a.get("xform", [])
	var xb: Array = b.get("xform", [])
	if xa.size() != xb.size():
		return false
	for index: int in xa.size():
		if absf(float(xa[index]) - float(xb[index])) > 0.0005:
			return false
	return true
