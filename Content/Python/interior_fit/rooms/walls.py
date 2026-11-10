import math
from .rays import STEP, NEIGHBORS, query
from .frame import unit, dot
from ..spline_contour import validate_simple_outline


def _edge_probes(points, roof):
    """Keep six ordered probes per edge: three positions at two ceiling heights."""
    rays = []
    normals = []
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        n = unit((b[1] - a[1], a[0] - b[0]))
        normals.append(n)
        for t in (0.22, 0.5, 0.78):
            x, y = (a[k] + t * (b[k] - a[k]) for k in (0, 1))
            for z in (roof - 25, roof - 55):
                rays.append(((x - STEP * n[0], y - STEP * n[1], z), (x + STEP * n[0], y + STEP * n[1], z)))
    return rays, normals


def _supported_plane(hits, outward):
    measurements = []
    for hit in hits:
        if not hit or abs(hit[1][2]) > 0.15:
            continue
        normal = unit(tuple(-v for v in hit[1][:2]))
        if dot(outward, normal) > 0.75:
            measurements.append((normal, hit[0][:2]))

    def support(candidate):
        _, anchor = candidate
        return sum(
            dot(normal, candidate[0]) > 0.998 and abs(dot(normal, point) - dot(normal, anchor)) < 3
            for normal, point in measurements
        )

    best = max(measurements, key=support, default=None)
    if best and support(best) >= 3:
        normal, point = best
        return normal, dot(normal, point)
    return None


def _wall_planes(points, normals, hits):
    planes = []
    supported_count = 0
    for i, (a, n) in enumerate(zip(points, normals)):
        plane = _supported_plane(hits[i * 6 : i * 6 + 6], n)
        if plane is not None:
            supported_count += 1
            planes.append(plane)
        else:
            planes.append((n, dot(n, a[:2])))
    return planes, supported_count


def _intersect_neighbors(points, planes):
    """Reject near-parallel/remote intersections and retain a valid simple outline."""
    result = []
    for i, p in enumerate(points):
        (a, b), d = planes[i - 1]
        (c, e), f = planes[i]
        det = a * e - b * c
        if abs(det) > 0.05:
            x, y = (d * e - b * f) / det, (a * f - d * c) / det
            if math.hypot(x - p[0], y - p[1]) < STEP * 1.6:
                p = (x, y, p[2])
        result.append(p)
    try:
        validate_simple_outline(result)
    except ValueError:
        result = points
    return result


def refine_edges(points, roof, details=None):
    """Fit supported wall planes, then intersect convex AND reflex neighbors."""
    rays, normals = _edge_probes(points, roof)
    hits = yield from query(rays)
    planes, supported_count = _wall_planes(points, normals, hits)
    result = _intersect_neighbors(points, planes)
    if details is not None:
        details.update(wall_supported=supported_count, wall_total=len(points))
    return result, len(rays)


def supported_convex(walls, centers, floor):
    """Clip by observed wall half-planes only if the convex result agrees with the connected grid."""
    # Extreme projections of a horizontal grid row occur at one of its endpoints.
    # This keeps plane validation cheap even in large rooms.
    ranges = {}
    for x, y, _ in centers:
        low, high = ranges.get(y, (x, x))
        ranges[y] = min(low, x), max(high, x)
    endpoints = [(x, y) for y, (low, high) in ranges.items() for x in (low, high)]
    planes = []
    for inward, point in walls:
        n = unit(inward)
        offset = dot(n, point)
        if any(dot(n, m) > 0.9999 and abs(offset - d) < 2 for m, d in planes):
            continue
        # A cabinet face or a wall defining a recess cuts through valid cells.
        if all(dot(n, p) >= offset - 2 for p in endpoints):
            planes.append((n, offset))
    if len(planes) < 3:
        return None
    xs, ys, _ = zip(*centers)
    left, right = min(xs) - 2 * STEP, max(xs) + 2 * STEP
    near, far = min(ys) - 2 * STEP, max(ys) + 2 * STEP
    polygon = [(left, near), (right, near), (right, far), (left, far)]
    for n, d in planes:
        clipped = []
        for i, a in enumerate(polygon):
            b = polygon[(i + 1) % len(polygon)]
            da, db = dot(n, a) - d, dot(n, b) - d
            if da >= 0:
                clipped.append(a)
            if (da >= 0) != (db >= 0):
                t = da / (da - db)
                clipped.append(tuple(a[j] + t * (b[j] - a[j]) for j in (0, 1)))
        polygon = clipped
    if len(polygon) < 3 or any(min(x - left, right - x, y - near, far - y) < 1 for x, y in polygon):
        return None
    inside = {(round((x - xs[0]) / STEP), round((y - ys[0]) / STEP)) for x, y, _ in centers}
    boundary = {(i + di, j + dj) for i, j in inside for di, dj in NEIGHBORS} - inside
    for i, j in boundary:
        p = (xs[0] + i * STEP, ys[0] + j * STEP)
        if all(dot(n, p) > d + 2 for n, d in planes):
            return None
    return [(x, y, floor) for x, y in polygon]
