"""Verify a visible constant curved section without sampling every floor cell."""
import math

from .rays import query
from .plane_loop import intersect_runs
from .planar_checks import check_heights
from ..spline_contour import simplify_path, validate_simple_outline


def fit(frame, pilot, roof):
    directions = [frame.direction(h[1]) for h in pilot if h]
    if len({round(math.atan2(y, x), 2) for x, y, z in directions if abs(z) < 0.04}) < 12:
        return None
    height = roof - 5
    start = frame.world((0, 0, height))
    # Authoring approximation: 64 directions, followed by independent mid-edge
    # checks. Sub-centimetre reconstruction is unnecessary for the final budget.
    angles = [math.tau*i/64 for i in range(64)]
    hits = yield from query([(start, frame.world((1800*math.cos(a), 1800*math.sin(a), height))) for a in angles])
    planes = []
    for hit in hits:
        if not hit:
            return None
        x, y, _ = frame.local(hit[0])
        nx, ny, nz = frame.direction(hit[1])
        if abs(nz) > 0.04 or nx*x+ny*y >= -15:
            return None
        planes.append((nx, ny, nx*x+ny*y))
    ring = intersect_runs(planes, 64, min_sine=0.001)
    if not ring or not (yield from _verify(frame, ring, roof)):
        # Nearly parallel tangents on a smooth wall can meet far beyond both hits.
        # Use a chord there only if new mid-segment rays independently support it.
        sampled = [(x, y, 0) for x, y, _ in (frame.local(hit[0]) for hit in hits)]
        reduced = simplify_path(sampled, 4.0, True)
        try:
            validate_simple_outline(reduced)
        except ValueError:
            return None
        ring = [(x, y) for x, y, _ in reduced]
        ring = yield from _split_curved_edges(frame, ring, roof)
        if not ring:
            return None
        if not (yield from _verify(frame, ring, roof)):
            return None
    outline = [(x, y, 0) for x, y in ring]
    return dict(model="wall_plane_prism", floor=0, roof=roof, origin=frame.origin,
                axis_x=frame.x, axis_z=frame.z, local_outline=outline,
                outline=[frame.world(p) for p in outline], columns=0)


def _split_curved_edges(frame, ring, roof):
    """Add a measured vertex only where a straight chord misses the near-top wall."""
    z = roof-5
    rays = []
    for a, b in zip(ring, ring[1:]+ring[:1]):
        x, y = (a[0]+b[0])/2, (a[1]+b[1])/2
        distance = math.hypot(x, y)
        if distance < 20:
            return None
        rays.append((frame.world((0, 0, z)), frame.world((x*(1+30/distance), y*(1+30/distance), z))))
    corrected = []
    for a, b, hit in zip(ring, ring[1:]+ring[:1], (yield from query(rays))):
        if not hit:
            return None
        corrected.append(a)
        p = frame.local(hit[0])[:2]
        error = math.dist(p, ((a[0]+b[0])/2, (a[1]+b[1])/2))
        if error > 18:
            return None
        if error > 6:
            corrected.append(p)
    return corrected


def _verify(frame, ring, roof):
    rays, points = [], []
    for a, b in zip(ring, ring[1:]+ring[:1]):
        x, y = (a[0]+b[0])/2, (a[1]+b[1])/2
        distance = math.hypot(x, y)
        if distance < 20 or distance > 1700:
            return False
        for z in (roof-8, roof-85):
            rays.append((frame.world((0, 0, z)), frame.world((x*(1+25/distance), y*(1+25/distance), z))))
        points.append((x, y))
    hits = yield from query(rays)
    low_support = 0
    for (x, y), upper, lower in zip(points, hits[::2], hits[1::2]):
        if not upper or math.dist(frame.local(upper[0])[:2], (x, y)) > 8:
            return False
        if lower and math.dist(frame.local(lower[0])[:2], (x, y)) <= 10:
            low_support += 1
    # Additional wall facets need horizontal checks, but need not increase the
    # density of the two independent floor/ceiling rings on this constant section.
    count = min(8, (len(points)+1)//2)
    directions = [points[i*len(points)//count] for i in range(count)]
    probes = [(x*s, y*s) for x, y in directions for s in (0.43, 0.90)]
    return low_support >= 0.65*len(points) and (yield from check_heights(frame, probes, roof))
