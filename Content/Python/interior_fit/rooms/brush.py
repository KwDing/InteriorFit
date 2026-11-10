"""Build native Wwise brushes from fitted geometry in the local floor frame."""

import unreal as u


def _append_clipped_sphere(mesh, result):
    radius = result["radius"]
    primitives = u.GeometryScript_Primitives
    settings = u.GeometryScriptPrimitiveOptions()
    center = u.Vector(*result["sphere_center"])
    primitives.append_sphere_lat_long(mesh, settings, u.Transform(location=center), radius, 20, 40)
    cutter = u.DynamicMesh()
    primitives.append_box(
        cutter,
        settings,
        u.Transform(location=u.Vector(center.x, center.y, -4 * radius)),
        4 * radius,
        4 * radius,
        4 * radius,
    )
    u.GeometryScript_MeshBooleans.apply_mesh_boolean(
        mesh,
        u.Transform(),
        cutter,
        u.Transform(),
        u.GeometryScriptBooleanOperation.SUBTRACT,
        u.GeometryScriptMeshBooleanOptions(),
    )


def _append_profile(mesh, result, profile=None):
    sections = result["sections"]
    chain = []
    for index, ordered in ((2, sections), (3, reversed(sections))):
        for row in ordered:
            ends = row[:2] if index == 2 else row[1::-1]
            for x in ends:
                point = (x, row[index])
                if not chain or chain[-1] != point:
                    chain.append(point)
    # Flat consecutive tread/roof runs share a line; intermediate vertices
    # cannot change occupancy and need no cap triangles.
    chain = [v for i, v in enumerate(chain)
             if (v[0]-chain[i-1][0])*(chain[(i+1) % len(chain)][1]-v[1]) !=
                (v[1]-chain[i-1][1])*(chain[(i+1) % len(chain)][0]-v[0])]
    low, high = result["lateral"]
    direction = u.Vector(0, 1, 0) if result["axis"] else u.Vector(1, 0, 0)
    rot = u.MathLibrary.make_rot_from_xy(direction, u.Vector(0, 0, 1))
    offset = u.Vector(low, 0, 0) if result["axis"] else u.Vector(0, high, 0)
    from .prism_mesh import append
    append(mesh,[u.Vector2D(*p) for p in (profile or chain)],high-low,u.Transform(location=offset, rotation=rot))
    return len(profile or chain)


def prepare_room(result, approval=None):
    """Prepare the candidate in memory before displaying the authoring confirmation."""
    options = u.GeometryScriptCreateNewVolumeFromMeshOptions()
    options.volume_type = u.AkSpatialAudioVolume
    points = result.get("local_outline", result["outline"])
    x, y, floor = points[0]
    polygon = [u.Vector2D(px - x, py - y) for px, py, _ in points]
    mesh = u.DynamicMesh()
    options.max_triangles = max(250, len(points) * 4)
    model = result.get("model")
    prism_sides = None
    pivot = result["outline"][0]
    if "triangles" in result or model in ("stepped_heightfield", "stair_layers"):
        from ..room_height import surface_buffers

        vertices, triangles = ((result["vertices"], result["triangles"])
                               if "triangles" in result else surface_buffers(result))
        buffers = u.GeometryScriptSimpleMeshBuffers()
        buffers.vertices = [u.Vector(*v) for v in vertices]
        buffers.triangles = [u.IntVector(*t) for t in triangles]
        u.GeometryScript_MeshEdits.append_buffers_to_mesh(mesh, buffers)
        pivot = result["origin"]
        options.max_triangles = len(triangles)
    elif model == "strip_profile":
        prism_sides = _append_profile(mesh, result)
        pivot = result["origin"]
    elif model == "floor_clipped_sphere":
        _append_clipped_sphere(mesh, result)
        pivot = result["origin"]
        options.max_triangles = 2000
    else:
        prism_sides = len(polygon)
        from .prism_mesh import append
        append(mesh, polygon, result["roof"] - floor)
    limit = None
    if result.get("authoring_budget"):
        from .mesh_adoption import select_mesh
        mesh, limit = select_mesh(mesh, result, result["authoring_budget"],prism_sides,approval)
        options.max_triangles = mesh.get_triangle_count()
    transform = u.Transform(location=u.Vector(*pivot))
    if "axis_z" in result:
        rotation = u.MathLibrary.make_rot_from_zx(
            u.Vector(*result["axis_z"]), u.Vector(*result["axis_x"]))
        transform = u.Transform(location=u.Vector(*pivot), rotation=rotation)
    import json
    audit = json.loads(u.InteriorFitLibrary.audit_room_mesh(mesh))
    result['mesh_audit'] = audit
    if not audit.get('valid'):
        raise ValueError('Room 网格重合／闭合检查未通过：'+json.dumps(audit,ensure_ascii=False))
    return mesh, transform, options, limit


def create_room(world, result, label, approval=None, prepared=None):
    reviewed_mesh = prepared is not None
    mesh, transform, options, limit = prepared or prepare_room(result, approval)
    if result.get('preview_required') and not reviewed_mesh:
        raise ValueError('该结果已自动重建，请从单个 Room 的最终预览检查并采纳。')
    values = u.GeometryScript_NewAssetUtils.create_new_volume_from_mesh(
        mesh, world, transform, label, options)
    volume = next((v for v in values if isinstance(v, u.AkSpatialAudioVolume)), None)
    if not volume:
        raise ValueError("Unreal could not build the polygon brush")
    if limit:
        try:
            cooked = u.DynamicMesh()
            u.GeometryScript_SceneUtils.copy_mesh_from_component(volume.get_component_by_class(u.BrushComponent),
                cooked,u.GeometryScriptCopyMeshFromComponentOptions(),False)
            acoustic_limit = approval["ceiling"] if approval else limit
            actual = u.InteriorFitLibrary.count_brush_triangles(volume)
            if not 4 <= actual <= acoustic_limit:
                raise ValueError(f"实际声学三角形数 {actual} 超出预算或无有效几何（上限 {acoustic_limit}）。")
            if not 4 <= cooked.get_triangle_count() <= limit:
                raise ValueError(f"实际 Brush 超出 {limit} 面预算或无法读取，请分区后重试")
        except Exception:
            u.get_editor_subsystem(u.EditorActorSubsystem).destroy_actor(volume)
            raise
    if "seed" in result and (limit or result.get("model") in ("ellipsoid_cap", "ridge_prism", "strip_profile", "wall_plane_prism")):
        brush = volume.get_component_by_class(u.BrushComponent)
        seed = u.Vector(*result["seed"])
        distance, _ = brush.get_closest_point_on_collision(seed)
        if not 0 <= distance < 0.1:
            u.InteriorFitLibrary.refresh_volume_collision(volume)
            distance, _ = brush.get_closest_point_on_collision(seed)
        if not 0 <= distance < 0.1:
            u.get_editor_subsystem(u.EditorActorSubsystem).destroy_actor(volume)
            raise ValueError(
                "Generated brush collision does not contain the seed; try another interior position")
    volume.set_actor_label(label)
    return volume
