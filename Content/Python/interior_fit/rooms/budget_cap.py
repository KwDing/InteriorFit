"""Turn a measured ellipsoid into a closed, convex room with a fixed triangle budget."""
import math

from .cap_hull import _band_faces, is_convex
from .frame import cross, dot
from .roof_mesh import result


def validate(budget):
    if type(budget) is not int or not 4 <= budget <= 64 or budget % 2:
        raise ValueError("ellipsoid_triangle_budget must be an even integer from 4 to 64")
    return budget


def contains(cap, point):
    """Check a seed against the actual coarse hull, whose corners can cross the fitted ellipse."""
    vertices = cap["vertices"]
    for i,j,k in cap["triangles"]:
        a = vertices[i]
        ab,ac,ap = (tuple(v-u for v,u in zip(p,a)) for p in (vertices[j],vertices[k],point))
        if dot(cross(ab,ac),ap) < -1.e-6:
            return False
    return True


def _levels(vertex_count, cut):
    # A closed triangulated hull has F = 2V - 4. Keep the floor planar.
    if vertex_count < 6:
        return [(vertex_count-1, 0)], True
    if vertex_count < 10:
        bottom = (vertex_count+1)//2
        return [(bottom, 0), (vertex_count-bottom, 0.80)], False
    remaining = vertex_count-1
    count = max(2, round(math.sqrt(remaining/2.7)))
    low = math.asin(-cut)
    angles = [low+(math.pi/2-low)*j/count for j in range(count)]
    weights = [math.cos(angle) for angle in angles]
    sides = [3]*count
    for _ in range(remaining-sum(sides)):
        j = max(range(count),key=lambda i:weights[i]/(sides[i]+0.5))
        sides[j] += 1
    return [(n,(cut+math.sin(angle))/(1+cut)) for n,angle in zip(sides,angles)], True


def _balance_volume(cap, center, radii):
    # Scale in the floor plane only. A coarse inscribed roof otherwise loses
    # a systematic band of air even when the measured ellipsoid is exact.
    cx,cy,cz = center
    a,b,h = radii
    local = [(x-cx,y-cy,z) for x,y,z in cap["vertices"]]
    volume = abs(sum(dot(local[i],cross(local[j],local[k])) for i,j,k in cap["triangles"]))/6
    cut = cz/h
    target = math.pi*a*b*h*(1+cut)**2*(2-cut)/3
    factor = math.sqrt(target/volume)
    return [(cx+x*factor,cy+y*factor,z) for x,y,z in local]


def build(frame, center, radii, theta, budget):
    vertex_count = (validate(budget)+4)//2
    cx,cy,cz = center
    a,b,h = radii
    levels, apex = _levels(vertex_count, cz/h)
    vertices,faces,rings = [],[],[]
    for j,(count,height_fraction) in enumerate(levels):
        z = (cz+h)*height_fraction
        # Equal-area regular polygon balances inward chords and outward corners.
        turn = math.tau/count
        radius = math.sqrt(max(0,1-((z-cz)/h)**2)*turn/math.sin(turn))
        phase = 0.5*j/count
        ring = list(range(len(vertices),len(vertices)+count)),phase
        for i in range(count):
            angle = math.tau*(phase+i/count)
            x,y = a*radius*math.cos(angle), b*radius*math.sin(angle)
            vertices.append((cx+x*math.cos(theta)-y*math.sin(theta),
                             cy+x*math.sin(theta)+y*math.cos(theta), z))
        faces.extend(_band_faces(rings[-1],ring) if rings else [ring[0][::-1]])
        rings.append(ring)
    last = rings[-1][0]
    if apex:
        top = len(vertices)
        vertices.append((cx,cy,cz+h))
        faces.extend((v,last[(i+1)%len(last)],top) for i,v in enumerate(last))
    else:
        faces.append(last)
    cap = result(frame,"ellipsoid_cap",vertices[:levels[0][0]],vertices,faces)
    vertices = _balance_volume(cap,center,radii)
    cap = result(frame,"ellipsoid_cap",vertices[:levels[0][0]],vertices,faces)
    if len(cap["triangles"]) != budget or not is_convex(cap):
        raise ValueError("Could not build a closed convex room at the selected triangle budget")
    cap.update(center=center,radii=radii,yaw_radians=theta,triangle_budget=budget)
    return cap
