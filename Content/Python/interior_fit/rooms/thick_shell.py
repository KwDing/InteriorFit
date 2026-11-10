"""Optional authoring profile: spend material thickness on a simpler acoustic hull."""
import math

from .cap_hull import staggered, is_convex
from .frame import cross, dot, unit
from .rays import query

TAG = "InteriorFitThickShell"


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
    if counts[component] >= 32 and owner and owner.actor_has_tag(TAG):
        return component


def _surface_probes(cap):
    cx, cy, cz = cap["center"]
    a, b, h = cap["radii"]
    c, s = math.cos(cap["yaw_radians"]), math.sin(cap["yaw_radians"])
    low = math.asin(-cz/h)
    for t in (0.15, 0.46, 0.79):
        phi = low+t*(math.pi/2-low)
        for i in range(8):
            az = (i+0.37+t)*math.tau/8
            x, y, z = math.cos(phi)*math.cos(az), math.cos(phi)*math.sin(az), math.sin(phi)
            p = (cx+c*a*x-s*b*y, cy+s*a*x+c*b*y, cz+h*z)
            yield p, unit((c*x/a-s*y/b, s*x/a+c*y/b, z/h))
    yield (cx, cy, cz+h), (0, 0, 1)


def _offset(p, n, d):
    return tuple(x+d*y for x, y in zip(p, n))


def _wall_pairs(frame, cap, component):
    probes = list(_surface_probes(cap))
    rays = []
    for p, n in probes:
        for start, end in ((-18, 18), (100, -10)):
            rays.append((frame.world(_offset(p, n, start)), frame.world(_offset(p, n, end))))
    hits = yield from query(rays)
    pairs = []
    for index, ((p, n), inner, outer) in enumerate(zip(probes, hits[::2], hits[1::2])):
        if not inner and not outer and index < 8:  # A low opening has neither shell face.
            continue
        if not inner or not outer or getattr(inner, "component", None) != component or getattr(outer, "component", None) != component:
            return []
        if dot(frame.direction(inner[1]), n) > -0.82 or dot(frame.direction(outer[1]), n) < 0.82:
            return []
        a, b = frame.local(inner[0]), frame.local(outer[0])
        thickness = dot(tuple(y-x for x, y in zip(a, b)), n)
        if not 25 <= thickness <= 90:
            return []
        pairs.append((a, b, n, thickness))
    return pairs if len(pairs) >= 22 else []


def _separates(cap, pairs):
    vertices = cap["vertices"]
    planes = []
    for i, j, k in cap["triangles"]:
        a, b, c = vertices[i], vertices[j], vertices[k]
        inward = unit(cross(tuple(y-x for x, y in zip(a, b)), tuple(y-x for x, y in zip(a, c))))
        planes.append((inward, dot(a, inward)))

    def inside(p):
        return all(dot(p, n) >= d-0.02 for n, d in planes)
    # Require a small margin *within* the material on both accessible sides.
    return all(inside(_offset(a, n, 1)) and not inside(_offset(b, n, -1)) for a, b, n, _ in pairs)


def within_wall(frame, cap, hits):
    component = _marked_component(hits)
    if component is None or "hull_chord_cm" not in cap:
        return cap
    pairs = yield from _wall_pairs(frame, cap, component)
    if not pairs:
        cap["wall_profile_review"] = "厚墙测量缺少足够的同组件内外表面支持，采用标准曲顶。"
        return cap
    thickness = min(row[3] for row in pairs)
    padding = min(24, thickness*0.45)
    coarse = staggered(frame, cap["center"], [r+padding for r in cap["radii"]],
                       cap["yaw_radians"], chord_cm=min(12, thickness*0.30))
    if len(coarse["triangles"]) >= len(cap["triangles"]) or not is_convex(coarse) or not _separates(coarse, pairs):
        cap["wall_profile_review"] = "粗凸体未通过墙内外边界验收，采用标准曲顶。"
        return cap
    # Retain the physical inside surface separately from the padded acoustic Room.
    coarse.update(physical_radii=cap["radii"], wall_min_cm=thickness, wall_padding_cm=padding)
    return coarse
