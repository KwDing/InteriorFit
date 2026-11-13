"""Build closed mesh buffers for stepped Room heightfields."""

# Each air span can be cut at shared height levels. Cap the resulting work.
MAX_HEIGHT_LEVELS = 192
MAX_SPAN_LEVEL_WORK = 360000


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
    """
    A watertight surface of neighboring air columns. Shared vertical edges
    use identical cuts.
    """
    columns = _merge_spans(result["height_cells"])
    cells = [(ij, bounds) for ij, spans in columns.items() for bounds in spans]
    levels = sorted({h for _, bounds in cells for h in bounds})
    if (
        len(levels) > MAX_HEIGHT_LEVELS
        or len(cells) * len(levels) > MAX_SPAN_LEVEL_WORK
    ):
        raise ValueError("Heightfield exceeds brush complexity budget")
    x, y = result["grid_origin"]
    step = result["step_cm"]
    corrections = {
        (axis, index): value
        for axis, index, value in result.get("boundary_planes", [])
    }
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
                if (
                    low < lo
                    or high > hi
                    or any(a <= low and high <= b for a, b in neighbors)
                ):
                    continue
                face([(*a, low), (*b, low), (*b, high), (*a, high)])
    return vertices, split_touching_edges(vertices, triangles, owners)


def split_touching_edges(vertices, triangles, owners):
    """
    Around an edge where two diagonal air columns touch, keep two distinct
    surface sheets.
    """
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
        raise ValueError(
            "Heightfield has an open surface; inspect these columns before "
            "creating a Room"
        )
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
                vertices.append(
                    tuple(
                        (x + y) * 0.5 for x, y in zip(vertices[a], vertices[b])
                    )
                )
            ring.append(midpoints[group])
        if len(ring) == 3:
            output.append(tri)
            continue
        center = len(vertices)
        vertices.append(
            tuple(sum(vertices[v][i] for v in tri) / 3 for i in range(3))
        )
        output.extend(
            (v, ring[(i + 1) % len(ring)], center) for i, v in enumerate(ring)
        )
    if any(
        n != 2
        for n in Counter(
            key(a, b) for tri in output for a, b in edges(tri)
        ).values()
    ):
        raise ValueError(
            "Ambiguous contact between storeys; split the selection before "
            "creating a Room"
        )
    return output
