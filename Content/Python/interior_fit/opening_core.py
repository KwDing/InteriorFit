"""Engine-independent aperture grid decomposition and geometric duplicate checks."""

import math


def _largest_on_row(heights, y, minimum_width, minimum_height):
    best = None
    stack = []
    for x in range(len(heights) + 1):
        height = heights[x] if x < len(heights) else 0
        start = x
        while stack and stack[-1][1] > height:
            left, h = stack.pop()
            start = left
            width = x - left
            if width >= minimum_width and h >= minimum_height:
                candidate = (width * h, left, y - h + 1, x, y + 1)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if not stack or stack[-1][1] < height:
            stack.append((start, height))
    return best


def rectangles(cells, columns, rows, minimum_width=2, minimum_height=3, limit=32):
    """Greedy maximum all-clear rectangles: never bridge a pillar or an opaque pane."""
    remaining = set(cells)
    result = []
    for _ in range(limit):
        heights = [0] * columns
        best = None
        for y in range(rows):
            for x in range(columns):
                heights[x] = heights[x] + 1 if (x, y) in remaining else 0
            candidate = _largest_on_row(heights, y, minimum_width, minimum_height)
            if candidate and (best is None or candidate[0] > best[0]):
                best = candidate
        if best is None:
            break
        _, left, bottom, right, top = best
        result.append((left, bottom, right, top))
        remaining.difference_update((x, y) for x in range(left, right) for y in range(bottom, top))
    return result


def overlap(a, b, plane_tolerance=80):
    angle = math.radians(a["yaw"])
    normal = [math.cos(angle), math.sin(angle)]
    other = math.radians(b["yaw"])
    if abs(normal[0] * math.cos(other) + normal[1] * math.sin(other)) < 0.94:
        return False
    delta = [b["center"][i] - a["center"][i] for i in range(3)]
    if abs(delta[0] * normal[0] + delta[1] * normal[1]) > plane_tolerance:
        return False
    lateral = abs(-delta[0] * normal[1] + delta[1] * normal[0])
    width = min(a["half_extent"][1] + b["half_extent"][1] - lateral, 2 * min(a["half_extent"][1], b["half_extent"][1]))
    height = min(
        a["half_extent"][2] + b["half_extent"][2] - abs(delta[2]), 2 * min(a["half_extent"][2], b["half_extent"][2])
    )
    smaller = min(a["half_extent"][1] * a["half_extent"][2], b["half_extent"][1] * b["half_extent"][2]) * 4
    return width > 0 and height > 0 and width * height / max(smaller, 1) > 0.45
