"""Discover openings and associate them with adjacent Rooms."""

import math
import time
import unreal as u
from interior_fit import editor_scene_adapter
from interior_fit.load_project_options import load_project_options
from interior_fit.portals.find_opening_rectangles import overlap

from interior_fit.portals.scan_opening_faces import (
    faces,
    at,
    ray_blocked,
    room_pair,
    portal_boxes,
    grid_size,
    scan_face,
    bounds as bounds,
    intersects_selection,
    selected_faces,
    clip_to_selection,
    is_door_leaf,
)

DEFAULTS = {
    "grid_cm": 20.0,
    "wall_probe_cm": 60.0,
    "portal_depth_cm": 60.0,
    "min_width_cm": 40.0,
    "min_height_cm": 60.0,
    "max_cells": 60000,
}


# Bound the configurable scan workload. The row cap must match the C++
# opening review panel and preview input limit.
MIN_OPENING_GRID_CM = 10
MAX_WALL_PROBE_CM = 200
MAX_PORTAL_DEPTH_CM = 150
MAX_OPENING_SCAN_CELLS = 100000
MIN_RECOGNIZED_DOOR_WIDTH_CM = 65
MIN_RECOGNIZED_DOOR_HEIGHT_CM = 166
MAX_OPENING_CANDIDATES = 128


def transform_key(actor):
    return [
        round(float(v), 5)
        for value in (
            actor.get_actor_location(),
            actor.get_actor_rotation(),
            actor.get_actor_scale3d(),
        )
        for v in value.to_tuple()
    ]


def geometry_key(actor):
    return (
        u.InteriorFitLibrary.get_volume_faces(actor)
        if isinstance(actor, u.Volume)
        else u.InteriorFitLibrary.get_actor_panel_face(actor)
    )


def scene():
    if u.get_editor_subsystem(u.UnrealEditorSubsystem).get_game_world():
        raise RuntimeError("Exit PIE before opening authoring")
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    return world, actors, actors.get_all_level_actors()


def parameters():
    config = dict(DEFAULTS)
    config.update(load_project_options().get("openings", {}))
    if any(
        not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0
        for v in config.values()
    ):
        raise ValueError("Invalid openings configuration")
    if (
        config["grid_cm"] < MIN_OPENING_GRID_CM
        or config["wall_probe_cm"] > MAX_WALL_PROBE_CM
        or config["portal_depth_cm"] > MAX_PORTAL_DEPTH_CM
        or config["max_cells"] > MAX_OPENING_SCAN_CELLS
    ):
        raise ValueError("Opening scan budget exceeded")
    return config


def _scan_surfaces(sources, selected_objects, rooms, config):
    surfaces = []
    if selected_objects:
        for room in rooms:
            for face in faces(room):
                proxy = {
                    "center": at(
                        face,
                        (face["left"] + face["right"]) / 2,
                        (face["bottom"] + face["top"]) / 2,
                    ),
                    "yaw": math.degrees(
                        math.atan2(face["normal"][1], face["normal"][0])
                    ),
                    "half_extent": [
                        config["portal_depth_cm"],
                        (face["right"] - face["left"]) / 2,
                        (face["top"] - face["bottom"]) / 2,
                    ],
                }
                if intersects_selection(proxy, sources):
                    surfaces.append((room, face))
        if not surfaces:
            surfaces = selected_faces(sources)
    else:
        for room in sources:
            if not isinstance(room, u.Volume):
                raise RuntimeError(
                    "Find Openings needs selected Room/Volume actors"
                )
            surfaces += [(room, face) for face in faces(room)]
    return surfaces


def _describe_connections(
    candidates, portals, rooms, selected_objects, recognize_doors
):
    counters = {}
    for row in candidates:
        label = row["owner_label"]
        counters[label] = counters.get(label, 0) + 1
        row["name"] = "ACOUSTIC_PORTAL__" + label + "_" + str(counters[label])
        row["rooms"] = room_pair(
            rooms, row["center"], row["yaw"], row["half_extent"][0] + 5
        )
        row["existing"] = [p["label"] for p in portals if overlap(row, p)]
        row["open"] = (
            not row["source_objects"]
            and row["sill_above_boundary_bottom"] < 60
        )
        row["checked"] = False
        reasons = []
        if row["rooms"][0] == row["rooms"][1]:
            reasons.append(
                "Both sides same Room / Outdoors; split Rooms first"
            )
        if row["existing"]:
            reasons.append("Existing Portal: " + ", ".join(row["existing"]))
        if row["structural_support"] == 0 and "Outdoors" in row["rooms"]:
            reasons.append("No wall support; unbounded opening")
        row["blocked"] = bool(reasons)
        note = "; ".join(reasons) or (
            "Named door leaf; default CLOSED, review door state"
            if recognize_doors and row["source_objects"]
            else (
                "Selected solid objects ignored; default CLOSED, "
                "review glazing/door state"
            )
            if selected_objects
            else (
                "Elevated aperture; check glazing/obstructions, default CLOSED"
                if not row["open"]
                else "Open aperture candidate"
            )
        )
        row["summary"] = (
            f"{row['half_extent'][1] * 2:.0f} x "
            f"{row['half_extent'][2] * 2:.0f} cm | "
            f"{' <-> '.join(row['rooms'])} | {note}"
        )


