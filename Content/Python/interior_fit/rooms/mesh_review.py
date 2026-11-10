"""Generate a finished UE-decimated review mesh when prism reduction is refused."""
import unreal as u
from .room_budget import deep_notch


def simplify_for_review(source, result, ceiling, volume, config):
    # This branch addresses compact planar concavities. Curves, tall profiles,
    # and deep multi-arm rooms retain their existing specialized paths.
    ring = result.get('local_outline',[])
    if result.get('model')!='wall_plane_prism' or len(ring)>24 or deep_notch(ring):
        return None
    mesh = u.DynamicMesh()
    u.GeometryScript_MeshEdits.append_mesh(mesh,source,u.Transform())
    options = u.GeometryScriptSimplifyMeshOptions()
    options.method = u.GeometryScriptRemoveMeshSimplificationType.STANDARD_QEM
    # QEM can tilt formerly coplanar faces. BSP conversion may split these
    # again; reserve two triangles instead of raising the final Room budget.
    target = max(4, ceiling-2)
    u.GeometryScript_MeshSimplification.apply_simplify_to_triangle_count(mesh,target,options)
    queries = u.GeometryScript_MeshQueries
    if not 4 <= mesh.get_triangle_count() <= ceiling or not queries.get_is_closed_mesh(mesh):
        return None
    _, new_volume = queries.get_mesh_volume_area(mesh)
    change = abs(new_volume-volume)/max(abs(volume),1)
    if change>config['max_volume_change']:
        return None
    result.update(preview_required=True,mesh_review=dict(method='UE Standard QEM',
        triangles=mesh.get_triangle_count(),volume_change=change,bsp_reserve=ceiling-target))
    return mesh
