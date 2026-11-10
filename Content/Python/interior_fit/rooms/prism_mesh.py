"""Closed concave extrusion with explicit caps and shared side-ring vertices."""
import unreal as u


def append(mesh, polygon, height, transform=None):
    from .triangulate import prism_buffers
    vertices,triangles=prism_buffers([(p.x,p.y) for p in polygon],height)
    pose=transform or u.Transform()
    buffers=u.GeometryScriptSimpleMeshBuffers()
    buffers.vertices=[u.MathLibrary.transform_location(pose,u.Vector(*v)) for v in vertices]
    # UE's volume conversion uses clockwise front faces, opposite to the
    # conventional CCW winding used by the engine-independent triangulator.
    buffers.triangles=[u.IntVector(a,c,b) for a,b,c in triangles]
    return u.GeometryScript_MeshEdits.append_buffers_to_mesh(mesh,buffers)
