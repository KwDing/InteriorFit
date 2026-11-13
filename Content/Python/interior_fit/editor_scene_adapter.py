"""Read editor scene data and configure Wwise Room/Portal components."""

from __future__ import annotations

from enum import IntEnum

import unreal as u

from .load_project_options import load_project_options


class HitResultField(IntEnum):
    """Fields used from HitResult.to_tuple(), ordered by BreakHitResult."""

    BLOCKING_HIT = 0
    IMPACT_POINT = 5
    IMPACT_NORMAL = 7
    HIT_ACTOR = 9
    HIT_COMPONENT = 10
    HIT_ITEM = 13


def acoustic_types():
    classes = (
        getattr(u, "AkSpatialAudioVolume", None),
        getattr(u, "AkAcousticPortal", None),
    )
    return tuple(cls for cls in classes if cls is not None)


def show_error(error: Exception | str) -> None:
    message = str(error)
    u.log_error(message)
    u.EditorDialog.show_message("Interior Fit", message, u.AppMsgType.OK)


def room_volumes():
    cls = getattr(u, "AkSpatialAudioVolume", None)
    return [
        a
        for a in u.get_editor_subsystem(
            u.EditorActorSubsystem
        ).get_all_level_actors()
        if cls and isinstance(a, cls)
    ]


def trace(world, start, end, ignored):
    hit = u.SystemLibrary.line_trace_single_by_profile(
        world,
        u.Vector(*start),
        u.Vector(*end),
        "Pawn",
        True,
        ignored,
        u.DrawDebugTrace.NONE,
        True,
    )
    if not hit:
        return None
    fields = hit.to_tuple()
    if not fields[HitResultField.BLOCKING_HIT]:
        return None
    actor = fields[HitResultField.HIT_ACTOR]
    component = fields[HitResultField.HIT_COMPONENT]
    return {
        "point": list(fields[HitResultField.IMPACT_POINT].to_tuple()),
        "normal": list(fields[HitResultField.IMPACT_NORMAL].to_tuple()),
        "actor": actor.get_name() if actor else None,
        "component": component.get_name() if component else None,
        "instance": fields[HitResultField.HIT_ITEM],
    }


def configure_wwise_room(room):
    options = load_project_options().get("wwise", {})
    component = room.get_editor_property("room")
    component.set_editor_property("enable", True)
    component.set_editor_property(
        "wall_occlusion", float(options.get("wall_occlusion", 0.45))
    )
    component.set_editor_property(
        "priority", float(options.get("priority", 20.0))
    )
    late = room.get_editor_property("late_reverb")
    late.set_editor_property("auto_assign_aux_bus", False)
    bus = options.get("aux_bus_name", "")
    late.set_editor_property("enable", bool(bus))
    if bus:
        late.set_editor_property("aux_bus_name", bus)
        late.set_editor_property(
            "send_level", float(options.get("send_level", 1.0))
        )
    room.get_editor_property("surface_reflector_set").set_editor_property(
        "enable_surface_reflectors", False
    )
