"""
Fit a room in its measured floor frame, retrying ambiguous probes within
a ray budget.
"""

import math
from interior_fit.rooms.frame import FloorFrame, cross, dot, unit
from interior_fit.rooms.ray_queries import (
    RayHitField,
    BATCH_SIZE as BATCH_SIZE,
    MAX_CELLS as MAX_CELLS,
    NEIGHBORS as NEIGHBORS,
    STEP,
    query,
)
from interior_fit.rooms.scanning.scan_grid import scan_local
from interior_fit.rooms.refine_wall_boundary import (
    refine_edges as refine_edges,
    supported_convex as supported_convex,
)
from interior_fit.rooms.fitting.spherical import (
    spherical_room,
    UnsupportedSphereError,
)
from interior_fit.rooms.fitting import (
    circular as cylinder,
    curved_prism,
    stepped as strip_profile,
    multiview_planar as adaptive_room,
)
from interior_fit.rooms.scanning import scan_ceiling as roof_fit
from interior_fit.rooms.candidate import Candidate
from interior_fit.rooms.scan_budget import MAX_COMBINED_SCAN_RAYS


RING_RAY_COUNT = 72  # 360° / 72 = 5° between directions.
RING_RAY_MAX_RANGE_CM = 2500
RING_UPPER_CEILING_OFFSET_CM = 30  # Near-ceiling band above floor clutter.
RING_VERTICAL_SPACING_CM = 65  # Upper-to-lower gap for wall continuity.

WALL_AXIS_VOTE_MAX_DISTANCE_CM = 2400  # Reliable-hit cutoff below ray range.

WALL_PAIR_MIN_NORMAL_DOT = 0.999  # cos(2.56°), rounded.
WALL_PAIR_MAX_OFFSET_CM = 3  # Exclusive tolerance for wall-normal separation.

RAY_FLOOR_START_ABOVE_SEED_CM = 12  # Avoid misses for seeds on the floor.
RAY_FLOOR_END_BELOW_SEED_CM = 500
RAY_CEILING_END_ABOVE_SEED_CM = 900  # Search reach in FloorFrame.

RAY_CACHE_MAX_SEGMENTS = 8192


def _trace_wall_ring(frame, height, indices):
    center = frame.world((0, 0, height))
    angles = [i * math.tau / RING_RAY_COUNT for i in indices]
    return (
        yield from query(
            [
                (
                    center,
                    frame.world(
                        (
                            RING_RAY_MAX_RANGE_CM * math.cos(a),
                            RING_RAY_MAX_RANGE_CM * math.sin(a),
                            height,
                        )
                    ),
                )
                for a in angles
            ]
        )
    )


def _measure_wall_pairs(frame, ceiling, pilot=None):
    height = (
        frame.local(ceiling[RayHitField.POINT])[2]
        - RING_UPPER_CEILING_OFFSET_CM
    )
    center = frame.world((0, 0, height))
    if pilot is None:
        upper_ring_hits = yield from _trace_wall_ring(
            frame, height, range(RING_RAY_COUNT)
        )
    else:
        missing = [i for i in range(RING_RAY_COUNT) if i % 3]
        upper_ring_hits = [None] * RING_RAY_COUNT
        upper_ring_hits[::3] = pilot
        missing_hits = yield from _trace_wall_ring(frame, height, missing)
        for index, hit in zip(missing, missing_hits):
            upper_ring_hits[index] = hit
    # Circular mean modulo 90 degrees. Dominant orthogonal walls reinforce one
    # another.
    directions = [
        frame.direction(hit[RayHitField.NORMAL])
        for hit in upper_ring_hits
        if hit
        and math.dist(center, hit[RayHitField.POINT])
        < WALL_AXIS_VOTE_MAX_DISTANCE_CM
    ]
    angles = [
        4 * math.atan2(n[1], n[0]) for n in directions if abs(n[2]) < 0.15
    ]
    sx, sy = sum(map(math.cos, angles)), sum(map(math.sin, angles))
    if len(angles) >= 8 and math.hypot(sx, sy) > 0.6 * len(angles):
        yaw = math.atan2(sy, sx) / 4
        frame.x = unit(
            tuple(
                a * math.cos(yaw) + b * math.sin(yaw)
                for a, b in zip(frame.x, frame.y)
            )
        )
        frame.y = cross(frame.z, frame.x)
    # The second height rejects isolated returns from furniture, openings and
    # trim.
    lower = height - RING_VERTICAL_SPACING_CM
    lower_center = frame.world((0, 0, lower))
    lower_ring_hits = yield from query(
        [
            (
                lower_center,
                frame.world(
                    (
                        RING_RAY_MAX_RANGE_CM
                        * math.cos(i * math.tau / RING_RAY_COUNT),
                        RING_RAY_MAX_RANGE_CM
                        * math.sin(i * math.tau / RING_RAY_COUNT),
                        lower,
                    )
                ),
            )
            for i in range(RING_RAY_COUNT)
        ]
    )
    paired = []
    for high_hit, low_hit in zip(upper_ring_hits, lower_ring_hits):
        if (
            not high_hit
            or not low_hit
            or dot(high_hit[RayHitField.NORMAL], low_hit[RayHitField.NORMAL])
            < WALL_PAIR_MIN_NORMAL_DOT
        ):
            continue
        normal = frame.direction(high_hit[RayHitField.NORMAL])
        p, q = (
            frame.local(high_hit[RayHitField.POINT]),
            frame.local(low_hit[RayHitField.POINT]),
        )
        if (
            abs(normal[2]) < 0.04
            and abs(dot(normal, p) - dot(normal, q)) < WALL_PAIR_MAX_OFFSET_CM
        ):
            paired.append((normal[:2], p[:2]))
    return paired


