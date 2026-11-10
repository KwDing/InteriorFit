"""Verify a proposed planar room against independent points on its walls and in its air space."""

import math

from .rays import query


def representative_points(points, limit=16):
    """Bound vertical validation after roof connectivity and walls are known.

    Farthest-point sampling spans the measured footprint instead of checking
    every coarse grid column again. Small local height details can be missed;
    this is an authoring approximation, not continuous floor certification.
    """
    remaining = sorted(set(points))
    if len(remaining)<=limit:
        return remaining
    chosen = [min(remaining,key=lambda p:math.hypot(*p))]
    remaining.remove(chosen[0])
    while len(chosen)<limit:
        point = max(remaining,key=lambda p:min(math.dist(p,q) for q in chosen))
        remaining.remove(point)
        chosen.append(point)
    return chosen


def walls_match(frame, ring, roof, fractions=(0.15,0.5,0.85)):
    if len(fractions)<2:
        raise ValueError('At least two independent wall positions are required')
    rays, checks = [], []
    for a,b in zip(ring, ring[1:]+ring[:1]):
        dx,dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx,dy)
        nx,ny = -dy/length, dx/length  # CCW contour: left side is inside.
        for fraction in fractions:
            x,y = a[0]+fraction*dx, a[1]+fraction*dy
            for z in (roof-5, roof-65):
                rays.append((frame.world((x+18*nx,y+18*ny,z)), frame.world((x-18*nx,y-18*ny,z))))
                checks.append((x, y, nx, ny))
    hits = yield from query(rays)
    open_edges = []
    stride = 2*len(fractions)
    for start in range(0,len(hits),stride):
        supported = []
        for hit,(x,y,nx,ny) in zip(hits[start:start+stride],checks[start:start+stride]):
            if not hit:
                supported.append(False)
                continue
            px,py,_ = frame.local(hit[0])
            normal = frame.direction(hit[1])
            supported.append(abs((px-x)*nx+(py-y)*ny) < 4 and normal[0]*nx+normal[1]*ny > 0.995)
        if sum(supported[::2]) < 2:
            return False
        if not any(supported[1::2]):
            if not all(supported[::2]):
                return False
            open_edges.extend(checks[start:start+stride:2])
    # A broad window may occupy every lower sample. Verify the roof terminates
    # at the measured lintel rather than silently closing unexplored interior air.
    rays = [(frame.world((x-45*nx,y-45*ny,roof-22)),frame.world((x-45*nx,y-45*ny,roof+12)))
            for x,y,nx,ny in open_edges]
    if any((yield from query(rays))):
        return False
    return True


def interior_matches(frame, cells, roof):
    points = []
    for x0,x1,y0,y1 in cells:
        for u,v in ((0.5,0.5),(0.2,0.2),(0.2,0.8),(0.8,0.2),(0.8,0.8)):
            x,y = x0+u*(x1-x0), y0+v*(y1-y0)
            points.append((x,y))
    return (yield from check_heights(frame, points, roof))


def check_heights(frame, points, roof):
    rays = []
    for x,y in points:
        mid = frame.world((x,y,roof/2))
        rays.extend([(mid, frame.world((x,y,-12))), (mid, frame.world((x,y,roof+12)))])
    hits = yield from query(rays)
    raised = []
    for floor,ceiling in zip(hits[::2], hits[1::2]):
        if not floor or not ceiling or abs(frame.local(ceiling[0])[2]-roof) > 5:
            return False
        if frame.direction(ceiling[1])[2] > -0.98:
            return False
        x,y,z = frame.local(floor[0])
        if z < -5 or z >= roof/2:
            return False
        if z > 5:
            raised.append((x,y,z))
        elif frame.direction(floor[1])[2] < 0.85:
            return False
    if len(raised) > 3:
        return False
    return not raised or (yield from floor_under_obstacles(frame, raised))


def floor_under_obstacles(frame, raised):
    # Require a real gap: the primitive below must expose the original floor,
    # and the obstruction above must have a downward-facing underside.
    rays = []
    for x, y, top in raised:
        start = frame.world((x, y, 5))
        rays.extend([(start, frame.world((x, y, -12))), (start, frame.world((x, y, top-1)))])
    hits = yield from query(rays)
    for floor, underside in zip(hits[::2], hits[1::2]):
        if not floor or abs(frame.local(floor[0])[2]) > 5 or not underside:
            return False
        if frame.local(underside[0])[2] <= 6 or frame.direction(underside[1])[2] > -0.5:
            return False
    return True
