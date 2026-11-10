"""Fit a room in its measured floor frame, retrying ambiguous probes within a ray budget."""

import math
from .rooms.frame import FloorFrame, cross, dot, unit
from .rooms.rays import BATCH_SIZE as BATCH_SIZE, MAX_CELLS as MAX_CELLS, NEIGHBORS as NEIGHBORS, STEP, query
from .rooms.grid import scan_local
from .rooms.walls import refine_edges as refine_edges, supported_convex as supported_convex
from .room_height import spherical_room, SphereUnsupported
from .rooms import cylinder, curved_prism, roof_fit, strip_profile, adaptive_room
from .rooms.candidate import Candidate


def _wall_fan(frame, height, indices):
    center = frame.world((0, 0, height))
    angles = [i * math.tau / 72 for i in indices]
    return (yield from query([(center, frame.world((2500 * math.cos(a), 2500 * math.sin(a), height)))
                              for a in angles]))


def _paired_walls(frame, ceiling, pilot=None):
    height = frame.local(ceiling[0])[2] - 30
    center = frame.world((0, 0, height))
    if pilot is None:
        fan = yield from _wall_fan(frame, height, range(72))
    else:
        missing = [i for i in range(72) if i % 3]
        fan = [None] * 72
        fan[::3] = pilot
        for index, hit in zip(missing, (yield from _wall_fan(frame, height, missing))):
            fan[index] = hit
    # Circular mean modulo 90 degrees. Dominant orthogonal walls reinforce one another.
    directions = [frame.direction(hit[1]) for hit in fan if hit and math.dist(center, hit[0]) < 2400]
    angles = [4 * math.atan2(n[1], n[0]) for n in directions if abs(n[2]) < 0.15]
    sx, sy = sum(map(math.cos, angles)), sum(map(math.sin, angles))
    if len(angles) >= 8 and math.hypot(sx, sy) > 0.6 * len(angles):
        yaw = math.atan2(sy, sx) / 4
        frame.x = unit(tuple(a * math.cos(yaw) + b * math.sin(yaw) for a, b in zip(frame.x, frame.y)))
        frame.y = cross(frame.z, frame.x)
    # The second height rejects isolated returns from furniture, openings and trim.
    lower = height - 65
    lower_center = frame.world((0, 0, lower))
    lower_fan = yield from query(
        [
            (lower_center, frame.world((2500 * math.cos(i * math.tau / 72), 2500 * math.sin(i * math.tau / 72), lower)))
            for i in range(72)
        ]
    )
    paired = []
    for high_hit, low_hit in zip(fan, lower_fan):
        if not high_hit or not low_hit or dot(high_hit[1], low_hit[1]) < 0.999:
            continue
        normal = frame.direction(high_hit[1])
        p, q = frame.local(high_hit[0]), frame.local(low_hit[0])
        if abs(normal[2]) < 0.04 and abs(dot(normal, p) - dot(normal, q)) < 3:
            paired.append((normal[:2], p[:2]))
    return paired


def _scan_frame(frame, seed, paired, allow_slopes):
    fixed_planes = False
    worker = scan_local(frame.local(seed), paired, allow_slopes)
    rays = next(worker)
    while True:
        hits = yield [(frame.world(a), frame.world(b)) for a, b in rays]
        local = [(frame.local(hit[0]), frame.direction(hit[1])) if hit else None for hit in hits]
        try:
            rays = worker.send(local)
        except ValueError as error:
            if "Room footprint has holes" in str(error) and not fixed_planes and not allow_slopes:
                fixed_planes = True
                worker = scan_local(frame.local(seed), paired, fixed_planes=True)
                rays = next(worker)
                continue
            if str(error) != "Curved ceiling":
                raise
            try:
                return (yield from spherical_room(frame, seed, query))
            except SphereUnsupported:
                worker = scan_local(frame.local(seed), paired, allow_slopes=True)
                rays = next(worker)
        except StopIteration as done:
            result = done.value
            break
    result.update(
        planar_recheck=fixed_planes,
        local_outline=result["outline"],
        axis_x=frame.x,
        axis_z=frame.z,
        origin=frame.origin,
        seed=seed,
        rays=result["rays"] + 146,
    )
    result["outline"] = [frame.world(p) for p in result["local_outline"]]
    return result