def _scan_frame(frame, seed, paired, allow_slopes):
    fixed_planes = False
    worker = scan_local(frame.local(seed), paired, allow_slopes)
    rays = next(worker)
    while True:
        hits = yield [(frame.world(a), frame.world(b)) for a, b in rays]
        local = [
            (
                frame.local(hit[RayHitField.POINT]),
                frame.direction(hit[RayHitField.NORMAL]),
            )
            if hit
            else None
            for hit in hits
        ]
        try:
            rays = worker.send(local)
        except ValueError as error:
            if (
                "Room footprint has holes" in str(error)
                and not fixed_planes
                and not allow_slopes
            ):
                fixed_planes = True
                worker = scan_local(
                    frame.local(seed), paired, fixed_planes=True
                )
                rays = next(worker)
                continue
            if str(error) != "Curved ceiling":
                raise
            try:
                return (yield from spherical_room(frame, seed, query))
            except UnsupportedSphereError:
                worker = scan_local(
                    frame.local(seed), paired, allow_slopes=True
                )
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
        rays=result["rays"] + 2 + 2 * RING_RAY_COUNT,
    )
    result["outline"] = [frame.world(p) for p in result["local_outline"]]
    return result


def scan_from_probe(seed, triangle_budget=None):
    """Estimate floor tilt and wall axes, then scan in that frame."""
    x, y, z = seed
    (floor_hit,) = yield from query(
        [
            (
                (x, y, z + RAY_FLOOR_START_ABOVE_SEED_CM),
                (x, y, z - RAY_FLOOR_END_BELOW_SEED_CM),
            )
        ]
    )
    if not floor_hit or floor_hit[RayHitField.NORMAL][2] < 0.7:
        raise ValueError("Seed needs a supported floor")
    frame = FloorFrame(
        floor_hit[RayHitField.POINT], floor_hit[RayHitField.NORMAL]
    )
    seed_local = frame.local(seed)
    (ceiling,) = yield from query(
        [
            (
                tuple(seed),
                frame.world(
                    (0, 0, seed_local[2] + RAY_CEILING_END_ABOVE_SEED_CM)
                ),
            )
        ]
    )
    if not ceiling:
        raise ValueError("No ceiling above seed")
    roof_tested = dot(ceiling[RayHitField.NORMAL], frame.z) > -0.998
    if roof_tested:
        cap = yield from roof_fit.fit(frame, seed, triangle_budget)
        if cap:
            return cap
    allow_slopes = dot(ceiling[RayHitField.NORMAL], frame.z) > -0.99
    if allow_slopes:
        try:
            return (yield from spherical_room(frame, seed, query))
        except UnsupportedSphereError:
            # A staircase may use a sloped collision ramp under a horizontal
            # slab.
            frame = FloorFrame(floor_hit[RayHitField.POINT], (0, 0, 1))
    roof = frame.local(ceiling[RayHitField.POINT])[2]
    pilot = None
    if not allow_slopes:
        pilot = yield from _trace_wall_ring(
            frame,
            roof - RING_UPPER_CEILING_OFFSET_CM,
            range(0, RING_RAY_COUNT, 3),
        )
        if (
            not roof_tested
            and sum(
                hit is not None
                and frame.direction(hit[RayHitField.NORMAL])[2] < -0.15
                for hit in pilot
            )
            >= 8
        ):
            cap = yield from roof_fit.fit(frame, seed, triangle_budget)
            if cap:
                return cap
        candidate = yield from cylinder.fit(frame, pilot, roof)
        if candidate:
            return candidate
        candidate = yield from curved_prism.fit(frame, pilot, roof)
        if candidate:
            return candidate
        candidate = yield from strip_profile.fit(frame, pilot, roof)
        if candidate:
            return candidate
        candidate = yield from adaptive_room.fit(frame, pilot, roof)
        if candidate and candidate.get("height_change"):
            low = yield from _trace_wall_ring(
                frame, roof * 0.55, range(0, RING_RAY_COUNT, 3)
            )
            candidate = yield from strip_profile.fit(frame, low, roof)
        if candidate:
            return candidate
    walls = yield from _measure_wall_pairs(frame, ceiling, pilot)
    return (yield from _scan_frame(frame, seed, walls, allow_slopes))


