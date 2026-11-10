"""Recover corners from ordered wall hits, including the diagonal sides of a Z."""

import math
from ..spline_contour import _exterior_loop, validate_simple_outline


def _cross(a,b):
    return a[0]*b[1] - a[1]*b[0]


def _ordered_planes(frame, sites, boundary):
    try:
        loop = _exterior_loop(sites)
    except ValueError:
        return []
    planes = []
    for a,b in zip(loop,loop[1:]+loop[:1]):
        dx,dy = b[1]-a[1], a[0]-b[0]
        i = math.floor((a[0]+b[0])/2 - 0.25*dx)
        j = math.floor((a[1]+b[1])/2 - 0.25*dy)
        hit = boundary.get(((i,j),(i+dx,j+dy)))
        if not hit:
            continue
        nx,ny,nz = frame.direction(hit[1])
        if abs(nz) > 0.04:
            return []
        x,y,_ = frame.local(hit[0])
        planes.append((nx,ny,nx*x+ny*y))
    return planes


def _same(a,b):
    return a[0]*b[0]+a[1]*b[1] > 0.99995 and abs(a[2]-b[2]) < 3


def corners(frame, sites, boundary):
    return intersect_runs(_ordered_planes(frame,sites,boundary), 20)


def intersect_runs(planes, limit, min_sine=0.08):
    """Intersect neighboring observed supports in perimeter order."""
    runs = []
    for plane in planes:
        if not runs or not _same(plane,runs[-1]):
            runs.append(plane)
    if len(runs)>1 and _same(runs[0],runs[-1]):
        runs.pop()
    if not 3 <= len(runs) <= limit:
        return None
    ring = []
    for (a,b,d),(e,f,g) in zip(runs[-1:]+runs[:-1],runs):
        determinant = a*f-b*e
        if abs(determinant)<min_sine:
            return None
        ring.append(((d*f-b*g)/determinant,(a*g-d*e)/determinant))
    if sum(_cross(a,b) for a,b in zip(ring,ring[1:]+ring[:1])) <= 0:
        return None
    try:
        validate_simple_outline([(x,y,0) for x,y in ring])
    except ValueError:
        return None
    return ring


def matches_sites(ring, sites, points):
    """Reject missing arms, bridged notches, or corners extrapolated beyond the survey."""
    extent = max(max(abs(a), abs(b)) for a,b in points.values())
    if any(max(abs(x), abs(y)) > extent for x,y in ring):
        return False
    for key,(x,y) in points.items():
        inside = False
        near_edge = False
        for a,b in zip(ring,ring[1:]+ring[:1]):
            dx,dy = b[0]-a[0],b[1]-a[1]
            if max(min(a[0],b[0])-x,x-max(a[0],b[0]),min(a[1],b[1])-y,y-max(a[1],b[1])) <= 4:
                near_edge |= abs(dx*(y-a[1])-dy*(x-a[0])) <= 4*math.hypot(dx,dy)
            if (a[1]>y) != (b[1]>y) and x < a[0]+(y-a[1])*dx/dy:
                inside = not inside
        if not near_edge and inside != (key in sites):
            return False
    return True
