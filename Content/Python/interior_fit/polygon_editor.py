"""Editor driver for cancellable, frame-batched contour fitting."""

import json
import time
from pathlib import Path

import unreal as u
from . import room_contour

from .rooms.brush import create_room

_active = None
_last_stats = {}


def last_scan_stats():
    return dict(_last_stats)


def _setup(seed, scanner, protected=None):
    subsystem = u.get_editor_subsystem(u.UnrealEditorSubsystem)
    world = subsystem.get_editor_world()
    if subsystem.get_game_world() or seed.get_world() != world:
        raise ValueError("Select an editor-world seed outside PIE")
    from .editor import acoustic_types
    from .rooms import room_budget, budget_cap, scene
    from . import stair_scan
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    ignored = [a for a in actors.get_all_level_actors() if isinstance(a, acoustic_types())]
    policy = room_budget.settings()
    args = {}
    if scanner is room_contour.scan:
        budget = scene.project_options().get("ellipsoid_triangle_budget")
        if budget is not None:
            explicit = budget_cap.validate(budget)
            args["triangle_budget"] = dict(policy, cap_max=explicit) if policy else explicit
        elif policy:
            args["triangle_budget"] = policy
    origin = seed.get_actor_location()
    return dict(subsystem=subsystem,world=world,ignored=ignored,origin=origin,policy=policy,protected=list(protected or []),
                budget_profile='stairwell' if scanner is stair_scan.scan else None,
                scan=scanner(list(origin.to_tuple()), **args))


def _stopped(stats):
    global _active, _last_stats
    _active, _last_stats = None, stats


def start(seed, done, failed, scanner=room_contour.scan, protected=None):
    global _active, _last_stats
    if _active is not None:
        raise ValueError("A contour scan is already running")
    _last_stats = {}
    started = time.perf_counter()
    from .scan_runner import ScanRunner
    runner = ScanRunner(seed,_setup(seed,scanner,protected),done,failed,_stopped,started)
    runner.begin()
    _active = runner


def review_result(seed, result):
    from .editor import room_volumes, configure_wwise_room

    world = seed.get_world()
    path = Path(u.Paths.project_saved_dir()) / "InteriorFit"
    path.mkdir(parents=True, exist_ok=True)
    (path / "last_polygon_fit.json").write_text(json.dumps(result, indent=2))
    from .rooms.mesh_adoption import BoundaryReview
    from .rooms.brush import prepare_room
    from . import boundary_review
    label = "InteriorFit_" + seed.get_actor_label()
    try:
        prepared = prepare_room(result) if result.get("authoring_budget") else None
    except BoundaryReview as rejected:
        boundary_review.show(world,result,label,rejected.info)
        u.log_warning(str(rejected)+" 已显示最终候选；检查后可采纳或删除预览。")
        return
    if result.get('preview_required'):
        boundary_review.show_final(world,result,label,prepared or prepare_room(result))
        return
    points = [u.Vector(x, y, z + 10) for x, y, z in result["outline"]]
    if result["model"] == "stair_layers":
        ox, oy, oz = result["origin"]
        step = result["step_cm"]
        for i, j, lo, hi in result["height_cells"]:
            p = u.Vector(ox + i * step, oy + j * step, oz + lo + 2)
            u.SystemLibrary.draw_debug_line(world, p, p + u.Vector(0, 0, 10), u.LinearColor(0, 1, 0, 1), 12, 2)
    else:
        u.InteriorFitLibrary.draw_spline_preview(world, points, True, False)
    if any(u.InteriorFitLibrary.contains_point(v, seed.get_actor_location()) for v in room_volumes()):
        u.log_warning("An existing Room covers this seed. Showing preview only.")
        return
    from .room_review_text import build
    message = build(world,result,points)
    if u.EditorDialog.show_message("Interior Fit", message, u.AppMsgType.YES_NO) == u.AppReturnType.YES:
        from .room_comparison import compare_before_create, finish_report

        points, report = compare_before_create(seed, result)
        with u.ScopedEditorTransaction("Create polygon Room"):
            room = create_room(world, result, label, prepared=prepared)
            configure_wwise_room(room)
        finish_report(room, points, report)


def selected(scanner=room_contour.scan):
    actors = u.get_editor_subsystem(u.EditorActorSubsystem).get_selected_level_actors()
    if len(actors) != 1:
        raise ValueError("Select one seed inside the room")
    seed = actors[0]
    start(seed, lambda result: review_result(seed, result), u.log_error, scanner)
