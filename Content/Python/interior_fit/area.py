"""Portable surface authoring. Source geometry stays untouched; previews are line batches."""

import json
import math
import unreal as u
from interior_fit import editor


def surface_actor(actor):
    for _ in range(8):
        meshes = [
            c
            for c in actor.get_components_by_class(u.StaticMeshComponent)
            if c.static_mesh and not c.static_mesh.get_path_name().startswith("/Engine/EditorMeshes/")
        ]
        if meshes or "Landscape" in actor.get_class().get_name():
            return actor
        actor = actor.get_attach_parent_actor()
        if not actor:
            break
    raise RuntimeError("No surface mesh on this actor or its parents. Select the actual lake/snow surface.")


def sample_selected(options_override=None, sources_override=None):
    world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
    if u.get_editor_subsystem(u.UnrealEditorSubsystem).get_game_world():
        raise RuntimeError("Exit PIE before area authoring")
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    selected = list(sources_override) if sources_override is not None else list(actors.get_selected_level_actors())
    sources = []
    for item in selected:
        source = surface_actor(item)
        if source not in sources:
            sources.append(source)
    sources.sort(key=lambda a: a.get_path_name())
    if not sources:
        raise RuntimeError("Select lake/surface mesh actors or landscape components first")
    if any(isinstance(a, (u.Volume, u.InteriorFitArea)) for a in sources):
        raise RuntimeError("Select source surface actors, not Rooms or existing areas")
    options = {"cell_cm": 50.0, "above_cm": 200.0, "below_cm": 500.0, "exclude_covered": True}
    options.update(editor.project_options().get("area", {}))
    options.update(options_override or {})
    for key in ("cell_cm", "above_cm", "below_cm"):
        if not isinstance(options[key], (int, float)) or not math.isfinite(options[key]) or options[key] < 0:
            raise RuntimeError("Invalid area option: " + key)
    data = json.loads(u.InteriorFitLibrary.sample_area_surface(sources, options["cell_cm"], options["exclude_covered"]))
    if "error" in data:
        raise RuntimeError(data["error"])
    data["above_cm"] = options["above_cm"]
    data["below_cm"] = options["below_cm"]
    data["sources"] = [a.get_path_name() for a in sources]
    return world, actors, sources, data
