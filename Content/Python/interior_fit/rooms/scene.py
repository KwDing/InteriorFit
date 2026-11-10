import json
from pathlib import Path
import unreal as u


def project_options():
    path = Path(u.Paths.project_config_dir()) / "InteriorFit.json"
    options = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(options, dict):
        raise ValueError("Config/InteriorFit.json must be a JSON object")
    return options


def acoustic_types():
    return tuple(cls for name in ("AkSpatialAudioVolume", "AkAcousticPortal") if (cls := getattr(u, name, None)))


def room_volumes():
    cls = getattr(u, "AkSpatialAudioVolume", None)
    return [
        a for a in u.get_editor_subsystem(u.EditorActorSubsystem).get_all_level_actors() if cls and isinstance(a, cls)
    ]


def trace(world, start, end, ignored):
    hit = u.SystemLibrary.line_trace_single_by_profile(
        world, u.Vector(*start), u.Vector(*end), "Pawn", True, ignored, u.DrawDebugTrace.NONE, True
    )
    v = hit.to_tuple() if hit else None
    if not v or not v[0]:
        return None
    return {
        "point": list(v[5].to_tuple()),
        "normal": list(v[7].to_tuple()),
        "actor": v[9].get_name() if v[9] else None,
        "component": v[10].get_name() if v[10] else None,
        "instance": v[13],
    }


def configure_wwise_room(room):
    options = project_options().get("wwise", {})
    component = room.get_editor_property("room")
    component.set_editor_property("enable", True)
    component.set_editor_property("wall_occlusion", float(options.get("wall_occlusion", 0.45)))
    component.set_editor_property("priority", float(options.get("priority", 20.0)))
    late = room.get_editor_property("late_reverb")
    late.set_editor_property("auto_assign_aux_bus", False)
    bus = options.get("aux_bus_name", "")
    late.set_editor_property("enable", bool(bus))
    if bus:
        late.set_editor_property("aux_bus_name", bus)
        late.set_editor_property("send_level", float(options.get("send_level", 1.0)))
    room.get_editor_property("surface_reflector_set").set_editor_property("enable_surface_reflectors", False)
