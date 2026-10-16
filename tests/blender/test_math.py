"""Převody souřadnic Godot ↔ Blender."""

import math
import random
import unittest

from mathutils import Euler, Matrix, Vector

import blender_bridge.bridge as bridge


def godot_xform(basis_columns, origin):
    x, y, z = basis_columns
    return [*x, *y, *z, *origin]


class ConversionTest(unittest.TestCase):
    def test_godot_up_is_blender_up(self):
        matrix = bridge.godot_to_blender(godot_xform(((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 5, 0)))
        self.assertEqual(tuple(round(v, 6) for v in matrix.translation), (0, 0, 5))

    def test_godot_forward_is_blender_forward(self):
        # Godot −Z je dopředu, Blender +Y je dopředu.
        matrix = bridge.godot_to_blender(godot_xform(((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, -3)))
        self.assertEqual(tuple(round(v, 6) for v in matrix.translation), (0, 3, 0))

    def test_rotation_about_up_axis_keeps_sign(self):
        angle = math.radians(30)
        # Godot Basis(UP, 30°): sloupce x, y, z.
        basis = ((math.cos(angle), 0, -math.sin(angle)), (0, 1, 0), (math.sin(angle), 0, math.cos(angle)))
        matrix = bridge.godot_to_blender(godot_xform(basis, (0, 0, 0)))
        self.assertAlmostEqual(matrix.to_euler().z, angle, places=5)

    def test_roundtrip_with_rotation_and_nonuniform_scale(self):
        rng = random.Random(7)
        for _ in range(50):
            rotation = Euler([rng.uniform(-math.pi, math.pi) for _ in range(3)]).to_matrix()
            scale = Matrix.Diagonal(Vector([rng.uniform(0.2, 4.0) for _ in range(3)]))
            basis = rotation @ scale
            columns = [tuple(basis.col[i]) for i in range(3)]
            original = godot_xform(columns, [rng.uniform(-500, 500) for _ in range(3)])
            back = bridge.blender_to_godot(bridge.godot_to_blender(original))
            for a, b in zip(back, original):
                self.assertAlmostEqual(a, b, places=4)

    def test_rejects_malformed_transform(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.godot_to_blender([0.0] * 11)
