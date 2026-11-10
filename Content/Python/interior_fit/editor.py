"""Selected-actor interior preview and conservative native Room creation; no automatic save."""

import json
import sys
from pathlib import Path
import unreal as u

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from interior_fit.core import (
    select_plane as select_plane,
    floor_component as floor_component,
    validate_settings as validate_settings,
)

from interior_fit.rooms.box import (
    DEFAULTS,
    position as position,
    vertical_surface as vertical_surface,
    plane_votes as plane_votes,
    opening_plane as opening_plane,
    sample_floor as sample_floor,
    scan_at as scan_at,
    scan,
)
from interior_fit.rooms.scene import project_options, acoustic_types, room_volumes, trace as trace, configure_wwise_room


def existing_rooms(world, result):
    """Report existing Wwise brush containment without a Wwise compile-time dependency."""
    names = set()
    volumes = room_volumes()
    points = [result.get("original_seed", result["seed"])]
    for cell in result.get("cells", []):
        p = cell["point"]
        points.append([p[0], p[1], p[2] + 120])
    for point in points:
        for volume in volumes:
            if u.InteriorFitLibrary.contains_point(volume, u.Vector(*point)):
                names.add(volume.get_actor_label())
    return sorted(names)


def selected_scan():
    if u.get_editor_subsystem(u.UnrealEditorSubsystem).get_game_world():
        raise RuntimeError("Exit PIE before fitting")
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    selected = actors.get_selected_level_actors()
    if len(selected) != 1:
        raise RuntimeError("Select exactly one seed Actor inside a room")
    actor = selected[0]
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    ignored = [
        a for a in actors.get_all_level_actors() if isinstance(a, acoustic_types()) or "InteriorFitVolume" in a.tags
    ]
    if actor not in ignored:
        ignored.append(actor)
    settings = dict(DEFAULTS)
    settings.update(project_options().get("scan", {}))
    result = scan(world, list(actor.get_actor_location().to_tuple()), actor.get_actor_rotation().yaw, ignored, settings)
    result.update(map=world.get_path_name(), actor=actor.get_path_name())
    result["existing_rooms"] = existing_rooms(world, result)
    path = Path(u.Paths.project_saved_dir()) / "InteriorFit/selected_preview.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if "center" in result:
        color = u.LinearColor(1, 0, 0, 1) if result["issues"] else u.LinearColor(0, 1, 0, 1)
        result["foreground_preview"] = u.InteriorFitLibrary.draw_preview(
            world,
            u.Transform(location=u.Vector(*result["center"]), rotation=u.Rotator(yaw=result["yaw"])),
            u.Vector(*result["half_extent"]),
            color,
        )
    else:
        u.InteriorFitLibrary.draw_preview(world, u.Transform(), u.Vector(0, 0, 0), u.LinearColor())
    status = "; ".join(result["issues"]) or "Ready: green candidate box (5 minutes)"
    status += " | Existing Rooms: " + (", ".join(result["existing_rooms"]) or "none")
    u.log_warning("Interior Fit preview: " + status) if result["issues"] else u.log("Interior Fit preview: " + status)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return world, actor, result


def preview_selected():
    try:
        _, _, result = selected_scan()
        status = (
            "Cannot create: " + ("; ".join(result["issues"]))
            if result["issues"]
            else "Ready: green box shows fitted interior."
        )
        status += "\nExisting Rooms: " + (", ".join(result["existing_rooms"]) or "none")
        if result["existing_rooms"]:
            status += "\nCreation is blocked here to avoid duplicate Rooms. Existing Rooms were NOT used to calculate the fit."
        if "center" in result:
            status += "\nCenter (cm): " + ", ".join(f"{v:.1f}" for v in result["center"])
            status += "\nSize (cm): " + ", ".join(f"{v * 2:.1f}" for v in result["half_extent"])
        status += "\nPreview lasts 5 minutes; a new preview replaces it. No map changes."
        u.EditorDialog.show_message("Interior Fit Preview", status, u.AppMsgType.OK)
    except Exception as error:
        u.log_error("Interior Fit: " + str(error))


def clear_preview():
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    if not u.InteriorFitLibrary.clear_surface_previews(world):
        raise RuntimeError("预览未能完全清除；请退出 PIE 后重试。")
    u.InteriorFitLibrary.draw_spline_preview(
        u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world(), [], False, False
    )
    u.InteriorFitLibrary.draw_area_preview(u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world(), "")
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    u.InteriorFitLibrary.draw_preview(world, u.Transform(), u.Vector(0, 0, 0), u.LinearColor())
    u.InteriorFitLibrary.draw_opening_previews(world, "[]")


def find_openings_selected():
    from interior_fit.openings import open_selected

    open_selected(False)


def fit_openings_selected():
    from interior_fit.openings import open_selected

    open_selected(True)


def create_selected():
    room = None
    try:
        cls = getattr(u, "AkSpatialAudioVolume", None)
        if cls is None:
            raise RuntimeError("Wwise is not enabled in this project. Enable the Wwise integration and restart.")
        world, seed, result = selected_scan()
        if result["issues"]:
            raise RuntimeError("; ".join(result["issues"]))
        if isinstance(seed, u.Volume):
            raise RuntimeError("Use an empty seed Actor; existing Volumes are never overwritten by this command")
        if result["existing_rooms"]:
            raise RuntimeError("Candidate overlaps existing Room: " + ", ".join(result["existing_rooms"]))
        answer = u.EditorDialog.show_message(
            "Interior Fit candidate",
            "Create the previewed Wwise Room? Inspect green bounds first. This does not create portals, certify walking clearance, or save the map.",
            u.AppMsgType.YES_NO,
            u.AppReturnType.NO,
        )
        if answer != u.AppReturnType.YES:
            return
        with u.ScopedEditorTransaction("Create interior acoustic Room"):
            room = u.InteriorFitLibrary.create_box_volume(
                world,
                cls,
                u.Transform(location=u.Vector(*result["center"]), rotation=u.Rotator(yaw=result["yaw"])),
                u.Vector(*result["half_extent"]),
            )
            if not room:
                raise RuntimeError("Native Room creation failed")
            room.set_actor_label("ACOUSTIC_ROOM__" + seed.get_actor_label())
            room.set_folder_path("InteriorFit/Rooms")
            room.tags = list(room.tags) + [u.Name("InteriorFitVolume")]
            configure_wwise_room(room)
            u.get_editor_subsystem(u.EditorActorSubsystem).set_selected_level_actors([room])
    except Exception as error:
        if room:
            u.get_editor_subsystem(u.EditorActorSubsystem).destroy_actor(room)
        u.log_error("Interior Fit: " + str(error))


def fit_polygon_selected():
    from .polygon_editor import selected

    selected()


def merge_selected_rooms():
    from .rooms.merge import selected

    selected()


def fit_stair_selected():
    from .polygon_editor import selected
    from .stair_scan import scan

    selected(scan)


def fit_lake_geometry():
    from .surface_geometry import selected

    selected("lake")


def fit_river_geometry():
    from .surface_geometry import selected

    selected("river")


def fit_area_geometry():
    from .surface_geometry import selected

    selected("area")


def fit_floor_selected():
    from .floor_rooms import selected

    selected()


def fit_view_room():
    from .viewport_fit import run

    run("room")


def fit_view_stair():
    from .viewport_fit import run

    run("stair")


def fit_view_floor():
    from .viewport_fit import run

    run("floor")


def accept_boundary_review():
    from .boundary_review import apply_selected
    apply_selected()
