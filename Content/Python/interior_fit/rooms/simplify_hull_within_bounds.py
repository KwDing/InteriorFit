"""
Optional authoring profile: spend material thickness on a simpler
acoustic hull.
"""

import math

from interior_fit.rooms.geometry.compute_ellipsoid_cap_hull import staggered
from interior_fit.rooms.geometry.check_closed_convex_hull import is_convex
from interior_fit.rooms.frame import cross, dot, unit
from interior_fit.rooms.ray_queries import RayHitField, query

TAG = "InteriorFitThickShell"


# Probe extents are signed offsets along the fitted shell's outward normal.
MIN_MARKED_COMPONENT_HITS = 32
PROBES_PER_SHELL_RING = 8
INNER_FACE_PROBE_HALF_SPAN_CM = 18
OUTER_FACE_PROBE_START_CM = 100
OUTER_FACE_PROBE_END_CM = -10
MIN_SHELL_FACE_NORMAL_DOT = 0.82
MIN_SHELL_THICKNESS_CM = 25
MAX_SHELL_THICKNESS_CM = 90
MIN_PAIRED_FACE_PROBES = 22
COARSE_HULL_PLANE_TOLERANCE_CM = 0.02
SHELL_FACE_MARGIN_CM = 1
MAX_SHELL_PADDING_CM = 24
SHELL_PADDING_FRACTION = 0.45
MAX_COARSE_CHORD_CM = 12
COARSE_CHORD_THICKNESS_FRACTION = 0.30


def _marked_component(hits):
    counts = {}
    for hit in hits:
        component = getattr(hit, "component", None)
        if component is not None:
            counts[component] = counts.get(component, 0) + 1
    if not counts:
        return None
    component = max(counts, key=counts.get)
    owner = component.get_owner()
    if (
        counts[component] >= MIN_MARKED_COMPONENT_HITS
        and owner
        and owner.actor_has_tag(TAG)
    ):
        return component


def _surface_probes(cap):
    cx, cy, cz = cap["center"]
    a, b, h = cap["radii"]
    c, s = math.cos(cap["yaw_radians"]), math.sin(cap["yaw_radians"])
    low = math.asin(-cz / h)
    for t in (0.15, 0.46, 0.79):
        phi = low + t * (math.pi / 2 - low)
        for i in range(PROBES_PER_SHELL_RING):
            az = (i + 0.37 + t) * math.tau / PROBES_PER_SHELL_RING
            x, y, z = (
                math.cos(phi) * math.cos(az),
                math.cos(phi) * math.sin(az),
                math.sin(phi),
            )
            p = (
                cx + c * a * x - s * b * y,
                cy + s * a * x + c * b * y,
                cz + h * z,
            )
            yield (
                p,
                unit((c * x / a - s * y / b, s * x / a + c * y / b, z / h)),
            )
    yield (cx, cy, cz + h), (0, 0, 1)


def _offset(p, n, d):
    return tuple(x + d * y for x, y in zip(p, n))


def _wall_pairs(frame, cap, component):
    probes = list(_surface_probes(cap))
    rays = []
    for p, n in probes:
        for start, end in (
            (-INNER_FACE_PROBE_HALF_SPAN_CM, INNER_FACE_PROBE_HALF_SPAN_CM),
            (OUTER_FACE_PROBE_START_CM, OUTER_FACE_PROBE_END_CM),
        ):
            rays.append(
                (
                    frame.world(_offset(p, n, start)),
                    frame.world(_offset(p, n, end)),
                )
            )
    hits = yield from query(rays)
    # Opposing rays and normals identify the two faces of the same component.
    pairs = []
    for index, ((p, n), inner, outer) in enumerate(
        zip(probes, hits[::2], hits[1::2])
    ):
        if (
            not inner and not outer and index < PROBES_PER_SHELL_RING
        ):  # A low opening has neither shell face.
            continue
        if (
            not inner
            or not outer
            or getattr(inner, "component", None) != component
            or getattr(outer, "component", None) != component
        ):
            return []
        if (
            dot(frame.direction(inner[RayHitField.NORMAL]), n)
            > -MIN_SHELL_FACE_NORMAL_DOT
            or dot(frame.direction(outer[RayHitField.NORMAL]), n)
            < MIN_SHELL_FACE_NORMAL_DOT
        ):
            return []
        a, b = (
            frame.local(inner[RayHitField.POINT]),
            frame.local(outer[RayHitField.POINT]),
        )
        thickness = dot(tuple(y - x for x, y in zip(a, b)), n)
        if not MIN_SHELL_THICKNESS_CM <= thickness <= MAX_SHELL_THICKNESS_CM:
            return []
        pairs.append((a, b, n, thickness))
    return pairs if len(pairs) >= MIN_PAIRED_FACE_PROBES else []


def _separates(cap, pairs):
    vertices = cap["vertices"]
    planes = []
    for i, j, k in cap["triangles"]:
        a, b, c = vertices[i], vertices[j], vertices[k]
        inward = unit(
            cross(
                tuple(y - x for x, y in zip(a, b)),
                tuple(y - x for x, y in zip(a, c)),
            )
        )
        planes.append((inward, dot(a, inward)))

    def inside(p):
        return all(
            dot(p, n) >= d - COARSE_HULL_PLANE_TOLERANCE_CM for n, d in planes
        )

    # Require a small margin *within* the material on both accessible sides.
    return all(
        inside(_offset(a, n, SHELL_FACE_MARGIN_CM))
        and not inside(_offset(b, n, -SHELL_FACE_MARGIN_CM))
        for a, b, n, _ in pairs
    )


def simplify_hull_within_bounds(frame, cap, hits):
    """Use the measured inner and outer faces as bounds for a coarser hull."""
    component = _marked_component(hits)
    if component is None or "hull_chord_cm" not in cap:
        return cap
    pairs = yield from _wall_pairs(frame, cap, component)
    if not pairs:
        cap["wall_profile_review"] = (
            "厚墙测量缺少足够的同组件内外表面支持，采用标准曲顶。"
        )
        return cap
    thickness = min(row[3] for row in pairs)
    padding = min(MAX_SHELL_PADDING_CM, thickness * SHELL_PADDING_FRACTION)
    coarse = staggered(
        frame,
        cap["center"],
        [r + padding for r in cap["radii"]],
        cap["yaw_radians"],
        chord_cm=min(
            MAX_COARSE_CHORD_CM, thickness * COARSE_CHORD_THICKNESS_FRACTION
        ),
    )
    if (
        len(coarse["triangles"]) >= len(cap["triangles"])
        or not is_convex(coarse)
        or not _separates(coarse, pairs)
    ):
        cap["wall_profile_review"] = (
            "粗凸体未通过墙内外边界验收，采用标准曲顶。"
        )
        return cap
    # Retain the physical inside surface separately from the padded acoustic
    # Room.
    coarse.update(
        physical_radii=cap["radii"],
        wall_min_cm=thickness,
        wall_padding_cm=padding,
    )
    return coarse


within_wall = simplify_hull_within_bounds
