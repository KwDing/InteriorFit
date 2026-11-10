"""Geometry-only authoring for lake shores, river paths and surface areas."""

import hashlib
import json
from .surfaces.river import RING as RING, thin as thin, river_paths


def _set_spline(actor, points, closed):
    """Populate an already-owned actor so the caller can roll back any failure."""
    import unreal as u

    spline = actor.get_component_by_class(u.SplineComponent)
    spline.clear_spline_points(False)
    for i, point in enumerate(points):
        spline.add_spline_point(u.Vector(*point), u.SplineCoordinateSpace.WORLD, False)
        spline.set_spline_point_type(i, u.SplinePointType.LINEAR, False)
    spline.set_closed_loop(closed, True)


def _set_area(actor, data):
    """Editor property changes invalidate the geometry query index."""
    import unreal as u

    actor.modify()
    actor.set_actor_transform(u.Transform(location=u.Vector(*data["origin"])), False, True)
    actor.set_editor_property("surface_cells", [u.Vector(*v) for v in data["cells"]])
    actor.set_editor_property("cell_size", data["cell_size"])
    actor.set_editor_property("height_above_surface", data["above_cm"])
    actor.set_editor_property("depth_below_surface", data["below_cm"])
    if not actor.is_shape_valid():
        raise RuntimeError("生成的 Area 形状无效。")


def _sample_geometry(method, source, settings):
    """Finish sampling and simplification before changing existing results."""
    from . import area
    from .surfaces import boundary
    from .surfaces.geometry_options import bounded

    if method == "lake":
        points, _, _ = boundary.selected_points("Lake", {"simplification_tolerance_cm": 0}, [source])
        paths = [points]
        data = None
    else:
        _, _, _, data = area.sample_selected(
            dict(cell_cm=settings['cell_size_cm'], above_cm=20, below_cm=20, exclude_covered=False), [source]
        )
        paths = river_paths(data) if method == "river" else []
    if method != "area" and not paths:
        raise ValueError("No valid surface paths; existing geometry has been retained")
    paths = [bounded(path, settings['simplification_tolerance_cm'], settings['maximum_points'], method == 'lake')
             for path in paths]
    return paths, data


def _spawn_results(actors, method, source, geometry, key, created):
    """The caller owns every Actor before shape assignment can fail."""
    import unreal as u

    paths, data = geometry
    results = [data] if method == "area" else paths
    for index, result in enumerate(results):
        actor_class = u.InteriorFitArea if method == "area" else u.InteriorFitSplineGuide
        origin = result["origin"] if method == "area" else result[0]
        actor = actors.spawn_actor_from_class(actor_class, u.Vector(*origin))
        if not actor:
            raise RuntimeError("Could not create surface geometry Actor")
        created.append(actor)
        if method == "area":
            _set_area(actor, result)
        else:
            _set_spline(actor, result, method == "lake")
        actor.set_actor_label(f"Fit_{method}_{source.get_actor_label()}_{index + 1}")
        actor.set_folder_path("Surface Fit/Results")
        actor.set_editor_property("tags", [u.Name(key)])


def _replace_results(actors, method, source, geometry):
    import unreal as u

    key = "InteriorFitProof_" + hashlib.sha256((source.get_path_name() + method).encode()).hexdigest()[:20]
    # Only replace exact classes created here, never a host's Area subclass.
    owned_classes = (u.InteriorFitArea.static_class(), u.InteriorFitSplineGuide.static_class())
    previous = [actor for actor in actors.get_all_level_actors()
                if actor.get_class() in owned_classes and actor.actor_has_tag(key)]
    created = []
    with u.ScopedEditorTransaction("Fit surface geometry"):
        try:
            _spawn_results(actors, method, source, geometry, key, created)
        except Exception:
            for actor in created:
                actors.destroy_actor(actor)
            raise
        for actor in previous:
            actors.destroy_actor(actor)
    return created


def fit_geometry(method, source, settings=None):
    """Publish geometry only; audio hosts explicitly copy the confirmed result."""
    import unreal as u

    if method not in ("lake", "river", "area"):
        raise ValueError("Unknown surface geometry method")
    if u.get_editor_subsystem(u.UnrealEditorSubsystem).get_game_world():
        raise ValueError("Exit PIE before fitting")
    settings = settings or dict(simplification_tolerance_cm=20, maximum_points=128, cell_size_cm=40)
    geometry = _sample_geometry(method, source, settings)
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    created = _replace_results(actors, method, source, geometry)
    actors.set_selected_level_actors(created)
    if method == "area":
        # Preview is optional display; the result already owns its sampled cells.
        u.InteriorFitLibrary.draw_area_preview(source.get_world(), json.dumps(geometry[1]))
    return created


def selected(method):
    import unreal as u

    actors = u.get_editor_subsystem(u.EditorActorSubsystem).get_selected_level_actors()
    try:
        if len(actors) != 1:
            raise ValueError("Select one source surface")
        from .surfaces.geometry_options import edit
        settings = edit(method)
        if settings is not None:
            fit_geometry(method, actors[0], settings)
    except Exception as error:
        u.EditorDialog.show_message("Interior Fit", str(error), u.AppMsgType.OK)