def _opening_scan_surfaces(
    sources, selected_objects, rooms, config, recognize_doors
):
    surfaces = _scan_surfaces(sources, selected_objects, rooms, config)
    if recognize_doors:
        surfaces = [
            (owner, face)
            for owner, face in surfaces
            if face["right"] - face["left"] >= MIN_RECOGNIZED_DOOR_WIDTH_CM
            and face["top"] - face["bottom"] >= MIN_RECOGNIZED_DOOR_HEIGHT_CM
        ]
    total = sum(
        math.prod(grid_size(face, config["grid_cm"])) for _, face in surfaces
    )
    if total > config["max_cells"]:
        raise RuntimeError(
            "Total opening scan budget exceeded; select fewer Rooms or "
            "increase grid_cm"
        )
    return surfaces, total


def _opening_rows(found, owner, selected, leaves):
    for row in found:
        if selected:
            for actor in selected:
                clipped = clip_to_selection(row, actor)
                if clipped is not None:
                    yield _with_source(
                        clipped, owner, actor.get_actor_label(), [actor]
                    )
        else:
            matching = [a for a in leaves if intersects_selection(row, [a], 0)]
            yield _with_source(row, owner, owner.get_actor_label(), matching)


def _with_source(row, owner, label, sources):
    return dict(
        row,
        owner=owner.get_path_name(),
        owner_transform=transform_key(owner),
        owner_geometry=geometry_key(owner),
        owner_label=label,
        source_objects=[actor.get_path_name() for actor in sources],
        source_transforms=[transform_key(actor) for actor in sources],
    )


def discover(sources, selected_objects=False, recognize_doors=False):
    world, _, all_actors = scene()
    config = parameters()
    rooms = editor_scene_adapter.room_volumes()
    selected = sources if selected_objects else []
    acoustic_types = editor_scene_adapter.acoustic_types()
    ignored = [a for a in all_actors if isinstance(a, acoustic_types)]
    leaves = (
        [a for a in all_actors if is_door_leaf(a)] if recognize_doors else []
    )
    ignored.extend(selected)
    ignored.extend(leaves)
    start = time.perf_counter()
    surfaces, sampled = _opening_scan_surfaces(
        sources, selected_objects, rooms, config, recognize_doors
    )
    candidates = []
    with u.ScopedSlowTask(sampled, "扫描门窗开口") as progress:
        progress.make_dialog_delayed(0.5, True)
        for owner, face in surfaces:
            room = owner if isinstance(owner, u.Volume) else None
            found, _ = scan_face(world, room, face, ignored, config, progress)
            for row in _opening_rows(found, owner, selected, leaves):
                if not any(overlap(row, old, 10) for old in candidates):
                    candidates.append(row)
    if len(candidates) > MAX_OPENING_CANDIDATES:
        raise RuntimeError(
            f"More than {MAX_OPENING_CANDIDATES} opening candidates; select "
            f"fewer Rooms"
        )
    _describe_connections(
        candidates,
        portal_boxes(all_actors),
        rooms,
        selected_objects,
        recognize_doors,
    )
    return {
        "world": world.get_path_name(),
        "rows": candidates,
        "sampled_cells": sampled,
        "seconds": time.perf_counter() - start,
        "selected_objects": selected_objects,
    }


def reconnect_discovered(batches):
    """Reuse this floor session's measured apertures; refresh their Room
    ownership.

    New neighbouring Rooms change connections, not the measured wall opening.
    Creation still revalidates source transforms, geometry and obstruction.
    """
    from copy import deepcopy

    world, _, all_actors = scene()
    candidates = []
    for data in batches:
        if data["world"] != world.get_path_name():
            raise RuntimeError("Map changed during floor opening discovery")
        for row in data["rows"]:
            if not any(overlap(row, old, 10) for old in candidates):
                candidates.append(deepcopy(row))
    if len(candidates) > MAX_OPENING_CANDIDATES:
        raise RuntimeError(
            f"More than {MAX_OPENING_CANDIDATES} opening candidates; split "
            f"the floor task"
        )
    _describe_connections(
        candidates,
        portal_boxes(all_actors),
        editor_scene_adapter.room_volumes(),
        False,
        True,
    )
    return dict(
        world=world.get_path_name(),
        rows=candidates,
        selected_objects=False,
        sampled_cells=sum(data.get("sampled_cells", 0) for data in batches),
    )
