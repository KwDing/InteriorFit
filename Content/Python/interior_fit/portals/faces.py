import json
import math
import re
import unreal as u
from .. import editor
from ..opening_core import rectangles


def faces(room, selection=False):
    result = []
    seen = set()
    encoded = (
        u.InteriorFitLibrary.get_actor_panel_face(room) if selection else u.InteriorFitLibrary.get_volume_faces(room)
    )
    for face in json.loads(encoded):
        n = face["normal"]
        length = math.hypot(n[0], n[1])
        n = [n[0] / length, n[1] / length]
        if n[0] < -0.001 or (abs(n[0]) < 0.001 and n[1] < 0):
            n = [-n[0], -n[1]]
        t = [-n[1], n[0]]
        v = face["vertices"]
        d = sum(v[0][i] * n[i] for i in (0, 1))
        along = [sum(p[i] * t[i] for i in (0, 1)) for p in v]
        item = {
            "normal": n,
            "tangent": t,
            "plane": d,
            "left": min(along),
            "right": max(along),
            "bottom": min(p[2] for p in v),
            "top": max(p[2] for p in v),
        }
        key = tuple(round(x, 1) for x in [*n, d, item["left"], item["right"], item["bottom"], item["top"]])
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def at(face, along, z, depth=0):
    return [face["normal"][i] * (face["plane"] + depth) + face["tangent"][i] * along for i in (0, 1)] + [z]


def ray_blocked(world, face, along, z, ignored, depth):
    a = at(face, along, z, -depth)
    b = at(face, along, z, depth)
    return editor.trace(world, a, b, ignored) is not None or editor.trace(world, b, a, ignored) is not None


def room_pair(rooms, center, yaw, depth):
    angle = math.radians(yaw)
    n = [math.cos(angle), math.sin(angle)]
    pair = []
    for sign in (-1, 1):
        p = u.Vector(center[0] + n[0] * depth * sign, center[1] + n[1] * depth * sign, center[2])
        inside = [r for r in rooms if u.InteriorFitLibrary.contains_point(r, p)]
        inside.sort(key=lambda r: float(r.get_editor_property("room").get_editor_property("priority")), reverse=True)
        pair.append(inside[0].get_actor_label() if inside else "Outdoors")
    return pair


