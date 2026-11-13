"""Fit a floor-clipped spherical Room from surface measurements."""

import math
import random
from interior_fit.rooms.ray_queries import RayHitField


# Fixed sampling seed makes repeated fits over the same evidence reproducible.
MIN_SPHERE_PIVOT = 0.001
SPHERE_FIT_RANDOM_SEED = 731
MIN_SPHERE_RADIUS_CM = 100
MAX_SPHERE_RADIUS_CM = 1800
SPHERE_TRACE_RANGE_CM = 2400


def sphere_through(points):
    """
    Subtract the first sphere equation from the other three and solve for
    center.
    """
    origin = points[0]
    matrix = []
    for p in points[1:]:
        delta = [a - b for a, b in zip(p, origin)]
        matrix.append([*delta, sum(v * v for v in delta) / 2])
    for i in range(3):
        pivot = max(range(i, 3), key=lambda j: abs(matrix[j][i]))
        if abs(matrix[pivot][i]) < MIN_SPHERE_PIVOT:
            return None
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        divisor = matrix[i][i]
        matrix[i] = [v / divisor for v in matrix[i]]
        for j in range(3):
            if j != i:
                factor = matrix[j][i]
                matrix[j] = [
                    a - factor * b for a, b in zip(matrix[j], matrix[i])
                ]
    center = tuple(origin[i] + matrix[i][-1] for i in range(3))
    return center, math.dist(center, origin)


class UnsupportedSphereError(ValueError):
    pass


def _fit_sphere(samples):
    rng = random.Random(SPHERE_FIT_RANDOM_SEED)
    candidates = []
    for _ in range(80):
        model = sphere_through([p for p, n in rng.sample(samples, 4)])
        if (
            not model
            or not MIN_SPHERE_RADIUS_CM < model[1] < MAX_SPHERE_RADIUS_CM
        ):
            continue
        center, radius = model
        residuals = [abs(math.dist(p, center) - radius) for p, n in samples]
        inliers = [
            err
            for err, (p, n) in zip(residuals, samples)
            if err < 8
            and sum((c - v) * k for c, v, k in zip(center, p, n))
            > 0.94 * radius
        ]
        candidates.append((len(inliers), -sum(inliers), center, radius))
    if not candidates:
        raise UnsupportedSphereError("No spherical shell supported")
    count, _, center, radius = max(candidates)
    if count < max(78, 0.88 * len(samples)) or abs(center[2]) >= radius:
        raise UnsupportedSphereError(
            "Curved shell lacks consistent spherical evidence"
        )
    return count, center, radius


def spherical_room(frame, seed, query):
    rays = []
    for elevation in (-15, 5, 30, 55, 75):
        tilt = math.radians(elevation)
        for i in range(24):
            a = i * math.tau / 24
            direction = (
                math.cos(a) * math.cos(tilt),
                math.sin(a) * math.cos(tilt),
                math.sin(tilt),
            )
            tip = tuple(
                v + SPHERE_TRACE_RANGE_CM * d
                for v, d in zip(frame.local(seed), direction)
            )
            rays.append((seed, frame.world(tip)))
    hits = yield from query(rays)
    samples = [
        (
            frame.local(hit[RayHitField.POINT]),
            frame.direction(hit[RayHitField.NORMAL]),
        )
        for hit in hits
        if hit and frame.direction(hit[RayHitField.NORMAL])[2] < 0.90
    ]
    if len(samples) < 80:
        raise UnsupportedSphereError(
            "Insufficient angular coverage for a sphere"
        )
    count, center, radius = _fit_sphere(samples)
    ring = math.sqrt(radius**2 - center[2] ** 2)
    outline = [
        (
            center[0] + ring * math.cos(i * math.tau / 48),
            center[1] + ring * math.sin(i * math.tau / 48),
            0,
        )
        for i in range(48)
    ]
    return dict(
        model="floor_clipped_sphere",
        sphere_center=center,
        radius=radius,
        inliers=count,
        local_outline=outline,
        outline=[frame.world(p) for p in outline],
        axis_z=frame.z,
        axis_x=frame.x,
        origin=frame.origin,
        seed=seed,
        floor=0,
        roof=center[2] + radius,
        rays=len(rays),
        columns=0,
    )
