from collections import defaultdict
from .rooms.rays import NEIGHBORS, query, STEP
from .floors.landings import isolate_flights, landing_pair, LANDING_REACH_CM

MAX_STATES = 2400


def nearby_flights(seed):
    """Use structural flight bounds to stop a landing from flooding a whole storey."""
    import re
    import unreal as u

    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    flights = []
    for actor in actors.get_all_level_actors():
        if not isinstance(actor, u.StaticMeshActor):
            continue
        mesh = actor.static_mesh_component.static_mesh
        if not mesh:
            continue
        tokens = re.split(r"[^a-z]+", mesh.get_name().lower())
        if not {"stairs", "stair", "staircase"}.intersection(tokens) or {
            "rail",
            "railing",
            "trim",
            "handle",
        }.intersection(tokens):
            continue
        center, extent = actor.get_actor_bounds(True)
        if extent.z < 30 or abs(center.x - seed[0]) > 1800 or abs(center.y - seed[1]) > 1800:
            continue
        flights.append(tuple((c - e, c + e) for c, e in zip(center.to_tuple(), extent.to_tuple())))

    def gaps(a, b):
        return [max(0, lo - end, start - hi) for (lo, hi), (start, end) in zip(a, b)]

    point = tuple((v, v) for v in seed)
    group = [box for box in flights if all(g <= limit for g, limit in zip(gaps(box, point), (100, 100, 135)))]
    for member in group:
        for box in flights:
            if box not in group and all(g <= limit for g, limit in zip(gaps(box, member), (160, 160, 45))):
                group.append(box)
    return group


def _candidate_parents(frontier, x, y, flights):
    parents = {}
    for a in frontier:
        i, j, lo = a
        for di, dj in NEIGHBORS:
            key = (i + di, j + dj, lo)
            px, py = x + key[0] * STEP, y + key[1] * STEP
            # Loose search bounds only; measured changes of elevation determine ownership.
            if flights and not any(
                b[0][0] - 240 <= px <= b[0][1] + 240 and b[1][0] - 240 <= py <= b[1][1] + 240 for b in flights
            ):
                continue
            parents.setdefault(key, []).append(a)
    return parents


def _sample_treads(fresh, sampled, x, y, base, band):
    rays = []
    for i, j, lo in fresh:
        px, py = x + i * STEP, y + j * STEP
        rays.append(((px, py, base + lo + 45), (px, py, base + lo - 45)))
    floors = yield from query(rays)
    count = len(rays)
    candidates = []
    for key, hit in zip(fresh, floors):
        sampled[key] = None
        if hit and hit[1][2] > 0.55 and abs(band(hit[0][2]) - key[2]) <= 40:
            candidates.append((key, band(hit[0][2])))
    rays = []
    for (i, j, _), lo in candidates:
        px, py = x + i * STEP, y + j * STEP
        rays.append(((px, py, base + lo + 110), (px, py, base + lo + 950)))
    caps = yield from query(rays)
    count += len(rays)
    for (key, lo), hit in zip(candidates, caps):
        if hit and hit[1][2] < -0.45 and band(hit[0][2]) - lo >= 155:
            sampled[key] = ((key[0], key[1], lo), band(hit[0][2]))
    return count


def _connect_treads(parents, sampled, tested_edges, graph, spans, x, y, base):
    edges, rays = [], []
    for key, previous in parents.items():
        found = sampled[key]
        if not found:
            continue
        b, hi = found
        for a in previous:
            pair = tuple(sorted((a, b)))
            if pair in tested_edges:
                continue
            tested_edges.add(pair)
            low = max(a[2], b[2])
            ceiling = min(spans[a], hi)
            if ceiling - low < 150:
                continue
            # A head-height ray catches solid partitions; the upper ray catches a door lintel.
            for h in (low + 100, ceiling - 22):
                rays.append(
                    ((x + a[0] * STEP, y + a[1] * STEP, base + h), (x + b[0] * STEP, y + b[1] * STEP, base + h))
                )
            edges.append((a, b, hi))
    walls = yield from query(rays)
    count = len(rays)
    frontier = []
    for k, (a, b, hi) in enumerate(edges):
        if walls[2 * k] or walls[2 * k + 1]:
            continue
        graph[a].add(b)
        graph[b].add(a)
        if b not in spans:
            spans[b] = hi
            frontier.append(b)
    return frontier, count


def scan_layers(seed):
    flights = nearby_flights(seed)
    x, y, z = seed
    (bottom,) = yield from query([(seed, (x, y, z - 480))])
    if not bottom or bottom[1][2] < 0.55:
        raise ValueError("楼梯种子下方缺少可踩踏面")
    base = bottom[0][2]
    (cap,) = yield from query([((x, y, base + 105), (x, y, base + 950))])
    if not cap or cap[1][2] > -0.45 or cap[0][2] - base < 155:
        raise ValueError("起点缺少封顶或可通行净高")

    def band(h):
        return round((h - base) / 5) * 5

    start = (0, 0, band(base))
    spans = {start: band(cap[0][2])}
    frontier = [start]
    graph = defaultdict(set)
    tested_edges = set()
    sampled = {}
    count = 2
    while frontier:
        parents = _candidate_parents(frontier, x, y, flights)
        fresh = [key for key in parents if key not in sampled]
        if len(sampled) + len(fresh) > 10000:
            raise ValueError("楼梯探测超出候选格预算")
        count += yield from _sample_treads(fresh, sampled, x, y, base, band)
        frontier, edge_count = yield from _connect_treads(parents, sampled, tested_edges, graph, spans, x, y, base)
        count += edge_count
        if len(spans) > MAX_STATES:
            raise ValueError("楼梯连通区域超过 2400 个空气区间；请分段制作")
    if len(spans) < 9:
        raise ValueError("可通行梯段太小，请把种子移到平台或踏步中央")
    return _stair_result(graph, start, base, spans, seed, flights, count)


def scan(seed):
    # Enclosed stairs are an acoustic cavity, not a mesh of individual treads.
    # The fast route verifies an actual connected rise; complex open flights keep
    # the layer scanner, under the same whole-invocation trace/time budget.
    from .floors import stair_enclosure
    try:
        return (yield from stair_enclosure.scan(seed))
    except ValueError:
        return (yield from scan_layers(seed))


def _stair_result(graph, start, base, spans, seed, flights, count):
    x, y, _ = seed
    stair = isolate_flights(graph, start)
    platforms = landing_pair(graph, stair, base, base)
    cells = [(i, j, lo, spans[i, j, lo]) for i, j, lo in sorted(stair)]
    xs = [r[0] * STEP for r in cells]
    ys = [r[1] * STEP for r in cells]
    bounds = [
        (min(xs) - 20, min(ys) - 20, 0),
        (max(xs) + 20, min(ys) - 20, 0),
        (max(xs) + 20, max(ys) + 20, 0),
        (min(xs) - 20, max(ys) + 20, 0),
    ]
    return dict(
        model="stair_layers",
        height_cells=cells,
        grid_origin=(0, 0),
        step_cm=STEP,
        floor=min(r[2] for r in cells),
        roof=max(r[3] for r in cells),
        seed=seed,
        origin=(x, y, base),
        axis_x=(1, 0, 0),
        axis_z=(0, 0, 1),
        local_outline=bounds,
        flight_hints=len(flights),
        outline=[(x + a, y + b, base + c) for a, b, c in bounds],
        columns=len(cells),
        excluded_flat_states=len(spans) - len(cells),
        landing_reach_cm=LANDING_REACH_CM,
        connected_landing_heights_cm=platforms,
        rays=count,
    )
