"""Point-for-point comparisons on the same probes for fitted Wwise brush volumes."""

import json
from pathlib import Path
from uuid import uuid4

import unreal as u


def hits(volume, points):
    brush = volume.get_component_by_class(u.BrushComponent)
    indices = []
    for index, point in enumerate(points):
        distance, _ = brush.get_closest_point_on_collision(point)
        if distance < 0:
            raise ValueError("Fitted volume has no queryable brush collision")
        if distance < 0.01:
            indices.append(index)
    return indices


def native_hits(seed, points, shape):
    library = u.InteriorFitLibrary
    world = seed.get_world()
    # Distinct small starting brush lets us detect a failed native fit.
    volume = library.create_box_volume(
        world, u.AkSpatialAudioVolume, u.Transform(location=seed.get_actor_location()), u.Vector(7, 9, 11)
    )
    if not volume:
        raise ValueError("Could not create comparison brush")
    try:
        before = library.get_volume_faces(volume)
        volume.set_editor_property("shape", shape)
        volume.set_editor_property("fit_to_geometry", True)
        if library.get_volume_faces(volume) == before:
            return {"status": "no fitted brush"}
        library.refresh_volume_collision(volume)
        return {"hits": hits(volume, points)}
    finally:
        u.get_editor_subsystem(u.EditorActorSubsystem).destroy_actor(volume)


def compare_before_create(seed, result):
    # A demo fixture may supply a known reference mask. For an ordinary room only
    # agreement between methods can be measured without a separate reference.
    reference = None
    fixture = Path(u.Paths.project_config_dir()) / "InteriorFitReferenceSamples.json"
    level = seed.get_world().get_path_name().partition(".")[0]
    if fixture.exists():
        data = json.loads(fixture.read_text(encoding="utf-8-sig"))
        if level == data["level"]:
            reference = data["seeds"].get(seed.get_actor_label())
    if reference:
        x, y, z0 = reference["origin"]
        points = [
            u.Vector(x + dx, y + dy, z0 + z)
            for z in reference.get("heights", (75, 120, 260))
            for dx in range(-575, 576, 50)
            for dy in range(-575, 576, 50)
        ]
    else:
        xs, ys, _ = zip(*result.get("local_outline", result["outline"]))

        def samples(values):
            low, high = min(values) - 50, max(values) + 50
            return [low + (i + 0.5) * (high - low) / 24 for i in range(24)]

        transform = u.Transform()
        if "axis_z" in result:
            rotation = u.MathLibrary.make_rot_from_zx(u.Vector(*result["axis_z"]), u.Vector(*result["axis_x"]))
            transform = u.Transform(location=u.Vector(*result["origin"]), rotation=rotation)
        points = [
            u.MathLibrary.transform_location(
                transform, u.Vector(x, y, result["floor"] + fraction * (result["roof"] - result["floor"]))
            )
            for fraction in (0.2, 0.5, 0.8)
            for x in samples(xs)
            for y in samples(ys)
        ]
    methods = {}
    for name, mode in [
        ("wwise_aligned", u.AkFitToGeometryMode.ALIGNED_BOX),
        ("wwise_oriented", u.AkFitToGeometryMode.ORIENTED_BOX),
        ("wwise_convex", u.AkFitToGeometryMode.CONVEX_POLYHEDRON),
    ]:
        methods[name] = native_hits(seed, points, mode)
    report = dict(
        level=level,
        seed=seed.get_actor_label(),
        polygon=result,
        points_cm=[p.to_tuple() for p in points],
        methods=methods,
    )
    if reference:
        report["reference_hits"] = reference["reference_hits"]
    return points, report


def finish_report(volume, points, report, folder=None):
    methods = report["methods"]
    methods["interior_fit"] = {"hits": hits(volume, points)}
    for method in methods.values():
        if "hits" not in method:
            continue
        predicted = set(method["hits"])
        method["disagreements_with_interior_fit"] = len(predicted.symmetric_difference(methods["interior_fit"]["hits"]))
        if "reference_hits" in report:
            truth = set(report["reference_hits"])
            method.update(
                tp=len(predicted & truth),
                fp=len(predicted - truth),
                fn=len(truth - predicted),
                tn=len(points) - len(predicted | truth),
            )
    folder = folder if folder is not None else Path(u.Paths.project_saved_dir()) / "InteriorFit"
    path = folder / ("polygon_" + uuid4().hex + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    u.log("Interior Fit comparison: " + str(path))
    return path
