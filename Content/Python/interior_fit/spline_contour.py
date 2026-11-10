"""Pure editor-time cell contour extraction; rejects holes/disconnected outlines."""

import math


def simplify(points, tolerance):
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx = bx - ax
    dy = by - ay

    def distance(p):
        t = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0
        return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)

    index = max(range(1, len(points) - 1), key=lambda i: distance(points[i]))
    if distance(points[index]) <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def _exterior_loop(occupied):
    edges = set()
    for x, y in occupied:
        corners = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            if (b, a) in edges:
                edges.remove((b, a))
            else:
                edges.add((a, b))
    following = {}
    for a, b in edges:
        if a in following:
            raise ValueError("Surface touches only at a corner; split or repair the selected water surface")
        following[a] = b
    loops = []
    while following:
        start = min(following)
        cursor = start
        loop = []
        while True:
            loop.append(cursor)
            if cursor not in following:
                raise ValueError("Open surface outline")
            cursor = following.pop(cursor)
            if cursor == start:
                break
        loops.append(loop)
    if len(loops) != 1:
        raise ValueError(
            "Selected surface has holes or disconnected pieces. Use separate simple splines or keep Grid Area; no holes will be silently filled."
        )
    return loops[0]


def lake_outline(cells, step, tolerance=30, max_points=256):
    if not cells or not math.isfinite(step) or step <= 0:
        raise ValueError("Invalid surface cells")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Invalid simplify tolerance")
    if max(p[2] for p in cells) - min(p[2] for p in cells) > 1:
        raise ValueError("Lake surface must be horizontal; use Line for sloped water")
    minx = min(p[0] for p in cells)
    miny = min(p[1] for p in cells)
    occupied = {(round((p[0] - minx) / step), round((p[1] - miny) / step)) for p in cells}
    loop = _exterior_loop(occupied)
    points = [(minx + (x - 0.5) * step, miny + (y - 0.5) * step) for x, y in loop]
    # Remove collinear samples before RDP to bound recursion on ordinary grids.
    points = [
        p
        for i, p in enumerate(points)
        if (p[0] - points[i - 1][0]) * (points[(i + 1) % len(points)][1] - p[1])
        != (p[1] - points[i - 1][1]) * (points[(i + 1) % len(points)][0] - p[0])
    ]
    split = max(range(1, len(points)), key=lambda i: math.dist(points[0], points[i]))
    result = simplify(points[: split + 1], tolerance)[:-1] + simplify(points[split:] + points[:1], tolerance)[:-1]
    if not 3 <= len(result) <= max_points:
        raise ValueError(f"Outline needs 3–{max_points} points; increase simplification tolerance or split the surface")
    return [(x, y, cells[0][2]) for x, y in result]


def simplify_path(points, tolerance, closed=False):
    """RDP in 3D; preserves open endpoints and the closed seam."""

    def reduce(part):
        if len(part) < 3:
            return part
        a = part[0]
        b = part[-1]
        delta = [b[i] - a[i] for i in range(3)]
        length = sum(d * d for d in delta)

        def distance(p):
            t = max(0, min(1, sum((p[i] - a[i]) * delta[i] for i in range(3)) / length)) if length else 0
            return math.sqrt(sum((p[i] - a[i] - t * delta[i]) ** 2 for i in range(3)))

        index = max(range(1, len(part) - 1), key=lambda i: distance(part[i]))
        if distance(part[index]) <= tolerance:
            return [a, b]
        return reduce(part[: index + 1])[:-1] + reduce(part[index:])

    if not closed:
        return reduce(points)
    split = max(range(1, len(points)), key=lambda i: math.dist(points[0], points[i]))
    return reduce(points[: split + 1])[:-1] + reduce(points[split:] + points[:1])[:-1]


def mesh_outline(edges, tolerance=30, max_points=8192):
    """Order one exact welded mesh boundary; never replace concavities with a hull."""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Invalid simplify tolerance")
    if not 3 <= len(edges) <= 8192:
        raise ValueError("Invalid mesh boundary edge count")
    adjacent = {}
    for a, b in edges:
        a = tuple(a)
        b = tuple(b)
        if len(a) != 3 or len(b) != 3 or not all(math.isfinite(v) for v in a + b) or a == b:
            raise ValueError("Invalid mesh edge")
        adjacent.setdefault(a, set()).add(b)
        adjacent.setdefault(b, set()).add(a)
    if any(len(neighbors) != 2 for neighbors in adjacent.values()):
        raise ValueError("Mesh outline branches or is open; select a clean water sheet")
    start = min(adjacent)
    points = [start]
    previous = start
    cursor = min(adjacent[start])
    while cursor != start:
        if len(points) >= len(adjacent):
            raise ValueError("Invalid mesh loop")
        points.append(cursor)
        following = next(p for p in adjacent[cursor] if p != previous)
        previous, cursor = cursor, following
    if len(points) != len(adjacent):
        raise ValueError("Water has holes or disconnected pieces; use separate simple splines")
    if max(p[2] for p in points) - min(p[2] for p in points) > 1:
        raise ValueError("Lake must be horizontal")
    result = simplify_path(points, tolerance, True)
    if not 3 <= len(result) <= max_points:
        raise ValueError("Outline collapsed or exceeds point budget; adjust tolerance")
    # Detect crossings introduced by aggressive simplification (or overlapping source meshes).
    validate_simple_outline(result)
    return result


def validate_simple_outline(points):
    def turn(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, c):
        return (
            min(a[0], b[0]) - 1e-7 <= c[0] <= max(a[0], b[0]) + 1e-7
            and min(a[1], b[1]) - 1e-7 <= c[1] <= max(a[1], b[1]) + 1e-7
        )

    if len(points) > 2048:
        raise ValueError("Outline too detailed for topology validation; increase simplification tolerance")
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        for j in range(i + 2, len(points)):
            if i == 0 and j == len(points) - 1:
                continue
            c = points[j]
            d = points[(j + 1) % len(points)]
            if (
                max(a[0], b[0]) < min(c[0], d[0])
                or max(c[0], d[0]) < min(a[0], b[0])
                or max(a[1], b[1]) < min(c[1], d[1])
                or max(c[1], d[1]) < min(a[1], b[1])
            ):
                continue
            values = (turn(a, b, c), turn(a, b, d), turn(c, d, a), turn(c, d, b))
            if (values[0] * values[1] < 0 and values[2] * values[3] < 0) or any(
                abs(v) < 1e-7 and on_segment(x, y, z)
                for v, x, y, z in zip(values, (a, a, c, c), (b, b, d, d), (c, d, a, b))
            ):
                raise ValueError("Outline intersects itself; reduce tolerance or repair the source water sheet")
