"""Check closure, consistent winding and convexity."""

import math

from ..frame import cross, dot


# Scaling the plane tolerance by the normal length keeps it in centimeters.
MIN_DOUBLE_FACE_AREA_CM2 = 1.0e-6
CONVEX_PLANE_TOLERANCE_CM = 0.001


def is_convex(cap):
    """
    Verify a closed, consistently wound shell and every local convex
    dihedral.
    """
    vertices = cap["vertices"]
    opposites = {}
    for a, b, c in cap["triangles"]:
        for i, j, k in ((a, b, c), (b, c, a), (c, a, b)):
            if (i, j) in opposites:
                return False
            opposites[i, j] = k
    for (i, j), k in opposites.items():
        other = opposites.get((j, i))
        if other is None:
            return False
        a = vertices[i]
        directions = [
            tuple(x - y for x, y in zip(vertices[t], a)) for t in (j, k, other)
        ]
        inward = cross(directions[0], directions[1])
        length = math.sqrt(dot(inward, inward))
        if (
            length < MIN_DOUBLE_FACE_AREA_CM2
            or dot(inward, directions[2]) < -CONVEX_PLANE_TOLERANCE_CM * length
        ):
            return False
    return True
