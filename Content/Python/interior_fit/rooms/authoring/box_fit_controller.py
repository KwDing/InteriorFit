"""Preview and create box Rooms from the editor selection."""

import json
from pathlib import Path

import unreal as u

from ...editor_scene_adapter import (
    acoustic_types,
    configure_wwise_room,
    room_volumes,
    show_error,
    trace,
)
from ...load_project_options import load_project_options
from ..fitting.box import DEFAULTS, scan

# Refresh UI and check cancellation between groups of synchronous rays.
PROGRESS_RAY_INTERVAL = 64


def existing_rooms(world, result):
    """
    Report existing Wwise brush containment without a Wwise compile-time
    dependency.
    """
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
        a
        for a in actors.get_all_level_actors()
        if isinstance(a, acoustic_types()) or "InteriorFitVolume" in a.tags
    ]
    if actor not in ignored:
        ignored.append(actor)
    settings = dict(DEFAULTS)
    settings.update(load_project_options().get("scan", {}))
    with u.ScopedSlowTask(0, "扫描盒形 Room") as progress:
        progress.make_dialog_delayed(0.5, True)
        ray_count = 0

        def trace_with_progress(world, start, end, ignored):
            nonlocal ray_count
            if ray_count % PROGRESS_RAY_INTERVAL == 0:
                progress.enter_progress_frame(0)
                if progress.should_cancel():
                    raise RuntimeError("已取消盒形 Room 扫描。")
            ray_count += 1
            return trace(world, start, end, ignored)

        result = scan(
            world,
            list(actor.get_actor_location().to_tuple()),
            actor.get_actor_rotation().yaw,
            ignored,
            settings,
            trace=trace_with_progress,
        )
    result.update(map=world.get_path_name(), actor=actor.get_path_name())
    result["existing_rooms"] = existing_rooms(world, result)
    path = (
        Path(u.Paths.project_saved_dir()) / "InteriorFit/selected_preview.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if "center" in result:
        color = (
            u.LinearColor(1, 0, 0, 1)
            if result["issues"]
            else u.LinearColor(0, 1, 0, 1)
        )
        result["foreground_preview"] = u.InteriorFitLibrary.draw_preview(
            world,
            u.Transform(
                location=u.Vector(*result["center"]),
                rotation=u.Rotator(yaw=result["yaw"]),
            ),
            u.Vector(*result["half_extent"]),
            color,
        )
    else:
        u.InteriorFitLibrary.draw_preview(
            world, u.Transform(), u.Vector(0, 0, 0), u.LinearColor()
        )
    status = (
        "; ".join(result["issues"]) or "Ready: green candidate box (5 minutes)"
    )
    status += " | Existing Rooms: " + (
        ", ".join(result["existing_rooms"]) or "none"
    )
    u.log_warning("Interior Fit preview: " + status) if result[
        "issues"
    ] else u.log("Interior Fit preview: " + status)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return world, actor, result


def preview_selected() -> None:
    try:
        _, _, result = selected_scan()
        status = (
            "Cannot create: " + ("; ".join(result["issues"]))
            if result["issues"]
            else "Ready: green box shows fitted interior."
        )
        status += "\nExisting Rooms: " + (
            ", ".join(result["existing_rooms"]) or "none"
        )
        if result["existing_rooms"]:
            status += (
                "\n\nCreation is blocked to avoid duplicate Rooms.\n"
                "The fit was calculated from scene geometry."
            )
        if "center" in result:
            status += "\nCenter (cm): " + ", ".join(
                f"{v:.1f}" for v in result["center"]
            )
            status += "\nSize (cm): " + ", ".join(
                f"{v * 2:.1f}" for v in result["half_extent"]
            )
        status += (
            "\n\nThe preview lasts 5 minutes or until another preview "
            "replaces it.\n"
            "The preview leaves the map untouched."
        )
        u.EditorDialog.show_message(
            "Interior Fit Preview", status, u.AppMsgType.OK
        )
    except Exception as error:
        show_error(error)


def create_selected() -> None:
    try:
        cls = getattr(u, "AkSpatialAudioVolume", None)
        if cls is None:
            raise RuntimeError(
                "Wwise is not enabled in this project. Enable the Wwise "
                "integration and restart."
            )
        world, seed, result = selected_scan()
        if result["issues"]:
            raise RuntimeError("; ".join(result["issues"]))
        if isinstance(seed, u.Volume):
            raise RuntimeError(
                "Use an empty seed Actor; existing Volumes are never "
                "overwritten by this command"
            )
        if result["existing_rooms"]:
            raise RuntimeError(
                "Candidate overlaps existing Room: "
                + ", ".join(result["existing_rooms"])
            )
        answer = u.EditorDialog.show_message(
            "Interior Fit candidate",
            "Inspect the green bounds before creating the Wwise Room.\n\n"
            "This action only creates the Room. Check walking clearance and "
            "create Portals separately. Save the map when ready.\n\n"
            "Create the previewed Wwise Room?",
            u.AppMsgType.YES_NO,
            u.AppReturnType.NO,
        )
        if answer != u.AppReturnType.YES:
            return
        with u.ScopedEditorTransaction("Create interior acoustic Room"):
            room = u.InteriorFitLibrary.create_box_volume(
                world,
                cls,
                u.Transform(
                    location=u.Vector(*result["center"]),
                    rotation=u.Rotator(yaw=result["yaw"]),
                ),
                u.Vector(*result["half_extent"]),
            )
            if not room:
                raise RuntimeError("Native Room creation failed")
            actors = u.get_editor_subsystem(u.EditorActorSubsystem)
            try:
                label = "ACOUSTIC_ROOM__" + seed.get_actor_label()
                room.set_actor_label(label)
                room.set_folder_path("InteriorFit/Rooms")
                room.set_editor_property(
                    "tags", list(room.tags) + [u.Name("InteriorFitVolume")]
                )
                configure_wwise_room(room)
            except Exception:
                if not actors.destroy_actor(room):
                    u.log_error("无法清理创建失败的 Room：" + room.get_actor_label())
                raise
        actors.set_selected_level_actors([room])
    except Exception as error:
        show_error(error)
