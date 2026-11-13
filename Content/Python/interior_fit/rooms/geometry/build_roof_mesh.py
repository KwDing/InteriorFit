"""
Build closed polyhedra in the measured floor frame (UE clockwise face
winding).
"""

import math


from interior_fit.rooms.geometry.assemble_mesh_result import result


def inside_ellipsoid(cap, x, y, z):
    """
    Occupancy in the measured curved shell, before approximation by flat
    faces.
    """
    if z < 0:
        return False
    dx, dy, dz = (v - c for v, c in zip((x, y, z), cap["center"]))
    c, s = math.cos(cap["yaw_radians"]), math.sin(cap["yaw_radians"])
    local = (c * dx + s * dy, -s * dx + c * dy, dz)
    return sum((v / r) ** 2 for v, r in zip(local, cap["radii"])) <= 1


def dense_ellipsoid(frame, center, radii, theta):
    cx, cy, cz = center
    a, b, h = radii
    low = math.asin(-cz / h)
    count = 40
    levels = max(8, math.ceil((math.pi / 2 - low) / 0.15))
    vertices, faces, rings = [], [], []
    for j in range(levels):
        phi = low + (math.pi / 2 - low) * j / levels
        # Halving azimuth resolution above the narrow cap avoids tiny polar
        # faces.
        size = count // 2 if math.cos(phi) <= 0.42 and phi > 0 else count
        rings.append(list(range(len(vertices), len(vertices) + size)))
        for i in range(size):
            angle = math.tau * i / size
            x, y = (
                a * math.cos(angle) * math.cos(phi),
                b * math.sin(angle) * math.cos(phi),
            )
            vertices.append(
                (
                    cx + x * math.cos(theta) - y * math.sin(theta),
                    cy + x * math.sin(theta) + y * math.cos(theta),
                    cz + h * math.sin(phi),
                )
            )
    outline = vertices[: len(rings[0])]
    faces.append(rings[0][::-1])
    for lower, upper in zip(rings, rings[1:]):
        for i, v in enumerate(upper):
            next_top = upper[(i + 1) % len(upper)]
            step = len(lower) // len(upper)
            left, right = lower[i * step], lower[((i + 1) * step) % len(lower)]
            if step == 2:
                mid = lower[i * step + 1]
                faces.extend(
                    [
                        (left, mid, v),
                        (mid, next_top, v),
                        (mid, right, next_top),
                    ]
                )
            else:
                faces.append((left, right, next_top, v))
    apex = len(vertices)
    vertices.append((cx, cy, cz + h))
    for i, v in enumerate(rings[-1]):
        faces.append((v, rings[-1][(i + 1) % len(rings[-1])], apex))
    fitted = result(frame, "ellipsoid_cap", outline, vertices, faces)
    fitted.update(center=center, radii=radii, yaw_radians=theta)
    return fitted