def _seed_candidate(event, seed, probe, total):
    """
    Forward partial evidence only when it still contains the designer's
    seed.
    """
    if includes_seed(event.result, seed):
        candidate = dict(event.result, seed=seed, probe=probe, rays=total)
        yield event.mapped(candidate)


def scan(seed, triangle_budget=None):
    """
    Retry ambiguous grid alignments nearby, keeping the selected seed as the
    public input.
    """
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
        worker = (
            scan_from_probe(probe)
            if triangle_budget is None
            else scan_from_probe(probe, triangle_budget)
        )
        rays = next(worker)
        try:
            while True:
                if isinstance(rays, Candidate):
                    yield from _seed_candidate(rays, seed, probe, total)
                    rays = next(worker)
                    continue
                keys = [(tuple(a), tuple(b)) for a, b in rays]
                missing = list(
                    dict.fromkeys(k for k in keys if k not in cache)
                )
                if total + len(missing) > MAX_COMBINED_SCAN_RAYS:
                    raise ValueError("Combined scan ray budget exceeded")
                if missing:
                    total += len(missing)
                    cache.update(zip(missing, (yield missing)))
                answers = [cache[k] for k in keys]
                # Only reuse identical directed segments within this one editor
                # scan.
                # Different heights, opposite directions and future jobs remain
                # independent.
                if len(cache) > RAY_CACHE_MAX_SEGMENTS:
                    cache.clear()
                rays = worker.send(answers)
        except StopIteration as done:
            result = done.value
            if (dx or dy) and not includes_seed(result, seed):
                last = ValueError(
                    "Offset candidate excludes the original seed"
                )
                continue
            result.update(seed=seed, probe=probe, rays=total)
            return result
        except ValueError as error:
            message = str(error)
            if not any(
                key in message
                for key in (
                    "corner",
                    "holes",
                    "disconnected",
                    "roof",
                    "ceiling",
                    "headroom",
                    "height changes",
                )
            ):
                raise
            last = error
    raise ValueError("No consistent room found around this seed: " + str(last))


def includes_seed(result, seed):
    delta = tuple(a - b for a, b in zip(seed, result["origin"]))
    x, y, z = (
        dot(delta, axis)
        for axis in (
            result["axis_x"],
            cross(result["axis_z"], result["axis_x"]),
            result["axis_z"],
        )
    )
    if result["model"] == "stepped_heightfield":
        gx, gy = result["grid_origin"]
        cell = round((x - gx) / STEP), round((y - gy) / STEP)
        return any(
            (i, j) == cell and low <= z <= high
            for i, j, low, high in result["height_cells"]
        )
    if result["model"] == "floor_clipped_sphere":
        return (
            z >= 0
            and math.dist((x, y, z), result["sphere_center"])
            <= result["radius"]
        )
    if result["model"] == "ridge_prism":
        return all(dot(n, (x, y, z)) >= d for n, d in result["inward_planes"])
    if result["model"] == "ellipsoid_cap":
        if "triangle_budget" in result:
            from ..geometry import (
                mesh_ellipsoid_cap_with_polybudget as budget_cap,
            )

            return budget_cap.contains(result, (x, y, z))
        from interior_fit.rooms.geometry.build_roof_mesh import (
            inside_ellipsoid,
        )

        return inside_ellipsoid(result, x, y, z)
    if result["model"] == "strip_profile":
        longitudinal, lateral = (y, x) if result["axis"] else (x, y)
        lo, hi = result["lateral"]
        return lo <= lateral <= hi and any(
            a <= longitudinal <= b and f <= z <= h
            for a, b, f, h in result["sections"]
        )
    if not result["floor"] <= z <= result["roof"]:
        return False
    points = result["local_outline"]
    inside = False
    for i, (ax, ay, _) in enumerate(points):
        bx, by, _ = points[i - 1]
        if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
            inside = not inside
    return inside
