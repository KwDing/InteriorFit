"""Extract and simplify connected river branches on a sampled surface grid."""

from collections import defaultdict
from ..spline_contour import simplify_path

RING = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))


def thin(mask):
    """Two-phase Zhang-Suen thinning on the selected river's raster footprint."""
    mask = set(mask)
    while True:
        removed = 0
        for phase in (0, 1):
            trim = []
            for x, y in mask:
                n = [(x + i, y + j) in mask for i, j in RING]
                if not 2 <= sum(n) <= 6 or sum(not a and b for a, b in zip(n, n[1:] + n[:1])) != 1:
                    continue
                north, east, south, west = n[::2]
                protected = (east and south and (north or west)) if phase == 0 else (north and west and (east or south))
                if not protected:
                    trim.append((x, y))
            mask.difference_update(trim)
            removed += len(trim)
        if not removed:
            return mask


def river_paths(data):
    step = data["cell_size"]
    cells = {(round(x / step - 0.5), round(y / step - 0.5)): (x, y, z) for x, y, z in data["cells"]}
    skeleton = thin(cells)
    graph = defaultdict(set)
    for x, y in skeleton:
        for dx, dy in RING:
            other = (x + dx, y + dy)
            if other not in skeleton:
                continue
            if dx and dy and ((x + dx, y) in skeleton or (x, y + dy) in skeleton):
                continue
            graph[x, y].add(other)
    nodes = {p for p, adj in graph.items() if len(adj) != 2}
    if len(nodes) < 2:
        raise ValueError("No open river branches at this sampling scale")
    used = set()
    paths = []

    def edge(a, b):
        return tuple(sorted((a, b)))

    for node in sorted(nodes):
        for nxt in sorted(graph[node]):
            if edge(node, nxt) in used:
                continue
            path = [node, nxt]
            used.add(edge(node, nxt))
            while path[-1] not in nodes:
                p = path[-1]
                q = next(iter(graph[p] - {path[-2]}))
                used.add(edge(p, q))
                path.append(q)
            # Only prune tiny terminal whiskers, retain junction-to-junction connections.
            if len(path) <= 3 and (len(graph[node]) == 1 or len(graph[path[-1]]) == 1):
                continue
            points = [tuple(a + b for a, b in zip(cells[p], data["origin"])) for p in path]
            paths.append(simplify_path(points, step * 0.65))
    if not paths:
        raise ValueError("No usable river centerline")
    return paths
