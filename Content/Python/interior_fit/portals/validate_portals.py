"""Revalidate source geometry and Room links before writing Portals."""

import math
import re

from interior_fit import editor_scene_adapter
from .discover_openings import (
    MAX_OPENING_CANDIDATES,
    geometry_key,
    parameters,
    scene,
    transform_key,
)
from .find_opening_rectangles import overlap
from .scan_opening_faces import portal_boxes, ray_blocked, room_pair


MAX_PORTAL_NAME_LENGTH = 160


def validate_batch(data):
    world, actors, all_actors = scene()
    if world.get_path_name() != data["world"]:
        raise RuntimeError("Map changed; run Find Openings again")
    rows = data["rows"]
    if not rows or len(rows) > MAX_OPENING_CANDIDATES:
        raise RuntimeError(
            f"Select between 1 and {MAX_OPENING_CANDIDATES} openings"
        )
    labels = {a.get_actor_label() for a in all_actors}
    portals = portal_boxes(all_actors)
    lookup = {a.get_path_name(): a for a in all_actors}
    rooms = editor_scene_adapter.room_volumes()
    for row in rows:
        name = row["name"].strip()
        row["name"] = name
        if (
            not name
            or len(name) > MAX_PORTAL_NAME_LENGTH
            or re.search(r"[\r\n\t/\\]", name)
        ):
            raise RuntimeError("Invalid Portal name: " + name)
        if name in labels:
            raise RuntimeError("Name already exists or is repeated: " + name)
        labels.add(name)
        if row["blocked"] or any(overlap(row, p) for p in portals):
            raise RuntimeError("Blocked or overlapping Portal: " + name)
        owner = lookup.get(row["owner"])
        if owner is None or transform_key(owner) != row["owner_transform"]:
            raise RuntimeError("Source moved/deleted; rescan " + name)
        if geometry_key(owner) != row["owner_geometry"]:
            raise RuntimeError("Source shape changed; rescan " + name)
        selected = [lookup.get(path) for path in row["source_objects"]]
        if any(
            a is None or transform_key(a) != expected
            for a, expected in zip(selected, row["source_transforms"])
        ):
            raise RuntimeError("Selected door/window changed; rescan")
        ignored = [
            a
            for a in all_actors
            if isinstance(a, editor_scene_adapter.acoustic_types())
        ] + selected
        angle = math.radians(row["yaw"])
        n = [math.cos(angle), math.sin(angle)]
        t = [-n[1], n[0]]
        face = {
            "normal": n,
            "tangent": t,
            "plane": sum(row["center"][i] * n[i] for i in (0, 1)),
        }
        along = sum(row["center"][i] * t[i] for i in (0, 1))
        for horizontal in (-0.8, 0, 0.8):
            for vertical in (-0.8, 0, 0.8):
                if ray_blocked(
                    world,
                    face,
                    along + horizontal * row["half_extent"][1],
                    row["center"][2] + vertical * row["half_extent"][2],
                    ignored,
                    parameters()["wall_probe_cm"],
                ):
                    raise RuntimeError(
                        "Opening is now obstructed; rescan " + name
                    )
        if (
            room_pair(
                rooms, row["center"], row["yaw"], row["half_extent"][0] + 5
            )
            != row["rooms"]
        ):
            raise RuntimeError("Room connections changed; rescan " + name)
        portals.append(row)
    return world, actors, rows