def scan_from_probe(seed, triangle_budget=None):
    """Estimate floor tilt, use a 360-degree fan to find wall axes, then scan in that frame."""
    x, y, z = seed
    (floor_hit,) = yield from query([((x, y, z + 12), (x, y, z - 500))])
    if not floor_hit or floor_hit[1][2] < 0.7:
        raise ValueError("Seed needs a supported floor")
    frame = FloorFrame(floor_hit[0], floor_hit[1])
    seed_local = frame.local(seed)
    (ceiling,) = yield from query([(tuple(seed), frame.world((0, 0, seed_local[2] + 900)))])
    if not ceiling:
        raise ValueError("No ceiling above seed")
    roof_tested = dot(ceiling[1],frame.z) > -0.998
    if roof_tested:
        cap = yield from roof_fit.fit(frame,seed,triangle_budget)
        if cap:
            return cap
    allow_slopes = dot(ceiling[1], frame.z) > -0.99
    if allow_slopes:
        try:
            return (yield from spherical_room(frame, seed, query))
        except SphereUnsupported:
            # A staircase may use a sloped collision ramp under a horizontal slab.
            frame = FloorFrame(floor_hit[0], (0, 0, 1))
    roof = frame.local(ceiling[0])[2]
    pilot = None
    if not allow_slopes:
        pilot = yield from _wall_fan(frame, roof - 30, range(0, 72, 3))
        if not roof_tested and sum(hit is not None and frame.direction(hit[1])[2]<-0.15 for hit in pilot) >= 8:
            cap = yield from roof_fit.fit(frame,seed,triangle_budget)
            if cap:
                return cap
        candidate = yield from cylinder.fit(frame, pilot, roof)
        if candidate:
            return candidate
        candidate = yield from curved_prism.fit(frame,pilot,roof)
        if candidate:
            return candidate
        candidate = yield from strip_profile.fit(frame,pilot,roof)
        if candidate:
            return candidate
        candidate = yield from adaptive_room.fit(frame,pilot,roof)
        if candidate and candidate.get('height_change'):
            low = yield from _wall_fan(frame,roof*.55,range(0,72,3))
            candidate = yield from strip_profile.fit(frame,low,roof)
        if candidate:
            return candidate
    walls = yield from _paired_walls(frame, ceiling, pilot)
    return (yield from _scan_frame(frame, seed, walls, allow_slopes))


def _seed_candidate(event, seed, probe, total):
    """Forward partial evidence only when it still contains the designer's seed."""
    if includes_seed(event.result, seed):
        candidate = dict(event.result, seed=seed, probe=probe, rays=total)
        yield event.mapped(candidate)


def scan(seed, triangle_budget=None):
    """Retry ambiguous grid alignments nearby, keeping the selected seed as the public input."""
    total = 0
    last = None
    cache = {}
    for dx, dy in ((0, 0), (19, 11), (-17, 21), (65, -35), (-55, -45)):
        probe = (seed[0] + dx, seed[1] + dy, seed[2])
        if dx or dy:
            (blocked,) = yield [(seed, probe)]
            total += 1
            if blocked:
                continue
        worker = scan_from_probe(probe) if triangle_budget is None else scan_from_probe(probe, triangle_budget)
        rays = next(worker)
        try:
            while True:
                if isinstance(rays,Candidate):
                    yield from _seed_candidate(rays, seed, probe, total)
                    rays = next(worker)
                    continue
                keys = [(tuple(a),tuple(b)) for a,b in rays]
                missing = list(dict.fromkeys(k for k in keys if k not in cache))
                if total+len(missing) > 160000:
                    raise ValueError("Combined scan ray budget exceeded")
                if missing:
                    total += len(missing)
                    cache.update(zip(missing,(yield missing)))
                answers = [cache[k] for k in keys]
                # Only reuse identical directed segments within this one editor scan.
                # Different heights, opposite directions and future jobs remain independent.
                if len(cache)>8192:
                    cache.clear()
                rays = worker.send(answers)
        except StopIteration as done:
            result = done.value
            if (dx or dy) and not includes_seed(result, seed):
                last = ValueError("Offset candidate excludes the original seed")
                continue
            result.update(seed=seed, probe=probe, rays=total)
            return result
        except ValueError as error:
            message = str(error)
            if not any(
                key in message
                for key in ("corner", "holes", "disconnected", "roof", "ceiling", "headroom", "height changes")
            ):
                raise
            last = error
    raise ValueError("No consistent room found around this seed: " + str(last))


def includes_seed(result, seed):
    delta = tuple(a - b for a, b in zip(seed, result["origin"]))
    x, y, z = (
        dot(delta, axis) for axis in (result["axis_x"], cross(result["axis_z"], result["axis_x"]), result["axis_z"])
    )
    if result["model"] == "stepped_heightfield":
        gx, gy = result["grid_origin"]
        cell = round((x - gx) / STEP), round((y - gy) / STEP)
        return any((i, j) == cell and low <= z <= high for i, j, low, high in result["height_cells"])
    if result["model"] == "floor_clipped_sphere":
        return z >= 0 and math.dist((x, y, z), result["sphere_center"]) <= result["radius"]
    if result["model"] == "ridge_prism":
        return all(dot(n,(x,y,z)) >= d for n,d in result["inward_planes"])
    if result["model"] == "ellipsoid_cap":
        if "triangle_budget" in result:
            from .rooms.budget_cap import contains
            return contains(result,(x,y,z))
        from .rooms.roof_mesh import inside_ellipsoid
        return inside_ellipsoid(result,x,y,z)
    if result["model"] == "strip_profile":
        longitudinal,lateral = (y,x) if result["axis"] else (x,y)
        lo,hi = result["lateral"]
        return lo <= lateral <= hi and any(a<=longitudinal<=b and f<=z<=h for a,b,f,h in result["sections"])
    if not result["floor"] <= z <= result["roof"]:
        return False
    points = result["local_outline"]
    inside = False
    for i, (ax, ay, _) in enumerate(points):
        bx, by, _ = points[i - 1]
        if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
            inside = not inside
    return inside
