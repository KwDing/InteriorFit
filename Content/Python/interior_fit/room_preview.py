"""Preview the finished mesh, after testing its temporary native Brush collision."""
import json
import unreal as u
from .rooms.frame import cross, dot, unit


def feature_graph(mesh):
    """Keep creases and boundary edges; hide coplanar triangulation diagonals."""
    normals = {}
    for index in range(mesh.get_triangle_count()):
        values = u.GeometryScript_MeshQueries.get_triangle_positions(mesh,index)
        vertices = [tuple(round(v,5) for v in p.to_tuple()) for p in values if isinstance(p,u.Vector)]
        if len(vertices)!=3:
            continue
        a,b,c = vertices
        normal = cross(tuple(y-x for x,y in zip(a,b)),tuple(y-x for x,y in zip(a,c)))
        if dot(normal,normal)<1e-12:
            continue
        for a,b in zip(vertices,vertices[1:]+vertices[:1]):
            normals.setdefault(tuple(sorted((a,b))),[]).append(unit(normal))
    graph = {}
    for (a,b),faces in normals.items():
        if len(faces)==2 and dot(faces[0],faces[1])>0.99999:
            continue
        graph.setdefault(a,set()).add(b)
        graph.setdefault(b,set()).add(a)
    return graph


def wire_points(mesh, transform):
    """Walk doubled mesh edges so one polyline has no invented connecting edges."""
    graph = feature_graph(mesh)
    if not graph:
        raise ValueError('Final candidate has no drawable edges')
    root = next(iter(graph))
    walked, seen = [root], set()

    def visit(a):
        for b in sorted(graph[a]):
            edge = tuple(sorted((a,b)))
            if edge not in seen:
                seen.add(edge)
                walked.append(b)
                visit(b)
                walked.append(a)

    visit(root)
    if len(seen)*2 != sum(len(neighbors) for neighbors in graph.values()):
        raise ValueError('Final candidate has disconnected preview surfaces')
    if len(walked)>256:
        raise ValueError('Final candidate exceeds preview edge budget')
    return [u.MathLibrary.transform_location(transform,u.Vector(*p)).to_tuple() for p in walked]


def create(world, result, label, prepared):
    from .rooms.brush import create_room
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    room = create_room(world,result,'QA_FinalPreviewValidation',prepared=prepared)
    try:
        count = u.InteriorFitLibrary.count_brush_triangles(room)
        # No permanent Room is authored during this validation.
        points = wire_points(prepared[0],prepared[1])
    finally:
        actors.destroy_actor(room)
    preview = u.InteriorFitLibrary.create_surface_preview(world,json.dumps(dict(
        shape='RoomCandidate',sources=[],label=f'{label}__{count}tri',points=points)))
    if not preview:
        raise ValueError('Cannot display the final room mesh')
    return preview,count
