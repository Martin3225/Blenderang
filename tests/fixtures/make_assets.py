"""Vyrobí testovací assety pro Godot fixture projekt.

Spouští se z runneru (``run_tests.py --regen-fixtures``) v Blenderu:

    blender --background --factory-startup --python tests/fixtures/make_assets.py -- <výstupní adresář>

Každý asset je jednoduchý, ale pokrývá jednu cestu importu:

* ``crate.glb``  — krychle 1 m, počátek ve středu podstavy
* ``tower.glb``  — válec 2 m, dva meshe v hierarchii
* ``barrel.fbx`` — válec přes FBX (jiný importér než glTF)
* ``rig.glb``    — armatura se třemi kostmi a skinovaným meshem; glTF
  importér k ní vyrábí pomocné objekty (tvary kostí), které se nesmí
  objevit ve scéně
"""

import os
import sys

import bmesh
import bpy

OUT = os.path.abspath(sys.argv[sys.argv.index("--") + 1])


def reset() -> None:
    bpy.ops.wm.read_homefile(use_empty=True)


def mesh_object(name: str, build) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def material(name: str, color: tuple[float, float, float]) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def export_glb(name: str) -> None:
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name), export_format="GLB")


def crate() -> None:
    reset()
    obj = mesh_object("crate", lambda bm: bmesh.ops.create_cube(bm, size=1.0))
    obj.data.transform(__import__("mathutils").Matrix.Translation((0, 0, 0.5)))
    obj.data.materials.append(material("wood", (0.6, 0.4, 0.2)))
    export_glb("crate.glb")


def tower() -> None:
    reset()
    base = mesh_object("tower_base", lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, segments=12, radius1=1.0, radius2=1.0, depth=1.0))
    base.data.transform(__import__("mathutils").Matrix.Translation((0, 0, 0.5)))
    top = mesh_object("tower_top", lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, segments=12, radius1=1.0, radius2=0.0, depth=1.0))
    top.parent = base
    top.location = (0, 0, 1.5)
    base.data.materials.append(material("stone", (0.5, 0.5, 0.55)))
    export_glb("tower.glb")


def barrel() -> None:
    reset()
    obj = mesh_object("barrel", lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, segments=16, radius1=0.4, radius2=0.4, depth=1.0))
    obj.location = (0, 0, 0.5)
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, "barrel.fbx"), use_selection=False)


def rig() -> None:
    reset()
    armature = bpy.data.armatures.new("rig")
    arm_obj = bpy.data.objects.new("rig", armature)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    previous = None
    for index in range(3):
        bone = armature.edit_bones.new("bone_%d" % index)
        bone.head = (0, 0, index * 0.6)
        bone.tail = (0, 0, (index + 1) * 0.6)
        if previous is not None:
            bone.parent = previous
            bone.use_connect = True
        previous = bone
    bpy.ops.object.mode_set(mode="OBJECT")

    body = mesh_object("body", lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, segments=8, radius1=0.3, radius2=0.3, depth=1.8))
    body.location = (0, 0, 0.9)
    bpy.context.view_layer.update()
    body.data.transform(body.matrix_world)
    body.matrix_world.identity()
    for index in range(3):
        group = body.vertex_groups.new(name="bone_%d" % index)
        for vertex in body.data.vertices:
            z = vertex.co.z
            weight = 1.0 if index * 0.6 <= z <= (index + 1) * 0.6 + 1e-4 else 0.0
            if weight:
                group.add([vertex.index], weight, "REPLACE")
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm_obj
    body.parent = arm_obj
    export_glb("rig.glb")


os.makedirs(OUT, exist_ok=True)
crate()
tower()
barrel()
rig()
print("ASSETS_OK", sorted(os.listdir(OUT)))
