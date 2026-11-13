"""Sample shell evidence and select a closed Room candidate."""

import math

from interior_fit.rooms.fitting import ellipsoid, gable
from interior_fit.rooms.ray_queries import RayHitField, query

# Used by the demo's legacy shape diagnostics.
_ridge = gable.fit


# The shell survey fits the roof; separate short floor rays validate closure.
SHELL_TRACE_RANGE_CM = 2600
SHELL_SAMPLES_PER_RING = 16
MIN_SHELL_HITS = 53
FLOOR_CHECK_SAMPLES = 10
FLOOR_CHECK_START_CM = 70
FLOOR_CHECK_END_CM = -30
FLOOR_HEIGHT_TOLERANCE_CM = 4
FLOOR_NORMAL_MIN_Z = 0.98


def fit(frame, seed, triangle_budget=None):
    origin = frame.local(seed)
    rays = []
    for j, tilt in enumerate((-12, 5, 29, 53, 75)):
        elevation = math.radians(tilt)
        for i in range(SHELL_SAMPLES_PER_RING):
            angle = math.tau * (i + 0.31 * j) / SHELL_SAMPLES_PER_RING
            v = (
                math.cos(angle) * math.cos(elevation),
                math.sin(angle) * math.cos(elevation),
                math.sin(elevation),
            )
            rays.append(
                (
                    seed,
                    frame.world(
                        tuple(
                            a + SHELL_TRACE_RANGE_CM * b
                            for a, b in zip(origin, v)
                        )
                    ),
                )
            )
    hits = yield from query(rays)
    samples = [
        (
            frame.local(h[RayHitField.POINT]),
            frame.direction(h[RayHitField.NORMAL]),
        )
        for h in hits
        if h and frame.direction(h[RayHitField.NORMAL])[2] < 0.85
    ]
    train = [s for i, s in enumerate(samples) if i % 4]
    test = samples[::4]
    if len(samples) < MIN_SHELL_HITS:
        return None
    groups = gable.group_planes(train)
    candidate = gable.fit(frame, train, test, groups)
    if not candidate:
        candidate = yield from gable.confirm_sparse_gable(
            frame, train, test, groups
        )
    if not candidate:
        candidate = ellipsoid.fit(frame, train, test, triangle_budget)
    if not candidate:
        return None
    ring = candidate["local_outline"]
    # The shell equations do not guarantee a level floor. Check below the
    # measured seed plane at distinct positions before closing it with one
    # face.
    points = ring[:: max(1, len(ring) // FLOOR_CHECK_SAMPLES)]
    if "triangle_budget" in candidate:
        # Coarse, volume-balanced corners can extend past the physical floor.
        # Validate the measured building independently of the rendering budget.
        cx, cy, cz = candidate["center"]
        a, b, h = candidate["radii"]
        yaw = candidate["yaw_radians"]
        scale = math.sqrt(1 - (cz / h) ** 2)
        points = []
        for i in range(FLOOR_CHECK_SAMPLES):
            angle = i * math.tau / FLOOR_CHECK_SAMPLES
            x, y = a * scale * math.cos(angle), b * scale * math.sin(angle)
            points.append(
                (
                    cx + x * math.cos(yaw) - y * math.sin(yaw),
                    cy + x * math.sin(yaw) + y * math.cos(yaw),
                    0,
                )
            )
    floors = yield from query(
        [
            (
                frame.world((x * 0.65, y * 0.65, FLOOR_CHECK_START_CM)),
                frame.world((x * 0.65, y * 0.65, FLOOR_CHECK_END_CM)),
            )
            for x, y, _ in points
        ]
    )
    if all(
        h
        and abs(frame.local(h[RayHitField.POINT])[2])
        < FLOOR_HEIGHT_TOLERANCE_CM
        and frame.direction(h[RayHitField.NORMAL])[2] > FLOOR_NORMAL_MIN_Z
        for h in floors
    ):
        if candidate["model"] == "ellipsoid_cap" and triangle_budget is None:
            from interior_fit.rooms.simplify_hull_within_bounds import (
                simplify_hull_within_bounds,
            )

            return (
                yield from simplify_hull_within_bounds(frame, candidate, hits)
            )
        return candidate
