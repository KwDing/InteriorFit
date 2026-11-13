"""Start Room scans in the editor and review their results.

ScanRunner advances the fit on Slate ticks and waits for each ray batch before
resuming the scanner. Ending a scan removes its callback and cancels the batch.
"""

import json
import time
from pathlib import Path

import unreal as u
from interior_fit.rooms.scanning import scan_contour as room_contour

from interior_fit.rooms.authoring.create_room_brushes import create_room

_active = None
_last_stats = {}


def last_scan_stats():
    return dict(_last_stats)


def _setup(seed, scanner, protected=None):
    subsystem = u.get_editor_subsystem(u.UnrealEditorSubsystem)
    world = subsystem.get_editor_world()
    if subsystem.get_game_world() or seed.get_world() != world:
        raise ValueError("Select an editor-world seed outside PIE")
    from interior_fit.editor_scene_adapter import acoustic_types
    from interior_fit.load_project_options import load_project_options
    from interior_fit.rooms import room_budget
    from interior_fit.rooms.geometry import (
        mesh_ellipsoid_cap_with_polybudget as budget_cap,
    )
    from interior_fit.floors import scan_stairs as stair_scan

    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    ignored = [
        a
        for a in actors.get_all_level_actors()
        if isinstance(a, acoustic_types())
    ]
    policy = room_budget.settings()
    args = {}
    if scanner is room_contour.scan:
        budget = load_project_options().get("ellipsoid_triangle_budget")
        if budget is not None:
            explicit = budget_cap.validate(budget)
            args["triangle_budget"] = (
                dict(policy, cap_max=explicit) if policy else explicit
            )
        elif policy:
            args["triangle_budget"] = policy
    origin = seed.get_actor_location()
    return dict(
        subsystem=subsystem,
        world=world,
        ignored=ignored,
        origin=origin,
        policy=policy,
        protected=list(protected or []),
        budget_profile="stairwell" if scanner is stair_scan.scan else None,
        scan=scanner(list(origin.to_tuple()), **args),
    )


def _stopped(stats):
    global _active, _last_stats
    _active, _last_stats = None, stats


def start(seed, done, failed, scanner=room_contour.scan, protected=None):
    global _active, _last_stats
    if _active is not None:
        raise ValueError("A contour scan is already running")
    _last_stats = {}
    started = time.perf_counter()
    from interior_fit.scan_runner import ScanRunner

    runner = ScanRunner(
        seed, _setup(seed, scanner, protected), done, failed, _stopped, started
    )
    runner.begin()
    _active = runner


def review_result(seed, result):
    from interior_fit.editor_scene_adapter import (
        room_volumes,
        configure_wwise_room,
    )

    world = seed.get_world()
    path = Path(u.Paths.project_saved_dir()) / "InteriorFit"
    path.mkdir(parents=True, exist_ok=True)
    (path / "last_polygon_fit.json").write_text(json.dumps(result, indent=2))
    from interior_fit.rooms.authoring.select_mesh import BoundaryReview
    from interior_fit.rooms.authoring.create_room_brushes import prepare_room
    from interior_fit.rooms.authoring import review_boundary as boundary_review

    label = "InteriorFit_" + seed.get_actor_label()
    try:
        prepared = (
            prepare_room(result) if result.get("authoring_budget") else None
        )
    except BoundaryReview as rejected:
        boundary_review.show(world, result, label, rejected.info)
        u.log_warning(
            str(rejected) + " 已显示最终候选；检查后可采纳或删除预览。"
        )
        return
    if result.get("preview_required"):
        boundary_review.show_final(
            world, result, label, prepared or prepare_room(result)
        )
        return
    points = [u.Vector(x, y, z + 10) for x, y, z in result["outline"]]
    if result["model"] == "stair_layers":
        ox, oy, oz = result["origin"]
        step = result["step_cm"]
        for i, j, lo, hi in result["height_cells"]:
            p = u.Vector(ox + i * step, oy + j * step, oz + lo + 2)
            u.SystemLibrary.draw_debug_line(
                world,
                p,
                p + u.Vector(0, 0, 10),
                u.LinearColor(0, 1, 0, 1),
                12,
                2,
            )
    else:
        u.InteriorFitLibrary.draw_spline_preview_with_style(
            world,
            points,
            u.InteriorFitSplineClosure.CLOSED,
            u.InteriorFitSplineBudgetStatus.WITHIN_BUDGET,
        )
    if any(
        u.InteriorFitLibrary.contains_point(v, seed.get_actor_location())
        for v in room_volumes()
    ):
        u.log_warning(
            "An existing Room covers this seed. Showing preview only."
        )
        return
    from interior_fit.rooms.authoring.build_review_text import build

    message = build(world, result, points)
    answer = u.EditorDialog.show_message(
        "Interior Fit",
        message,
        u.AppMsgType.YES_NO,
    )
    if answer == u.AppReturnType.YES:
        with u.ScopedEditorTransaction("Create polygon Room"):
            room = create_room(world, result, label, prepared=prepared)
            try:
                configure_wwise_room(room)
            except Exception:
                actors = u.get_editor_subsystem(u.EditorActorSubsystem)
                if not actors.destroy_actor(room):
                    u.log_error("无法清理配置失败的 Room：" + label)
                raise


def selected(scanner=room_contour.scan):
    from interior_fit.editor_scene_adapter import show_error

    try:
        actors = u.get_editor_subsystem(u.EditorActorSubsystem)
        selection = actors.get_selected_level_actors()
        if len(selection) != 1:
            raise ValueError("Select one seed inside the room")
        seed = selection[0]
        start(
            seed,
            lambda result: review_result(seed, result),
            show_error,
            scanner,
        )
    except Exception as error:
        show_error(error)
