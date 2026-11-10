"""Surface boundary extraction with no sound-object or playback dependencies."""

import json
import unreal as u
from .. import area, editor
from ..spline_contour import mesh_outline, simplify_path


def _spline_points(spline):
    """Retain the existing eight samples per curved segment, in world centimetres."""
    count = spline.get_number_of_spline_points()
    if count < 2:
        raise RuntimeError("Source spline needs at least two points")
    segments = count if spline.is_closed_loop() else count - 1
    points = []
    for index in range(segments):
        steps = 1 if spline.get_spline_point_type(index) == u.SplinePointType.LINEAR else 8
        points.extend(
            spline.get_location_at_spline_input_key(index + step / steps, u.SplineCoordinateSpace.WORLD).to_tuple()
            for step in range(steps)
        )
    if not spline.is_closed_loop():
        points.append(spline.get_location_at_spline_point(count - 1, u.SplineCoordinateSpace.WORLD).to_tuple())
    return points


def _lake_points(selected, tolerance):
    sources = []
    for actor in selected:
        source = area.surface_actor(actor)
        if source not in sources:
            sources.append(source)
    sources.sort(key=lambda actor: actor.get_path_name())
    data = json.loads(u.InteriorFitLibrary.get_lake_surface_boundary(sources))
    if "error" in data:
        raise RuntimeError(data["error"])
    return mesh_outline(data["edges"], tolerance), sources[0].get_actor_label(), []


def _seed_points(selected):
    if len(selected) != 1:
        raise RuntimeError("For Line, select one spline or one seed actor; edit the generated path afterwards")
    center, extent = selected[0].get_actor_bounds(False)
    xyz = list(center.to_tuple())
    sizes = extent.to_tuple()
    axis = max(range(3), key=lambda i: sizes[i])
    half = max(sizes[axis], 300)
    a = xyz.copy()
    b = xyz.copy()
    a[axis] -= half
    b[axis] += half
    return [tuple(a), tuple(xyz), tuple(b)], selected[0].get_actor_label(), []


def selected_points(shape, settings=None, selected_override=None):
    """Resolve selection, then delegate extraction without creating audio objects."""
    settings = settings or {}
    tolerance = settings.get(
        "simplification_tolerance_cm", editor.project_options().get("ambient_spline", {}).get("simplify_cm", 30)
    )
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    selected = list(selected_override) if selected_override is not None else list(actors.get_selected_level_actors())
    if not selected:
        raise RuntimeError("Select water mesh actor(s), an existing Spline actor, or an actor as a Line seed")
    splines = [component for actor in selected for component in actor.get_components_by_class(u.SplineComponent)]
    if splines:
        if len(splines) != 1:
            raise RuntimeError("Select exactly one source spline")
        points = _spline_points(splines[0])
        return simplify_path(points, tolerance, shape == "Lake"), selected[0].get_actor_label(), []
    if shape == "Lake":
        return _lake_points(selected, tolerance)
    return _seed_points(selected)
