"""Geometry-only settings and bounded simplification, independent of audio hosts."""
from ..spline_contour import simplify_path


def bounded(points, tolerance, limit, closed):
    if not 3 <= limit <= 256 or not 0 <= tolerance <= 1000:
        raise ValueError('控制点应为 3–256，简化容差应为 0–1000 cm')
    # Raise geometric tolerance rather than dropping arbitrary path samples.
    effective = tolerance
    for _ in range(24):
        result = simplify_path(points, effective, closed)
        if len(result) <= limit:
            if len(result) < (3 if closed else 2):
                raise ValueError('简化后轮廓过小，请降低容差或提高控制点上限')
            return result
        effective = max(1, effective * 1.5)
    raise ValueError('无法在控制点限制内保留轮廓，请提高上限')


def make_draft(method):
    """Show only inputs consumed by this command; retain existing numeric defaults."""
    import unreal as u
    modes = {
        'lake': u.InteriorFitGeometryMethod.LAKE,
        'river': u.InteriorFitGeometryMethod.RIVER,
        'area': u.InteriorFitGeometryMethod.AREA,
    }
    draft = u.new_object(u.InteriorFitGeometrySettings)
    draft.set_editor_property('method', modes[method])
    return draft


def edit(method):
    """Return the confirmed draft values, or None when the author cancels."""
    import unreal as u
    draft = make_draft(method)
    title = {'lake': '湖岸闭合样条', 'river': '河流中心样条', 'area': '地表 Area'}[method]
    options = u.EditorDialogLibraryObjectDetailsViewOptions(show_object_name=False)
    if not u.EditorDialog.show_object_details_view(title + '：设置后生成', draft, options):
        return None
    return {name: draft.get_editor_property(name) for name in
            ('simplification_tolerance_cm', 'maximum_points', 'cell_size_cm')}
