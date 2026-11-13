"""Fit a closed gable prism to shell measurements."""

import math
from itertools import combinations

from ..frame import cross, dot, unit
from ..geometry.assemble_mesh_result import result
from ..geometry.solve_linear_system import solve
from interior_fit.rooms.ray_queries import RayHitField, query


def group_planes(samples):
    groups = []
    for p, n in samples:
        d = dot(p, n)
        match = next(
            (g for g in groups if dot(g[0], n) > 0.999 and abs(g[1] - d) < 3),
            None,
        )
        if match:
            match[2] += 1
        else:
            groups.append([n, d, 1])
    return groups


def fit(frame, samples, test, groups=None):
    groups = group_planes(samples) if groups is None else groups
    planes = [(n, d) for n, d, k in groups if k >= 3]
    if len(planes) != 4 or sum(n[2] < -0.15 for n, d in planes) != 2:
        return None
    if sum(
        any(abs(dot(p, m) - d) < 4 and dot(n, m) > 0.99 for m, d in planes)
        for p, n in test
    ) < 0.85 * len(test):
        return None
    planes.append(((0, 0, 1), 0))
    vertices = []
    for group in combinations(planes, 3):
        normals, offsets = zip(*group)
        p = solve(normals, offsets)
        if p and all(dot(p, n) >= d - 0.1 for n, d in planes):
            vertices.append(tuple(p))
    if len(vertices) != 6:
        return None
    faces = []
    for n, d in planes:
        ids = [i for i, p in enumerate(vertices) if abs(dot(p, n) - d) < 0.2]
        if len(ids) < 3:
            return None
        center = [
            sum(vertices[i][k] for i in ids) / len(ids) for k in range(3)
        ]
        x = unit(tuple(a - b for a, b in zip(vertices[ids[0]], center)))
        y = cross(x, n)
        faces.append(
            sorted(
                ids,
                key=lambda i: math.atan2(
                    dot(vertices[i], y) - dot(center, y),
                    dot(vertices[i], x) - dot(center, x),
                ),
            )
        )
    outline = [vertices[i] for i in reversed(faces[-1])]
    fitted = result(frame, "ridge_prism", outline, vertices, faces)
    fitted["inward_planes"] = planes
    return fitted


def confirm_sparse_gable(frame, samples, test, groups):
    """
    Corroborate a lightly observed end wall without accepting a single
    doorway return.
    """
    roofs = [(n, d) for n, d, k in groups if n[2] < -0.15 and k >= 3]
    ends = [(n, d, k) for n, d, k in groups if abs(n[2]) < 0.04]
    if len(roofs) != 2 or len(ends) != 2:
        return None
    weak, strong = sorted(ends, key=lambda plane: plane[2])
    n, offset, count = weak
    if count >= 3 or strong[2] < 3 or dot(n, strong[0]) > -0.999:
        return None
    if any(abs(dot(n, m)) > 0.04 for m, _ in roofs):
        return None
    # Build only a hypothesis. Probe both lower shoulders and the upper gable
    # from its interior, so a door at the center can stay open.
    proposal = [
        (n, offset, 3) if (m, d) == (n, offset) else (m, d, k)
        for m, d, k in groups
    ]
    candidate = fit(frame, samples, test, proposal)
    vertices = (
        [p for p in candidate["vertices"] if abs(dot(n, p) - offset) < 0.2]
        if candidate
        else []
    )
    if len(vertices) != 3:
        return None
    center = tuple(sum(p[i] for p in vertices) / 3 for i in range(3))
    sites = [tuple((a + b) / 2 for a, b in zip(p, center)) for p in vertices]

    def endpoint(p, step):
        return frame.world(tuple(a + step * b for a, b in zip(p, n)))

    hits = yield from query(
        [(endpoint(p, 16), endpoint(p, -16)) for p in sites]
    )
    if all(
        h
        and dot(frame.direction(h[RayHitField.NORMAL]), n) > 0.995
        and abs(dot(frame.local(h[RayHitField.POINT]), n) - offset) < 3
        for h in hits
    ):
        return candidate
