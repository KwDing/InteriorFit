"""Verify overlapping flights; emit connectivity evidence, never tread geometry.

An upper flight can hide a lower flight at the same XY. Recast below each hit,
then verify standing clearance and horizontal obstruction using real collision.
The enclosing prism remains the acoustic Room; this graph is authoring-only.
"""
from collections import Counter
from ..rooms.rays import query

MIN_CLEARANCE_CM = 155
MAX_LAYERS = 6
MAX_NEIGHBOR_RISE_CM = 110


def cast(rays, stats):
    stats['rays'] += len(rays)
    return (yield from query(rays))


def collect(points, first_hits, frame, floor, stats):
    """Retain separate walkable surfaces at one XY, with bounded depth peeling."""
    layers = {key: [] for key in points}
    active = dict(zip(points, first_hits))
    for _ in range(MAX_LAYERS):
        next_starts = {}
        for key, hit in active.items():
            if not hit or frame.direction(hit[1])[2] <= .6:
                continue
            height = frame.local(hit[0])[2]
            if height < floor - 2 or (layers[key] and height >= layers[key][-1] - 1):
                continue
            layers[key].append(height)
            start = height - MIN_CLEARANCE_CM
            if start > floor + 1:
                next_starts[key] = start
        if not next_starts:
            break
        rays = [(frame.world((*points[key], height)), frame.world((*points[key], floor - 12)))
                for key, height in next_starts.items()]
        active = dict(zip(next_starts, (yield from cast(rays, stats))))
    return layers


def standing_nodes(points, layers, frame, stats):
    """Reject under-stair voids with insufficient headroom; don't ignore stairs."""
    candidates = {(i, j, k): height for (i, j), values in layers.items() for k, height in enumerate(values)}
    rays = [(frame.world((*points[key[:2]], height + 8)),
             frame.world((*points[key[:2]], height + MIN_CLEARANCE_CM)))
            for key, height in candidates.items()]
    blocked = yield from cast(rays, stats)
    return {key: height for (key, height), hit in zip(candidates.items(), blocked) if not hit}


def neighbors(nodes):
    """Four-neighbor XY graph with distinct nodes for each vertical layer."""
    by_column = {}
    for key in nodes:
        by_column.setdefault(key[:2], []).append(key)
    for a in nodes:
        for dx, dy in ((1, 0), (0, 1)):
            for b in by_column.get((a[0] + dx, a[1] + dy), []):
                if abs(nodes[a] - nodes[b]) <= MAX_NEIGHBOR_RISE_CM:
                    yield a, b


def reachable(graph, start):
    visited, frontier = {start}, {start}
    while frontier:
        frontier = {b for a in frontier for b in graph[a]} - visited
        visited.update(frontier)
    return visited


def connected(points, nodes, frame, seed, stats):
    if not nodes:
        raise ValueError('楼梯多层探测没有足够净空的踏面')
    edges = list(neighbors(nodes))
    rays = [(frame.world((*points[a[:2]], max(nodes[a], nodes[b]) + 100)),
             frame.world((*points[b[:2]], max(nodes[a], nodes[b]) + 100))) for a, b in edges]
    blocked = yield from cast(rays, stats)
    graph = {key: set() for key in nodes}
    for (a, b), hit in zip(edges, blocked):
        if not hit:
            graph[a].add(b)
            graph[b].add(a)
    local_seed = frame.local(seed)
    eligible = [key for key, height in nodes.items() if 0 <= local_seed[2] - height <= 160]
    if not eligible:
        raise ValueError('楼梯多层采样未连接到起点所在高度')
    start = min(eligible, key=lambda k: sum((points[k[:2]][i] - local_seed[i]) ** 2 for i in (0, 1)))
    anchor = frame.world((*points[start[:2]], nodes[start] + 100))
    if (yield from cast([(seed, anchor)], stats))[0]:
        raise ValueError('起点与楼梯多层采样之间存在实体遮挡')
    reached = reachable(graph, start)
    levels = Counter(round(nodes[key] / 10) * 10 for key in reached)
    landings = [z for z, count in levels.items() if count >= 2]
    if len(landings) < 2 or max(landings) - min(landings) < 220 or len(levels) < 4:
        raise ValueError('多层探测未证实跨层连续通路')
    return [min(landings), max(landings)], len(reached)


def verify(points, first_hits, frame, floor, seed, stats):
    layers = yield from collect(points, first_hits, frame, floor, stats)
    nodes = yield from standing_nodes(points, layers, frame, stats)
    levels, reached = yield from connected(points, nodes, frame, seed, stats)
    return levels, dict(columns=len(points), walkable_nodes=len(nodes), reached_nodes=reached,
                        maximum_layers=max(map(len, layers.values()), default=0))
