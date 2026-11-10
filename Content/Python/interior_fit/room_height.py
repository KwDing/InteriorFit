"""Alternative three-dimensional models for connected changes in height and curved shells."""

import math
import random


def sphere_through(points):
    """Subtract the first sphere equation from the other three and solve for center."""
    origin = points[0]
    matrix = []
    for p in points[1:]:
        delta = [a - b for a, b in zip(p, origin)]
        matrix.append([*delta, sum(v * v for v in delta) / 2])
    for i in range(3):
        pivot = max(range(i, 3), key=lambda j: abs(matrix[j][i]))
        if abs(matrix[pivot][i]) < 0.001:
            return None
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        divisor = matrix[i][i]
        matrix[i] = [v / divisor for v in matrix[i]]
        for j in range(3):
            if j != i:
                factor = matrix[j][i]
                matrix[j] = [a - factor * b for a, b in zip(matrix[j], matrix[i])]
    center = tuple(origin[i] + matrix[i][-1] for i in range(3))
    return center, math.dist(center, origin)


class SphereUnsupported(ValueError):
    pass


def _fit_sphere(samples):
    rng = random.Random(731)
    candidates = []
    for _ in range(80):
        model = sphere_through([p for p, n in rng.sample(samples, 4)])
        if not model or not 100 < model[1] < 1800:
            continue
        center, radius = model
        residuals = [abs(math.dist(p, center) - radius) for p, n in samples]
        inliers = [
            err
            for err, (p, n) in zip(residuals, samples)
            if err < 8 and sum((c - v) * k for c, v, k in zip(center, p, n)) > 0.94 * radius
        ]
        candidates.append((len(inliers), -sum(inliers), center, radius))
    if not candidates:
        raise SphereUnsupported("No spherical shell supported")
    count, _, center, radius = max(candidates)
    if count < max(78, 0.88 * len(samples)) or abs(center[2]) >= radius:
        raise SphereUnsupported("Curved shell lacks consistent spherical evidence")
    return count, center, radius


def spherical_room(frame, seed, query):
    rays = []
    for elevation in (-15, 5, 30, 55, 75):
        tilt = math.radians(elevation)
        for i in range(24):
            a = i * math.tau / 24
            direction = (math.cos(a) * math.cos(tilt), math.sin(a) * math.cos(tilt), math.sin(tilt))
            tip = tuple(v + 2400 * d for v, d in zip(frame.local(seed), direction))
            rays.append((seed, frame.world(tip)))
    hits = yield from query(rays)
    samples = [
        (frame.local(hit[0]), frame.direction(hit[1])) for hit in hits if hit and frame.direction(hit[1])[2] < 0.90
    ]
    if len(samples) < 80:
        raise SphereUnsupported("Insufficient angular coverage for a sphere")
    count, center, radius = _fit_sphere(samples)
    ring = math.sqrt(radius**2 - center[2] ** 2)
    outline = [
        (center[0] + ring * math.cos(i * math.tau / 48), center[1] + ring * math.sin(i * math.tau / 48), 0)
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


def _merge_spans(height_cells):
    columns = {}
    for i, j, lo, hi in height_cells:
        columns.setdefault((i, j), []).append((lo, hi))
    for key, spans in columns.items():
        merged = []
        for lo, hi in sorted(spans):
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        columns[key] = merged
    return columns


def surface_buffers(result):
    """A watertight surface of neighboring air columns. Shared vertical edges use identical cuts."""
    columns = _merge_spans(result["height_cells"])
    cells = [(ij, bounds) for ij, spans in columns.items() for bounds in spans]
    levels = sorted({h for _, bounds in cells for h in bounds})
    if len(levels) > 192 or len(cells) * len(levels) > 360000:
        raise ValueError("Heightfield exceeds brush complexity budget")
    x, y = result["grid_origin"]
    step = result["step_cm"]
    corrections = {(axis, index): value for axis, index, value in result.get("boundary_planes", [])}
    vertices, indices, triangles = [], {}, []
    owners = []

    def face(corners):
        ids = []
        for ci, cj, h in corners:
            key = (ci, cj, h)
            if key not in indices:
                indices[key] = len(vertices)
                vertices.append(
                    (
                        corrections.get(("x", ci), x + (ci - 0.5) * step),
                        corrections.get(("y", cj), y + (cj - 0.5) * step),
                        h,
                    )
                )
            ids.append(indices[key])
        triangles.extend([(ids[0], ids[2], ids[1]), (ids[0], ids[3], ids[2])])
        owners.extend([(i, j), (i, j)])

    for (i, j), (lo, hi) in cells:
        corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
        face([(a, b, lo) for a, b in reversed(corners)])
        face([(a, b, hi) for a, b in corners])
        for k, (di, dj) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
            neighbors = columns.get((i + di, j + dj), [])
            if (lo, hi) in neighbors:
                continue
            a, b = corners[k], corners[(k + 1) % 4]
            for low, high in zip(levels, levels[1:]):
                if low < lo or high > hi or any(a <= low and high <= b for a, b in neighbors):
                    continue
                face([(*a, low), (*b, low), (*b, high), (*a, high)])
    return vertices, split_touching_edges(vertices, triangles, owners)


def align_outer_edges(walls, reached, x, y, step):
    """Snap only outer lattice lines supported by multiple near-axis wall returns."""
    corrections = []
    for axis, coord, origin in (("x", 0, x), ("y", 1, y)):
        ids = [cell[coord] for cell in reached]
        for index, sign in ((min(ids), 1), (max(ids) + 1, -1)):
            edge = origin + (index - 0.5) * step
            values = sorted(
                p[coord] for n, p in walls if n[coord] * sign > 0.9995 and abs(p[coord] - edge) < step * 0.48
            )
            if len(values) >= 3 and values[-1] - values[0] < 3:
                corrections.append((axis, index, values[len(values) // 2]))
    return corrections


def split_touching_edges(vertices, triangles, owners):
    """Around an edge where two diagonal air columns touch, keep two distinct surface sheets."""
    from collections import Counter

    def edges(triangle):
        a, b, c = triangle
        return ((a, b), (b, c), (c, a))

    def key(a, b):
        return (a, b) if a < b else (b, a)

    counts = Counter(key(a, b) for tri in triangles for a, b in edges(tri))
    if all(n == 2 for n in counts.values()):
        return triangles
    if any(n not in (2, 4) for n in counts.values()):
        raise ValueError("Heightfield has an open surface; inspect these columns before creating a Room")
    midpoints = {}
    output = []
    for tri, cell in zip(triangles, owners):
        ring = []
        for a, b in edges(tri):
            ring.append(a)
            e = key(a, b)
            if counts[e] != 4:
                continue
            group = e, cell
            if group not in midpoints:
                midpoints[group] = len(vertices)
                vertices.append(tuple((x + y) * 0.5 for x, y in zip(vertices[a], vertices[b])))
            ring.append(midpoints[group])
        if len(ring) == 3:
            output.append(tri)
            continue
        center = len(vertices)
        vertices.append(tuple(sum(vertices[v][i] for v in tri) / 3 for i in range(3)))
        output.extend((v, ring[(i + 1) % len(ring)], center) for i, v in enumerate(ring))
    if any(n != 2 for n in Counter(key(a, b) for tri in output for a, b in edges(tri)).values()):
        raise ValueError("Ambiguous contact between storeys; split the selection before creating a Room")
    return output
