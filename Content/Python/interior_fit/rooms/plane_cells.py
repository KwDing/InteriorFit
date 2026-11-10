"""Bounded 2D wall-line arrangement, retaining concave unions instead of a hull."""
import math
from ..spline_contour import validate_simple_outline


def area(poly):
    return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(poly,poly[1:]+poly[:1]))/2


def clip(poly, plane, sign):
    nx,ny,d = plane
    result = []
    for a,b in zip(poly,poly[1:]+poly[:1]):
        da,db = sign*(nx*a[0]+ny*a[1]-d), sign*(nx*b[0]+ny*b[1]-d)
        if da >= -1.e-7:
            result.append(a)
        if (da < -1.e-7 and db > 1.e-7) or (da > 1.e-7 and db < -1.e-7):
            t = da/(da-db)
            result.append((a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])))
    return result


def partition(planes, extent):
    """At most 16 supports and 160 cells; unknown geometry falls back to scanning."""
    if not 3 <= len(planes) <= 16:
        return []
    cells = [[(-extent,-extent),(extent,-extent),(extent,extent),(-extent,extent)]]
    for plane in planes:
        cells = [part for poly in cells for sign in (-1,1)
                 if len(part := clip(poly,plane,sign)) >= 3 and area(part) > 1]
        if len(cells) > 160:
            return []
    return cells


def center(poly):
    return tuple(sum(p[k] for p in poly)/len(poly) for k in (0,1))


def contains(poly, point):
    return all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) >= -1.e-5
               for a,b in zip(poly,poly[1:]+poly[:1]))


def inside(ring, point):
    x,y = point
    return sum((a[1]>y)!=(b[1]>y) and x < a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
               for a,b in zip(ring,ring[1:]+ring[:1])) % 2 == 1


def near_edge(ring, point, tolerance=4):
    for a,b in zip(ring,ring[1:]+ring[:1]):
        dx,dy = b[0]-a[0],b[1]-a[1]
        t = max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/max(1.e-12,dx*dx+dy*dy)))
        if math.dist(point,(a[0]+t*dx,a[1]+t*dy)) <= tolerance:
            return True
    return False


def edges(cells):
    """Rounded keys weld only numerical noise; measured geometry stays unrounded."""
    owners = {}
    for index, poly in enumerate(cells):
        for a,b in zip(poly,poly[1:]+poly[:1]):
            key = tuple(sorted((tuple(round(v,4) for v in a),tuple(round(v,4) for v in b))))
            if key[0] == key[1]:
                continue  # Nearly concurrent supports can leave sub-micron edges.
            owners.setdefault(key,[]).append((index,a,b))
    return owners


def outline(cells, reached, min_corners=6):
    following = {}
    for owners in edges(cells).values():
        kept = [(a,b) for index,a,b in owners if index in reached]
        if len(kept) != 1:
            continue
        a,b = kept[0]
        key,end = tuple(round(v,4) for v in a),tuple(round(v,4) for v in b)
        if key in following or key == end:
            return None
        following[key] = (end,a)
    if not following:
        return None
    start = cursor = min(following)
    ring = []
    while cursor in following:
        cursor, point = following.pop(cursor)
        ring.append(point)
    if cursor != start or following:
        return None  # Multiple loops, a hole, or a corner-only connection.
    ring = remove_collinear(ring)
    if not min_corners <= len(ring) <= 24:
        return None
    try:
        validate_simple_outline(ring)
    except ValueError:
        return None
    return ring


def remove_collinear(ring):
    result = []
    for i,b in enumerate(ring):
        a,c = ring[i-1],ring[(i+1)%len(ring)]
        ab,bc = (b[0]-a[0],b[1]-a[1]),(c[0]-b[0],c[1]-b[1])
        if abs(ab[0]*bc[1]-ab[1]*bc[0]) > 1.e-6*math.hypot(*ab)*math.hypot(*bc):
            result.append(b)
    return result


def stable_outline(ring):
    """Remove sub-millimetre intersection noise before UE's float/BSP cooking.

    0.001 cm quantization moves a vertex by at most 0.000708 cm. This is numeric
    conditioning, not a shape approximation or permission to close a doorway.
    """
    points = []
    for x,y in ring:
        point = round(x,3),round(y,3)
        if not points or point!=points[-1]:
            points.append(point)
    if len(points)>1 and points[0]==points[-1]:
        points.pop()
    points = remove_collinear(points)
    if len(points)<3:
        return None
    try:
        validate_simple_outline(points)
    except ValueError:
        return None
    return points
