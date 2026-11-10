"""Room-boundary and selected-object opening discovery. Preview is value-only and actor-free."""

import json
import math
import re
import time
from pathlib import Path
import unreal as u
from interior_fit import editor
from interior_fit.opening_core import rectangles as rectangles, overlap

from .portals.faces import (
    faces,
    at,
    ray_blocked,
    room_pair,
    portal_boxes,
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


def transform_key(actor):
    return [
        round(float(v), 5)
        for value in (actor.get_actor_location(), actor.get_actor_rotation(), actor.get_actor_scale3d())
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
    config.update(editor.project_options().get("openings", {}))
    if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0 for v in config.values()):
        raise ValueError("Invalid openings configuration")
    if (
        config["grid_cm"] < 10
        or config["wall_probe_cm"] > 200
        or config["portal_depth_cm"] > 150
        or config["max_cells"] > 100000
    ):
        raise ValueError("Opening scan budget exceeded")
    return config


def _scan_surfaces(sources, selected_objects, rooms, config):
    surfaces = []
    if selected_objects:
        for room in rooms:
            for face in faces(room):
                proxy = {
                    "center": at(face, (face["left"] + face["right"]) / 2, (face["bottom"] + face["top"]) / 2),
                    "yaw": math.degrees(math.atan2(face["normal"][1], face["normal"][0])),
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
                raise RuntimeError("Find Openings needs selected Room/Volume actors")
            surfaces += [(room, face) for face in faces(room)]
    return surfaces


def _describe_connections(candidates, portals, rooms, selected_objects, recognize_doors):
    counters = {}
    for row in candidates:
        label = row["owner_label"]
        counters[label] = counters.get(label, 0) + 1
        row["name"] = "ACOUSTIC_PORTAL__" + label + "_" + str(counters[label])
        row["rooms"] = room_pair(rooms, row["center"], row["yaw"], row["half_extent"][0] + 5)
        row["existing"] = [p["label"] for p in portals if overlap(row, p)]
        row["open"] = not row["source_objects"] and row["sill_above_boundary_bottom"] < 60
        row["checked"] = False
        reasons = []
        if row["rooms"][0] == row["rooms"][1]:
            reasons.append("Both sides same Room / Outdoors; split Rooms first")
        if row["existing"]:
            reasons.append("Existing Portal: " + ", ".join(row["existing"]))
        if row["structural_support"] == 0 and "Outdoors" in row["rooms"]:
            reasons.append("No wall support; unbounded opening")
        row["blocked"] = bool(reasons)
        note = "; ".join(reasons) or (
            "Named door leaf; default CLOSED, review door state"
            if recognize_doors and row["source_objects"]
            else "Selected solid objects ignored; default CLOSED, review glazing/door state"
            if selected_objects
            else (
                "Elevated aperture; check glazing/obstructions, default CLOSED"
                if not row["open"]
                else "Open aperture candidate"
            )
        )
        row["summary"] = (
            f"{row['half_extent'][1] * 2:.0f} x {row['half_extent'][2] * 2:.0f} cm | {' <-> '.join(row['rooms'])} | {note}"
        )


def discover(sources, selected_objects=False, recognize_doors=False):
    world, _, all_actors = scene()
    config = parameters()
    rooms = editor.room_volumes()
    ignored = [a for a in all_actors if isinstance(a, editor.acoustic_types())]
    if selected_objects:
        ignored += sources
    leaves = [a for a in all_actors if is_door_leaf(a)] if recognize_doors else []
    candidates = []
    sampled = 0
    start = time.perf_counter()
    surfaces = _scan_surfaces(sources, selected_objects, rooms, config)
    for owner, face in surfaces:
        if recognize_doors and (face["right"] - face["left"] < 65 or face["top"] - face["bottom"] < 166):
            continue
        found, count = scan_face(world, owner if isinstance(owner, u.Volume) else None, face, ignored + leaves, config)
        sampled += count
        if sampled > config["max_cells"]:
            raise RuntimeError("Total opening scan budget exceeded; select fewer Rooms or increase grid_cm")
        for row in found:
            if selected_objects and not clip_to_selection(row, sources):
                continue
            row["owner"] = owner.get_path_name()
            row["owner_transform"] = transform_key(owner)
            row["owner_geometry"] = geometry_key(owner)
            row["source_objects"] = [a.get_path_name() for a in sources] if selected_objects else []
            row["source_transforms"] = [transform_key(a) for a in sources] if selected_objects else []
            if leaves:
                matching = [a for a in leaves if intersects_selection(row, [a], 0)]
                row["source_objects"] = [a.get_path_name() for a in matching]
                row["source_transforms"] = [transform_key(a) for a in matching]
            row["owner_label"] = sources[0].get_actor_label() if selected_objects else owner.get_actor_label()
            if any(overlap(row, old, 10) for old in candidates):
                continue
            candidates.append(row)
    if len(candidates) > 128:
        raise RuntimeError("More than 128 opening candidates; select fewer Rooms")
    _describe_connections(candidates, portal_boxes(all_actors), rooms, selected_objects, recognize_doors)
    return {
        "world": world.get_path_name(),
        "rows": candidates,
        "sampled_cells": sampled,
        "seconds": time.perf_counter() - start,
        "selected_objects": selected_objects,
    }


def reconnect_discovered(batches):
    """Reuse this floor session's measured apertures; refresh their Room ownership.

    New neighbouring Rooms change connections, not the measured wall opening.
    Creation still revalidates source transforms, geometry and obstruction.
    """
    from copy import deepcopy
    world, _, all_actors = scene()
    candidates = []
    for data in batches:
        if data['world'] != world.get_path_name():
            raise RuntimeError('Map changed during floor opening discovery')
        for row in data['rows']:
            if not any(overlap(row, old, 10) for old in candidates):
                candidates.append(deepcopy(row))
    if len(candidates) > 128:
        raise RuntimeError('More than 128 opening candidates; split the floor task')
    _describe_connections(candidates, portal_boxes(all_actors), editor.room_volumes(), False, True)
    return dict(world=world.get_path_name(),rows=candidates,selected_objects=False,
        sampled_cells=sum(data.get('sampled_cells',0) for data in batches))


def open_selected(selected_objects=False):
    try:
        _, actors, _ = scene()
        selected = actors.get_selected_level_actors()
        if not selected:
            raise RuntimeError("Select Room volumes or door/window mesh actors first")
        if selected_objects and any(isinstance(a, u.Volume) for a in selected):
            raise RuntimeError("Select physical door/window actors, not Volumes")
        data = discover(selected, selected_objects)
        path = Path(u.Paths.project_saved_dir()) / "InteriorFit/openings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if not data["rows"]:
            raise RuntimeError("No supported openings found. Check collision or use selected door/window objects.")
        if not u.InteriorFitLibrary.show_openings(json.dumps(data)):
            raise RuntimeError("Could not open the Openings panel")
    except Exception as error:
        u.log_error("Interior Fit Openings: " + str(error))
        u.EditorDialog.show_message("Interior Fit Openings", str(error), u.AppMsgType.OK)


def validate_batch(data):
    world, actors, all_actors = scene()
    if world.get_path_name() != data["world"]:
        raise RuntimeError("Map changed; run Find Openings again")
    rows = data["rows"]
    if not rows or len(rows) > 128:
        raise RuntimeError("Select between 1 and 128 openings")
    labels = {a.get_actor_label() for a in all_actors}
    portals = portal_boxes(all_actors)
    lookup = {a.get_path_name(): a for a in all_actors}
    rooms = editor.room_volumes()
    for row in rows:
        name = row["name"].strip()
        row["name"] = name
        if not name or len(name) > 160 or re.search(r"[\r\n\t/\\]", name):
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
        if any(a is None or transform_key(a) != expected for a, expected in zip(selected, row["source_transforms"])):
            raise RuntimeError("Selected door/window changed; rescan")
        ignored = [a for a in all_actors if isinstance(a, editor.acoustic_types())] + selected
        angle = math.radians(row["yaw"])
        n = [math.cos(angle), math.sin(angle)]
        t = [-n[1], n[0]]
        face = {"normal": n, "tangent": t, "plane": sum(row["center"][i] * n[i] for i in (0, 1))}
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
                    raise RuntimeError("Opening is now obstructed; rescan " + name)
        if room_pair(rooms, row["center"], row["yaw"], row["half_extent"][0] + 5) != row["rooms"]:
            raise RuntimeError("Room connections changed; rescan " + name)
        portals.append(row)
    return world, actors, rows


def spawn_portal(world, cls, row):
    return u.InteriorFitLibrary.create_box_volume(
        world,
        cls,
        u.Transform(location=u.Vector(*row["center"]), rotation=u.Rotator(yaw=row["yaw"])),
        u.Vector(*row["half_extent"]),
    )


def create_batch(data):
    cls = getattr(u, "AkAcousticPortal", None)
    if cls is None:
        raise RuntimeError("Enable Wwise integration to create acoustic Portals")
    world, actors, rows = validate_batch(data)
    created = []
    with u.ScopedEditorTransaction("Interior Fit: Create Portals"):
        try:
            for row in rows:
                portal = spawn_portal(world, cls, row)
                if not portal:
                    raise RuntimeError("Native Portal creation failed")
                created.append(portal)
                portal.set_actor_label(row["name"])
                portal.set_folder_path("InteriorFit/Portals")
                component = portal.get_editor_property("portal")
                state_type = type(component.get_editor_property("initial_state"))
                component.set_editor_property("initial_state", state_type.OPEN if row["open"] else state_type.CLOSED)
                portal.enable_portal() if row["open"] else portal.disable_portal()
            actors.set_selected_level_actors(created)
        except Exception as error:
            surviving = []
            for actor in reversed(created):
                label = actor.get_actor_label()
                if not actors.destroy_actor(actor):
                    surviving.append(label)
            if surviving:
                raise RuntimeError(str(error) + "; rollback could not remove: " + ", ".join(surviving)) from error
            raise
    u.InteriorFitLibrary.draw_opening_previews(world, "[]")
    return created


def _focus_rows(rows):
    """Frame all selected openings, including each rectangle's world-space yaw."""
    if not rows:
        return
    lower = [float("inf")] * 3
    upper = [-float("inf")] * 3
    for row in rows:
        angle = math.radians(row["yaw"])
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        e = row["half_extent"]
        extent = [c * e[0] + s * e[1], s * e[0] + c * e[1], e[2]]
        for axis in range(3):
            lower[axis] = min(lower[axis], row["center"][axis] - extent[axis])
            upper[axis] = max(upper[axis], row["center"][axis] + extent[axis])
    u.InteriorFitLibrary.focus_opening(
        u.Vector(*[(a + b) / 2 for a, b in zip(lower, upper)]),
        u.Vector(*[(b - a) / 2 + 20 for a, b in zip(lower, upper)]),
    )


def apply_action(action, data):
    try:
        world, _, _ = scene()
        if world.get_path_name() != data["world"]:
            raise RuntimeError("Map changed; rescan openings")
        if action in ("preview", "focus"):
            rows = data["rows"]
            if not u.InteriorFitLibrary.draw_opening_previews(world, json.dumps(rows)):
                raise RuntimeError("Could not draw opening previews")
            _focus_rows(rows)
            u.log(f"Interior Fit: previewing {len(rows)} checked openings (Open state does not control inclusion)")
            return
        if action != "create":
            raise ValueError("Unknown opening action")
        created = create_batch(data)
        u.EditorDialog.show_message(
            "Interior Fit",
            f"Created {len(created)} Portals. Undo is available. Map has not been saved.",
            u.AppMsgType.OK,
        )
    except Exception as error:
        u.log_error("Interior Fit Openings: " + str(error))
        u.EditorDialog.show_message("Interior Fit Openings", str(error), u.AppMsgType.OK)
