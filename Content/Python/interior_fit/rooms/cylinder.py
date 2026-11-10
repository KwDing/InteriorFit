"""Recognize a constant cylindrical section from measured walls before flooding its floor."""

import math
from statistics import median

from .rays import query
from .planar_checks import floor_under_obstacles


def _candidate(planes):
    # For each inward-facing tangent, n·center - radius = n·wall.
    (a, b, d), (e, f, g), (h, i, j) = planes
    det = (a - e) * (b - i) - (a - h) * (b - f)
    if abs(det) < 0.2:
        return None
    x = ((d - g) * (b - i) - (d - j) * (b - f)) / det
    y = ((a - e) * (d - j) - (a - h) * (d - g)) / det
    r = a * x + b * y - d
    if 100 <= r <= 1500 and math.hypot(x, y) < r - 5:
        return x, y, r


def _section(walls):
    planes = [(a, b, a*x + b*y) for (a, b), (x, y) in walls]
    count = len(planes)
    if count < 16 or len({round(math.atan2(b, a), 2) for a, b, _ in planes}) < 12:
        return None
    best = []
    for index in range(count):
        model = _candidate([planes[(index + k * count // 3) % count] for k in range(3)])
        if not model:
            continue
        x, y, r = model
        support = [(a, b, d) for a, b, d in planes if abs(a*x + b*y - d - r) <= 3]
        if len(support) > len(best):
            best, center = support, (x, y)
    if len(best) < max(16, 0.8 * count):
        return None
    angles = sorted(math.atan2(-b, -a) for a, b, _ in best)
    gaps = [b-a for a, b in zip(angles, angles[1:] + [angles[0] + math.tau])]
    if max(gaps) > math.radians(56):
        return None
    x, y = center
    return x, y, median(a*x + b*y - d for a, b, d in best), angles


def _outline(x, y, radius, normals):
    # Recover a faceted wall's actual corners if its tangent directions share a pitch.
    for sides in range(16, 49):
        pitch = math.tau / sides
        phase = normals[0]
        if all(abs(math.remainder(a-phase, pitch)) < 0.006 for a in normals):
            start = phase + pitch / 2
            radius /= math.cos(pitch / 2)
            break
    else:
        sides = max(24, math.ceil(math.pi / math.acos(1 - 2/radius)))
        start = 0
    return [(x + radius*math.cos(start+i*math.tau/sides),
             y + radius*math.sin(start+i*math.tau/sides), 0) for i in range(sides)]


def _ring_rays(frame, section, roof):
    """Probe independent directions at two floor radii and two wall heights."""
    x, y, radius, _ = section
    rays = []
    for i in range(20):
        a = (i + 0.37) * math.tau / 20
        dx, dy = math.cos(a), math.sin(a)
        for scale in (0.48, 0.90):
            px, py = x + scale*radius*dx, y + scale*radius*dy
            mid = frame.world((px, py, roof / 2))
            rays.extend([(mid, frame.world((px, py, -12))), (mid, frame.world((px, py, roof+12)))])
        for height in (roof-20, roof-95):
            rays.append((frame.world((x, y, height)),
                         frame.world((x+(radius+100)*dx, y+(radius+100)*dy, height))))
    return rays


def _radial_distance(frame, hit, x, y):
    if not hit:
        return math.inf
    px, py, _ = frame.local(hit[0])
    return math.hypot(px - x, py - y)


def _check_rings(frame, section, roof):
    x, y, radius, _ = section
    hits = yield from query(_ring_rays(frame, section, roof))
    high_support = 0
    paired_support = 0
    openings = []
    raised = []
    for start in range(0, len(hits), 6):
        for k, height in enumerate((0, roof, 0, roof)):
            hit = hits[start+k]
            if not hit:
                return None
            px, py, z = frame.local(hit[0])
            if height == 0 and 5 < z < roof / 2:
                raised.append((px, py, z))
            elif abs(z - height) > 5:
                return None
        upper, lower = hits[start+4:start+6]
        tolerance = max(4, radius*0.012)
        if abs(_radial_distance(frame, upper, x, y) - radius) <= tolerance:
            high_support += 1
            distance = _radial_distance(frame, lower, x, y)
            if abs(distance-radius) <= tolerance:
                paired_support += 1
            elif distance > radius + 30:
                # A lintel with open space below it is a lead for the author, not a Portal.
                px, py, _ = frame.local(upper[0])
                openings.append(frame.world((px, py, roof-95)))
    if high_support < 18 or paired_support < 13 or len(raised) > 2:
        return None
    if raised and not (yield from floor_under_obstacles(frame, raised)):
        return None
    return openings


def fit(frame, pilot, roof):
    walls = []
    for hit in pilot:
        if hit:
            normal = frame.direction(hit[1])
            if abs(normal[2]) < 0.04:
                walls.append((normal[:2], frame.local(hit[0])[:2]))
    section = _section(walls)
    if roof < 190 or not section:
        return None
    openings = yield from _check_rings(frame, section, roof)
    if openings is None:
        return None
    outline = _outline(*section)
    return dict(model="circular_prism", origin=frame.origin, axis_x=frame.x, axis_z=frame.z,
                floor=0, roof=roof, local_outline=outline, outline=[frame.world(p) for p in outline],
                columns=0, opening_hints=openings)
