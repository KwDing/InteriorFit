"""Recover repeated straight treads or a stepped ceiling from two verified parallel profiles."""
import math
from statistics import median

from .rays import query
from .planar_room import _wall_frame
from .planar_checks import walls_match


def _bounds(frame, pilot):
    walls = {(axis, sign): [] for axis in (0, 1) for sign in (-1, 1)}
    for hit in pilot:
        if not hit:
            continue
        normal = frame.direction(hit[1])
        axis = int(abs(normal[1]) > abs(normal[0]))
        if abs(normal[axis]) > 0.998:
            sign = 1 if normal[axis] > 0 else -1
            walls[axis, sign].append(frame.local(hit[0])[axis])
    bounds = []
    for group in walls.values():
        if len(group) < 2:
            return None
        value = median(group)
        if sum(abs(x-value) < 3 for x in group) < max(2, len(group)*0.65):
            return None
    for axis in (0, 1):
        low, high = median(walls[axis, 1]), median(walls[axis, -1])
        if not low < 0 < high or not 130 < high-low < 1900:
            return None
        bounds.append((low, high))
    return bounds


def _heights(frame, points, roof):
    rays = []
    for x, y in points:
        mid = frame.world((x, y, roof*0.6))
        rays.extend([(mid, frame.world((x, y, -150))), (mid, frame.world((x, y, roof+220)))])
    hits = yield from query(rays)
    heights = []
    for lo, hi in zip(hits[::2], hits[1::2]):
        if not lo or not hi or frame.direction(lo[1])[2] < 0.985 or frame.direction(hi[1])[2] > -0.985:
            return None
        floor, top = frame.local(lo[0])[2], frame.local(hi[0])[2]
        if top-floor < 190:
            return None
        heights.append((round(floor/2)*2, round(top/2)*2))
    return heights


def _diff(a, b):
    return max(abs(x-y) for x, y in zip(a, b))


def _direction(samples):
    for axis in (0, 1):
        rows = [samples[i*3:i*3+3] for i in range(3)]
        if axis:
            rows = list(zip(*rows))
        if any(_diff(row[0], row[-1]) > 4 for row in rows):
            continue
        if any(_diff(rows[0][0], row[0]) > 8 for row in rows[1:]):
            return axis
    return None


def _xy(axis, longitudinal, lateral):
    return (lateral, longitudinal) if axis else (longitudinal, lateral)


def _runs(frame, bounds, axis, roof):
    lo, hi = bounds[axis]
    side, end = bounds[1-axis]
    count = math.ceil((hi-lo)/26)
    xs = [lo+(i+0.5)*(hi-lo)/count for i in range(count)]
    lanes = [side+(end-side)*t for t in (0.12, 0.86)]
    points = [_xy(axis, x, y) for x in xs for y in lanes]
    heights = yield from _heights(frame, points, roof)
    if not heights:
        return None
    runs = []
    for x, a, b in zip(xs, heights[::2], heights[1::2]):
        if _diff(a, b) > 3:
            return None
        if not runs or _diff(runs[-1][2], a) > 3:
            runs.append([x, x, a])
        else:
            runs[-1][1] = x
    if 2 <= len(runs) <= 24:
        return runs


def _cuts(frame, bounds, axis, runs):
    rays = []
    side, end = bounds[1-axis]
    for (_, left, a), (right, _, b) in zip(runs, runs[1:]):
        idx = int(abs(a[1]-b[1]) > abs(a[0]-b[0]))
        if abs(a[0]-b[0]) > 38 or abs(a[1]-b[1]) > 70:
            return None
        start, stop = (left, right) if ((a[idx] < b[idx]) != bool(idx)) else (right, left)
        z = (a[idx]+b[idx])/2
        for t in (0.32, 0.70):
            y = side+(end-side)*t
            rays.append((frame.world((*_xy(axis, start, y), z)), frame.world((*_xy(axis, stop, y), z))))
    hits = yield from query(rays)
    cuts = [None]*(len(runs)-1)
    unresolved = []
    for i, (a, b) in enumerate(zip(hits[::2], hits[1::2])):
        if a and b and all(abs(frame.direction(h[1])[axis]) >= 0.985 for h in (a, b)):
            x, y = frame.local(a[0])[axis], frame.local(b[0])[axis]
            if abs(x-y) > 3:
                return None
            cuts[i] = (x+y)/2
        else:
            unresolved.extend([[i, t, runs[i][1], runs[i+1][0]] for t in (0.32, 0.70)])
    if unresolved and not (yield from _bisect(frame, bounds, axis, runs, unresolved, cuts)):
        return None
    edges = [bounds[axis][0], *cuts, bounds[axis][1]]
    return edges if all(b-a > 4 for a, b in zip(edges, edges[1:])) else None


