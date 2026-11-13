"""Queries for planar outlines."""

import math


def closest_edge(ring, point):
    candidates = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        t = max(
            0,
            min(
                1,
                ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy)
                / (length * length),
            ),
        )
        foot = a[0] + t * dx, a[1] + t * dy
        candidates.append(
            (math.dist(point, foot), foot, (-dy / length, dx / length))
        )
    return min(candidates, key=lambda item: item[0])
