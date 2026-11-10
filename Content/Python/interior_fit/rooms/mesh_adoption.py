"""Accept the cheapest closed candidate that stays close to the measured source."""
import math
import unreal as u
from .room_budget import HEIGHT_MODELS, deep_notch, limits, stair_ramp

queries = u.GeometryScript_MeshQueries


def _weld(mesh):
    if not queries.get_is_closed_mesh(mesh):
        u.GeometryScript_MeshRepair.weld_mesh_edges(mesh,u.GeometryScriptWeldEdgesOptions())


def _outline_error(ring, candidate):
    """Compare both directions, including edge interiors where a chord can bridge a notch."""
    def distance(p, a, b):
        dx,dy = b[0]-a[0], b[1]-a[1]
        t = ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1.e-12,dx*dx+dy*dy)
        t = max(0,min(1,t))
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
    worst = 0
    for source,target in ((ring,candidate),(candidate,ring)):
        edges = list(zip(target,target[1:]+target[:1]))
        for a,b in zip(source,source[1:]+source[:1]):
            for t in (0,0.25,0.5,0.75):
                p = (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
                worst = max(worst,min(distance(p,c,d) for c,d in edges))
    return worst


def _thin_ring(ring, n):
    points = list(ring)
    while len(points)>n:
        def corner_area(i):
            a,b,c = points[i-1],points[i],points[(i+1)%len(points)]
            return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
        points.pop(min(range(len(points)),key=corner_area))
    return points


class BoundaryReview(ValueError):
    """Candidate passed the structural checks and exceeded only the planar error threshold."""
    def __init__(self, info):
        self.info = info
        super().__init__(f"候选 {info['limit']} 面，边界偏差 {info['error']:.2f} cm，容许 {info['tolerance']:.2f} cm。")


def _reduced_outline(ring, limit, model):
    n = (limit+4)//4
    concave = deep_notch(ring)
    pts = (_thin_ring(ring,n) if len(ring)<=180 and (concave or len(ring)<18 or model=="connected_polygon")
           else [ring[i*len(ring)//n] for i in range(n)])
    def area(poly):
        return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(poly,poly[1:]+poly[:1])))
    if area(pts) > 1:
        scale = 1 if concave else math.sqrt(area(ring)/area(pts))
        cx,cy = (sum(p[k] for p in pts)/n for k in (0,1))
        outline = [(cx+(p[0]-cx)*scale,cy+(p[1]-cy)*scale) for p in pts]
        from ..spline_contour import validate_simple_outline
        try:
            validate_simple_outline(outline)
        except ValueError:
            return None
        return outline


def _candidate(source, result, limit):
    mesh = u.DynamicMesh()
    ring = result.get("local_outline", [])
    if result.get("model") == "strip_profile" and limit >= 20:
        ramp = stair_ramp(result["sections"])
        if ramp:
            from .brush import _append_profile
            _append_profile(mesh,result,ramp)
            _weld(mesh)
            return mesh, 20, 0  # stair_ramp checked the vertical error on every tread.
    if result.get("model") in {"circular_prism","wall_plane_prism","connected_polygon"} and len(ring) >= 5:
        # Maintain vertical walls. Balancing footprint area avoids a consistently
        # undersized inscribed polygon. The 3D checks below still apply.
        outline = _reduced_outline(ring, limit, result["model"])
        if outline:
            n = len(outline)
            poly = [u.Vector2D(x-ring[0][0],y-ring[0][1]) for x,y in outline]
            from .prism_mesh import append
            append(mesh,poly,result["roof"]-ring[0][2])
            _weld(mesh)
            u.GeometryScript_MeshSimplification.apply_simplify_to_planar(mesh,u.GeometryScriptPlanarSimplifyOptions())
            return mesh, 4*n-4, _outline_error(ring,outline)
    u.GeometryScript_MeshEdits.append_mesh(mesh,source,u.Transform())
    u.GeometryScript_MeshSimplification.apply_simplify_to_triangle_count(
        mesh,limit,u.GeometryScriptSimplifyMeshOptions())
    return mesh, mesh.get_triangle_count(), None


def _context(mesh, result, config):
    _weld(mesh)
    u.GeometryScript_MeshSimplification.apply_simplify_to_planar(mesh,u.GeometryScriptPlanarSimplifyOptions())
    bounds = queries.get_mesh_bounding_box(mesh)
    diagonal_cm = (bounds.max-bounds.min).length()
    _, volume = queries.get_mesh_volume_area(mesh)
    model = result.get("model")
    levels = limits(model, result.get("local_outline", []), abs(volume)/1e6, diagonal_cm/100, config)
    tolerance = diagonal_cm*config["boundary_fraction"]
    if model in HEIGHT_MODELS:
        tolerance = min(6, tolerance)  # Preserve differences between neighbouring steps.
    elif deep_notch(result.get("local_outline",[])):
        tolerance = min(15, tolerance)
    return levels, volume, tolerance


def select_mesh(mesh, result, config, prism_sides, approval=None):
    if "triangle_budget" in result:
        return mesh, result["triangle_budget"]
    levels, volume, tolerance = _context(mesh,result,config)
    model = result.get("model")
    best_review = None
    ceiling = levels[-1]
    # Measured long walls already express the fitted shape. Reserve the actual
    # class ceiling for BSP splits rather than deleting another wall corner.
    if (result.get("straightened") or result.get("verified_wall_planes")) and mesh.get_triangle_count() <= ceiling:
        return mesh, ceiling
    deep = deep_notch(result.get("local_outline",[]))
    # Reserve one perimeter vertex for BSP splitting in a manually reviewed deep notch.
    trial_levels = tuple(levels) + ((44,) if deep and ceiling == 48 else ())
    for limit in trial_levels:
        if mesh.get_triangle_count() <= limit or (prism_sides and 4*prism_sides-4 <= limit):
            return mesh, limit
        candidate, count, planar_error = _candidate(mesh, result, limit)
        if not 4 <= count <= limit or not queries.get_is_closed_mesh(candidate):
            continue
        _, new_volume = queries.get_mesh_volume_area(candidate)
        if abs(new_volume-volume) > abs(volume)*config["max_volume_change"]:
            continue
        if planar_error is not None:
            if planar_error <= tolerance:
                return candidate, limit
            if model in {"circular_prism","wall_plane_prism","connected_polygon"}:
                outline = _reduced_outline(result["local_outline"],limit,model)
                if deep and ceiling == 48 and limit == ceiling:
                    continue
                info = dict(limit=limit, ceiling=ceiling, outline=outline, error=planar_error, tolerance=tolerance)
                if approval and approval == info:
                    return candidate, limit
                rank = (planar_error, abs(new_volume-volume), limit)
                if best_review is None or rank < best_review[0]:
                    best_review = (rank,info)
            continue
        distances = u.GeometryScript_MeshComparison.measure_distances_between_meshes(
            mesh,candidate,u.GeometryScriptMeasureMeshDistanceOptions())
        if distances[-4] <= tolerance:
            return candidate, limit
    if best_review:
        from .mesh_review import simplify_for_review
        replacement = simplify_for_review(mesh,result,ceiling,volume,config)
        if replacement:
            return replacement, ceiling
        raise BoundaryReview(best_review[1])
    raise ValueError(f"{model} 在 {levels[-1]} 个三角形内未通过边界验收；请分区制作或关闭编辑器预算重新审核。")