def _bisect(frame, bounds, axis, runs, brackets, cuts):
    # An open tread mesh can expose its top but have no vertical riser collision.
    # Only unresolved transitions need extra vertical samples.
    side, end = bounds[1-axis]
    for _ in range(4):
        points = [_xy(axis, (lo+hi)/2, side+t*(end-side)) for _, t, lo, hi in brackets]
        samples = yield from _heights(frame, points, runs[0][2][1])
        if not samples:
            return False
        for row, height in zip(brackets, samples):
            i, _, lo, hi = row
            if _diff(height, runs[i][2]) <= 3:
                row[2] = (lo+hi)/2
            elif _diff(height, runs[i+1][2]) <= 3:
                row[3] = (lo+hi)/2
            else:
                return False
    for a, b in zip(brackets[::2], brackets[1::2]):
        x, y = sum(a[2:])/2, sum(b[2:])/2
        if abs(x-y) > 3:
            return False
        cuts[a[0]] = (x+y)/2
    return True


def fit(base, pilot, roof):
    frame = _wall_frame(base, pilot)
    bounds = _bounds(frame, pilot) if frame else None
    if not bounds:
        return None
    (x0, x1), (y0, y1) = bounds
    sites = [(x0+(x1-x0)*i, y0+(y1-y0)*j) for i in (0.13, 0.5, 0.86) for j in (0.13, 0.5, 0.86)]
    samples = yield from _heights(frame, sites, roof)
    axis = _direction(samples) if samples else None
    if axis is None:
        return None
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if not (yield from walls_match(frame, ring, min(h[1] for h in samples))):
        return None
    runs = yield from _runs(frame, bounds, axis, roof)
    if not runs:
        return None
    cuts = yield from _cuts(frame, bounds, axis, runs)
    if not cuts:
        return None
    midpoints = [_xy(axis, (a+b)/2, sum(bounds[1-axis])/2) for a, b in zip(cuts, cuts[1:])]
    check = yield from _heights(frame, midpoints, roof)
    if not check or any(_diff(h, r[2]) > 3 for h, r in zip(check, runs)):
        return None
    sections = [(lo, hi, *r[2]) for lo, hi, r in zip(cuts, cuts[1:], runs)]
    clear_z = min(s[3] for s in sections)-30
    if clear_z <= max(s[2] for s in sections)+10:
        return None
    # Independent vertical profiles alone cannot exclude a floor-to-ceiling partition.
    links = []
    for t in (0.26, 0.73):
        px, py = x0+t*(x1-x0), y0+t*(y1-y0)
        links.extend([(frame.world((x0+8, py, clear_z)), frame.world((x1-8, py, clear_z))),
                      (frame.world((px, y0+8, clear_z)), frame.world((px, y1-8, clear_z)))])
    if any((yield from query(links))):
        return None
    floor = min(s[2] for s in sections)
    outline = [(x, y, floor) for x, y in ring]
    return dict(model="strip_profile", axis=axis, lateral=bounds[1-axis], sections=sections,
                columns=len(runs), floor=floor, roof=max(s[3] for s in sections), origin=frame.origin,
                axis_x=frame.x, axis_z=frame.z, local_outline=outline, outline=[frame.world(p) for p in outline])
