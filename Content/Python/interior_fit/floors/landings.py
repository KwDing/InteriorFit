from ..rooms.rays import STEP

LANDING_REACH_CM = 160


def isolate_flights(graph, start):
    """Keep graded walking paths, their landings, and the piece connected to this seed."""
    core = set()
    for mid, adjacent in graph.items():
        lower = [p for p in adjacent if mid[2] - p[2] >= 10]
        higher = [p for p in adjacent if p[2] - mid[2] >= 10]
        for low in lower:
            for high in higher:
                if high[:2] != low[:2] and high[2] - low[2] >= 30:
                    core.update((low, mid, high))
    if not core:
        raise ValueError("这里仅发现同层地面，没有连续升降的踏步；请在楼梯口放种子")

    # Distance is walked on verified edges. A tread directly overhead is not a neighbor.
    kept = set(core)
    frontier = core
    for _ in range(LANDING_REACH_CM // STEP):
        frontier = {n for p in frontier for n in graph[p]} - kept
        kept.update(frontier)
    if start not in kept:
        raise ValueError("种子位于平层大厅，请在第一段踏步旁的平台放种子")
    connected = {start}
    frontier = {start}
    while frontier:
        frontier = {n for p in frontier for n in graph[p] if n in kept} - connected
        connected.update(frontier)
    return connected


def _patch_heights(graph, kept, corner, base):
    """A landing has four walkable corners joined by edges at nearly the same height."""
    adjacent = [p for p in graph[corner] if p in kept and abs(corner[2] - p[2]) <= 8]
    east = [p for p in adjacent if p[0] == corner[0] + 1]
    north = [p for p in adjacent if p[1] == corner[1] + 1]
    for right in east:
        for upper in north:
            for opposite in graph[right].intersection(graph[upper], kept):
                if opposite[:2] != (right[0], upper[1]):
                    continue
                levels = (corner[2], right[2], upper[2], opposite[2])
                if max(levels) - min(levels) <= 8:
                    yield round(base + sum(levels) / 4)


def landing_pair(graph, kept, base, seed_height):
    """Find two reachable, roughly flat 2x2 patches at least 220 cm apart in Z."""
    heights = set()
    for a in kept:
        heights.update(_patch_heights(graph, kept, a, base))
    if not heights:
        return []
    near = min(heights, key=lambda h: (abs(h - seed_height), h))
    others = [h for h in heights if abs(h - near) >= 220]
    return sorted((near, min(others, key=lambda h: (abs(h - near), h)))) if others else []
