"""Fit a closed ellipsoid cap to shell measurements."""

import math
import random

from interior_fit.rooms.geometry.compute_ellipsoid_cap_hull import staggered
from ..frame import dot
from ..geometry.check_closed_convex_hull import is_convex
from ..geometry.solve_linear_system import solve
from interior_fit.rooms.geometry.build_roof_mesh import dense_ellipsoid


# Scale world centimeters before the polynomial solve, then convert the
# fitted center, radii and gradient-based residuals back to centimeters.
FIT_SCALE_CM = 500
MIN_GRADIENT_LENGTH = 1e-6
SHELL_RESIDUAL_TOLERANCE_CM = 6
MIN_SURFACE_NORMAL_DOT = 0.94
MIN_AXIS_RADIUS_CM = 80
MAX_AXIS_RADIUS_CM = 1800
ELLIPSOID_FIT_RANDOM_SEED = 2971
MAX_FIT_TRIALS = 32
SAMPLES_PER_TRIAL = 9
FIT_EARLY_ACCEPT_FRACTION = 0.96
MIN_TRAIN_INLIER_FRACTION = 0.84
MIN_TEST_INLIER_FRACTION = 0.82


def _feature(p):
    x, y, z = (v / FIT_SCALE_CM for v in p)
    return (x * x, x * y, y * y, x, y, 1, z), z * z


def _coefficients(samples):
    rows, values = zip(*[_feature(p) for p, n in samples])
    cols = list(zip(*rows))
    return solve(
        [[dot(a, b) for b in cols] for a in cols],
        [dot(a, values) for a in cols],
    )


def _inlier(coeff, p, normal):
    row, value = _feature(p)
    a, b, c, d, e, _, g = coeff
    x, y, z = (v / FIT_SCALE_CM for v in p)
    grad = (2 * a * x + b * y + d, b * x + 2 * c * y + e, g - 2 * z)
    length = math.sqrt(dot(grad, grad))
    return (
        length > MIN_GRADIENT_LENGTH
        and abs(dot(row, coeff) - value) * FIT_SCALE_CM
        < SHELL_RESIDUAL_TOLERANCE_CM * length
        and dot(grad, normal) > MIN_SURFACE_NORMAL_DOT * length
    )


def _axes(coeff):
    a, b, c, d, e, f, g = coeff
    center = solve([[-2 * a, -b], [-b, -2 * c]], [d, e])
    if not center:
        return None
    x, y = center
    z = g / 2
    height2 = f + (x * d + y * e) / 2 + z * z
    mid, delta = -(a + c) / 2, math.hypot(a - c, b) / 2
    if mid - delta <= 0 or height2 <= z * z:
        return None
    radii = [
        FIT_SCALE_CM * math.sqrt(height2 / k)
        for k in (mid + delta, mid - delta, 1)
    ]
    if min(radii) < MIN_AXIS_RADIUS_CM or max(radii) > MAX_AXIS_RADIUS_CM:
        return None
    return (
        (FIT_SCALE_CM * x, FIT_SCALE_CM * y, FIT_SCALE_CM * z),
        radii,
        math.atan2(-b, c - a) / 2,
    )


def fit(frame, train, test, triangle_budget=None):
    rng = random.Random(ELLIPSOID_FIT_RANDOM_SEED)
    best = []
    for _ in range(MAX_FIT_TRIALS):
        coeff = _coefficients(rng.sample(train, SAMPLES_PER_TRIAL))
        if not coeff or not _axes(coeff):
            continue
        support = [s for s in train if _inlier(coeff, *s)]
        if len(support) > len(best):
            best = support
        if len(best) >= FIT_EARLY_ACCEPT_FRACTION * len(train):
            break
    if len(best) < MIN_TRAIN_INLIER_FRACTION * len(train):
        return None
    coeff = _coefficients(best)
    axes = _axes(coeff) if coeff else None
    if axes and sum(
        _inlier(coeff, *s) for s in test
    ) >= MIN_TEST_INLIER_FRACTION * len(test):
        if triangle_budget is not None:
            from ..geometry import (
                mesh_ellipsoid_cap_with_polybudget as budget_cap,
            )

            if isinstance(triangle_budget, dict):
                from ..room_budget import cap_target

                triangle_budget = min(
                    cap_target(axes[0], axes[1], triangle_budget),
                    triangle_budget.get("cap_max", 48),
                )
            return budget_cap.build(frame, *axes, triangle_budget)
        return ellipsoid(frame, *axes)


def ellipsoid(frame, center, radii, theta):
    # Outside the tested dome/cut-sphere envelope keep the original
    # tessellation.
    ratio = center[2] / radii[2]
    if (
        -0.08 <= ratio <= 0.55
        and max(radii) <= 650
        and max(radii) <= 2.35 * min(radii)
    ):
        cap = staggered(frame, center, radii, theta, chord_cm=3.0)
        if is_convex(cap):
            return cap
    return dense_ellipsoid(frame, center, radii, theta)
