"""Reconstruct planar walls from a bounded, ordered noisy contour.

Douglas-Peucker deletes samples. The optional total-least-squares pass instead
reconstructs each selected wall line, then intersects neighbouring wall lines.
No room labels, expected corner counts, or reference geometry are used.
"""
import math


def distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-12, dx*dx+dy*dy)
    t = max(0, min(1, t))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def simplify_indices(points, tolerance):
    """Closed DP chain; the repeated endpoint is omitted from the returned ring."""
    chain = list(points)+[points[0]]
    keep = {0, len(points)}
    work = [(0, len(points))]
    while work:
        a, b = work.pop()
        if b-a < 2:
            continue
        index = max(range(a+1, b), key=lambda i: distance(chain[i], chain[a], chain[b]))
        if distance(chain[index], chain[a], chain[b]) > tolerance:
            keep.add(index)
            work.extend(((a, index), (index, b)))
    return sorted(keep-{len(points)})


def wall_line(chain):
    """Fit by orthogonal distance; arc-length weighting avoids corner-density bias."""
    samples = []
    for a, b in zip(chain, chain[1:]):
        count = max(1, math.ceil(math.dist(a[:2], b[:2])/10))
        samples.extend(tuple(a[k]+(b[k]-a[k])*(i+.5)/count for k in (0, 1))
                       for i in range(count))
    cx, cy = (sum(p[k] for p in samples)/len(samples) for k in (0, 1))
    xx = sum((p[0]-cx)**2 for p in samples)
    yy = sum((p[1]-cy)**2 for p in samples)
    xy = sum((p[0]-cx)*(p[1]-cy) for p in samples)
    angle = .5*math.atan2(2*xy, xx-yy)
    return (cx, cy), (math.cos(angle), math.sin(angle))


def intersection(left, right):
    (ax, ay), (dx, dy) = left
    (bx, by), (ex, ey) = right
    denominator = dx*ey-dy*ex
    if abs(denominator) < .05:
        return None
    t = ((bx-ax)*ey-(by-ay)*ex)/denominator
    return ax+t*dx, ay+t*dy


def reconstruct(points, tolerance, refit=False):
    indices = simplify_indices(points, tolerance)
    if len(indices) < 3:
        raise ValueError('Too few surviving corners')
    corners = [tuple(points[i][:2]) for i in indices]
    if not refit:
        return corners
    closed = list(points)+list(points)
    ends = indices[1:]+[indices[0]+len(points)]
    lines = [wall_line(closed[a:b+1]) for a, b in zip(indices, ends)]
    out = [intersection(lines[i-1], line) for i, line in enumerate(lines)]
    if any(p is None or math.dist(p, q) > 2*tolerance for p, q in zip(out, corners)):
        raise ValueError('Unstable wall intersection')
    return out


def reconstruct_closed(points, tolerance, refit=False):
    """Resolve the closed seam by sample error, never reference truth.

    A closed ring has no privileged start vertex. With these small diagnostic
    contours, enumerate rotations to expose the ordinary DP seam sensitivity.
    The caller bounds input to 96 corners to keep this editor operation bounded.
    """
    candidates = []
    for i in range(len(points)):
        try:
            out = reconstruct(points[i:]+points[:i], tolerance, refit)
        except ValueError:
            continue
        edges = list(zip(out, out[1:]+out[:1]))
        residual = sum(min(distance(p, a, b) for a, b in edges)**2 for p in points)
        candidates.append(((len(out), residual), out))
    if not candidates:
        raise ValueError('No stable closed contour')
    return min(candidates, key=lambda item: item[0])[1]