def portal_boxes(actors):
    cls = getattr(u, "AkAcousticPortal", None)
    output = []
    for actor in actors:
        if not cls or not isinstance(actor, cls):
            continue
        vertices = [v for face in json.loads(u.InteriorFitLibrary.get_volume_faces(actor)) for v in face["vertices"]]
        if not vertices:
            continue
        yaw = actor.get_actor_rotation().yaw
        a = math.radians(yaw)
        n = [math.cos(a), math.sin(a)]
        t = [-n[1], n[0]]
        xs = [sum(v[i] * n[i] for i in (0, 1)) for v in vertices]
        ys = [sum(v[i] * t[i] for i in (0, 1)) for v in vertices]
        zs = [v[2] for v in vertices]
        x = (min(xs) + max(xs)) / 2
        y = (min(ys) + max(ys)) / 2
        output.append(
            {
                "center": [n[i] * x + t[i] * y for i in (0, 1)] + [(min(zs) + max(zs)) / 2],
                "half_extent": [(max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2, (max(zs) - min(zs)) / 2],
                "yaw": yaw,
                "label": actor.get_actor_label(),
            }
        )
    return output


def scan_face(world, room, face, ignored, config):
    step = config["grid_cm"]
    cols = max(1, math.ceil((face["right"] - face["left"]) / step))
    rows = max(1, math.ceil((face["top"] - face["bottom"]) / step))
    if cols * rows > config["max_cells"]:
        raise RuntimeError("Opening grid too large; increase openings.grid_cm")
    dx = (face["right"] - face["left"]) / cols
    dz = (face["top"] - face["bottom"]) / rows
    clear = set()
    supported = 0
    for x in range(cols):
        along = face["left"] + (x + 0.5) * dx
        for y in range(rows):
            z = face["bottom"] + (y + 0.5) * dz
            if room and not any(
                u.InteriorFitLibrary.contains_point(room, u.Vector(*at(face, along, z, sign * 15))) for sign in (-1, 1)
            ):
                continue
            supported += 1
            if not ray_blocked(world, face, along, z, ignored, config["wall_probe_cm"]):
                clear.add((x, y))
    result = []
    for left, bottom, right, top in rectangles(
        clear, cols, rows, math.ceil(config["min_width_cm"] / dx), math.ceil(config["min_height_cm"] / dz)
    ):
        width = (right - left) * dx
        height = (top - bottom) * dz
        center = at(face, face["left"] + (left + right) * dx / 2, face["bottom"] + (bottom + top) * dz / 2)
        result.append(
            {
                "center": center,
                "half_extent": [config["portal_depth_cm"], max(1, width / 2 - 2), max(1, height / 2 - 2)],
                "yaw": math.degrees(math.atan2(face["normal"][1], face["normal"][0])),
                "structural_support": supported - len(clear),
                "grid_cm": step,
                "sill_above_boundary_bottom": bottom * dz,
            }
        )
    return result, cols * rows


def bounds(actor):
    center, extent = actor.get_actor_bounds(False)
    return list(center.to_tuple()), list(extent.to_tuple())


def intersects_selection(row, selected, padding=25):
    angle = math.radians(row["yaw"])
    n = [math.cos(angle), math.sin(angle)]
    t = [-n[1], n[0]]
    for actor in selected:
        c, e = bounds(actor)
        d = [c[i] - row["center"][i] for i in range(3)]
        if abs(sum(d[i] * n[i] for i in (0, 1))) > sum(e[i] * abs(n[i]) for i in (0, 1)) + 120:
            continue
        if (
            abs(sum(d[i] * t[i] for i in (0, 1)))
            > sum(e[i] * abs(t[i]) for i in (0, 1)) + row["half_extent"][1] + padding
        ):
            continue
        if abs(d[2]) <= e[2] + row["half_extent"][2] + padding:
            return True
    return False


def selected_faces(selected):
    """Fallback preserves each selected actor's yaw using local component bounds."""
    return [(actor, face) for actor in selected for face in faces(actor, True)]


def clip_to_selection(row, selected):
    angle = math.radians(row["yaw"])
    n = [math.cos(angle), math.sin(angle)]
    t = [-n[1], n[0]]
    along = sum(row["center"][i] * t[i] for i in (0, 1))
    intervals = []
    for actor in selected:
        if not intersects_selection(row, [actor], 0):
            continue
        c, e = bounds(actor)
        middle = sum(c[i] * t[i] for i in (0, 1))
        half = sum(e[i] * abs(t[i]) for i in (0, 1))
        intervals.append(
            (
                max(along - row["half_extent"][1], middle - half),
                min(along + row["half_extent"][1], middle + half),
                max(row["center"][2] - row["half_extent"][2], c[2] - e[2]),
                min(row["center"][2] + row["half_extent"][2], c[2] + e[2]),
            )
        )
    if not intervals:
        return False
    left = min(v[0] for v in intervals)
    right = max(v[1] for v in intervals)
    bottom = min(v[2] for v in intervals)
    top = max(v[3] for v in intervals)
    if right - left < 30 or top - bottom < 40:
        return False
    shift = (left + right) / 2 - along
    row["center"] = [row["center"][i] + t[i] * shift for i in (0, 1)] + [(bottom + top) / 2]
    row["half_extent"] = [row["half_extent"][0], (right - left) / 2, (top - bottom) / 2]
    return True


def is_door_leaf(actor):
    if not isinstance(actor, u.StaticMeshActor):
        return False
    mesh = actor.static_mesh_component.static_mesh
    names = actor.get_actor_label() + " " + (mesh.get_name() if mesh else "")
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", names).lower()
    if not re.search(r"(?:^|[^a-z])door", words) or re.search(r"frame|handle|hinge|trim", words):
        return False
    _, e = bounds(actor)
    return 60 <= e[2] <= 190 and min(e[0], e[1]) <= 65 and max(e[0], e[1]) <= 190
