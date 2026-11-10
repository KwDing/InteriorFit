from collections import defaultdict
from .rays import MAX_CELLS, NEIGHBORS, STEP, query
from .walls import refine_edges, supported_convex
from ..spline_contour import lake_outline, validate_simple_outline
from . import grid_links


def neighbor_cells(frontier, reached, supported):
    parents = defaultdict(list)
    for i, j in sorted(frontier):
        for di, dj in NEIGHBORS:
            cell = (i + di, j + dj)
            if cell not in reached and supported.get(cell, True):
                parents[cell].append((i, j))
    return parents


def sample_columns(fresh, x, y, heights, parents, fixed_planes, links=()):
    rays = []
    for i,j in fresh:
        px,py = x+i*STEP, y+j*STEP
        low,high = heights[parents[i,j][0]]
        radius = 16 if fixed_planes else 38
        rays.extend([((px,py,low+radius),(px,py,low-radius)),
                     ((px,py,high-24),(px,py,high+24))])
    column_count = len(rays)
    rays.extend(links)
    combined = yield from query(rays)
    hits, link_hits = combined[:column_count], combined[column_count:]
    if fixed_planes:
        return hits, len(rays), link_hits

    # A valid first hit strictly inside the short interval already answers both
    # downward queries. Preserve the old narrow/wide choice for ambiguous hits.
    extra, slots = [], []
    for k,(i,j) in enumerate(fresh):
        px,py = x+i*STEP, y+j*STEP
        low,high = heights[parents[i,j][0]]
        broad,ceiling = hits[2*k:2*k+2]
        # A miss on the broad segment proves its contained narrow segment misses.
        if broad and (broad[1][2] <= 0.85 or abs(broad[0][2]-low) >= 15.99):
            extra.append(((px,py,low+16),(px,py,low-16)))
            slots.append(2*k)
        if not ceiling or ceiling[1][2] > -0.85:
            extra.append(((px,py,high-70),(px,py,high+70)))
            slots.append(2*k+1)
    for slot,hit in zip(slots,(yield from query(extra))):
        broad = hits[slot]
        if slot % 2 or (hit and not (broad and broad[1][2]>0.85 and broad[0][2]>hit[0][2]+10)):
            hits[slot] = hit
    return hits, len(rays)+len(extra), link_hits


def record_heights(fresh, hits, allow_slopes, normal_limit, fixed_planes, floor, roof, supported, heights):
    for k, cell in enumerate(fresh):
        low, high = hits[2 * k : 2 * k + 2]
        if not allow_slopes and low and high and -0.99 < high[1][2] < -0.7:
            raise ValueError("Curved ceiling")
        valid = (
            low
            and high
            and low[1][2] > normal_limit
            and high[1][2] < (-normal_limit if allow_slopes else -0.98)
            and high[0][2] - low[0][2] >= 190
        )
        supported[cell] = bool(valid)
        if valid:
            heights[cell] = (floor, roof) if fixed_planes else (low[0][2], high[0][2])


def reachable_neighbors(parents, supported, heights, x, y, cached=None):
    return (yield from grid_links.reachable(parents, supported, heights, x, y, cached or {}))


def audit_flat_floor(reached, x, y, floor, roof):
    # The planar fallback is only for locally occluded flat floors. Audit coverage before
    # accepting it, including the ring just beyond the candidate where a raised landing may begin.
    ring = {(i + di, j + dj) for i, j in reached for di, dj in NEIGHBORS} - reached
    sites = sorted(reached | ring)
    samples = sites[:: max(1, len(sites) // 96)]
    checks = []
    for i, j in samples:
        px, py = x + i * STEP, y + j * STEP
        checks.extend([((px, py, floor + 55), (px, py, floor - 55)), ((px, py, roof - 75), (px, py, roof + 75))])
    checked = yield from query(checks)
    changed = 0
    for k in range(0, len(checked), 2):
        low, high = checked[k : k + 2]
        if low and high and (abs(low[0][2] - floor) > 12 or abs(high[0][2] - roof) > 12):
            changed += 1
    if changed > max(3, len(samples) * 0.06):
        raise ValueError("Planar fallback conflicts with measured height changes")
    return len(checks)


def build_result(seed, wall_hits, reached, heights, floor, roof, ray_count):
    x, y, _ = seed
    centers = [(x + i * STEP, y + j * STEP, floor) for i, j in sorted(reached)]
    try:
        outline = lake_outline(centers, STEP, STEP * 0.68)
    except ValueError as error:
        raise ValueError("Room footprint has holes, corner contact or excessive outline complexity") from error
    validate_simple_outline(outline)
    # Small seams retain the accurate plane fit. Substantial connected steps get a 3D surface.
    significant = sum(abs(heights[c][0] - floor) > 12 or abs(heights[c][1] - roof) > 12 for c in reached)
    if significant >= 4:
        records = [(i, j, round(heights[i, j][0] / 2) * 2, round(heights[i, j][1] / 2) * 2) for i, j in sorted(reached)]
        from ..room_height import align_outer_edges

        corrections = align_outer_edges(wall_hits, reached, x, y, STEP)
        return dict(
            model="stepped_heightfield",
            boundary_planes=corrections,
            height_cells=records,
            grid_origin=(x, y),
            outline=outline,
            floor=min(r[2] for r in records),
            roof=max(r[3] for r in records),
            columns=len(reached),
            rays=ray_count,
            step_cm=STEP,
        )
    coarse = outline
    from .straight_walls import reconstruct
    straight = reconstruct(outline, STEP)
    details = {} if straight else None
    outline, added = yield from refine_edges(straight or outline, roof, details)
    convex = supported_convex(wall_hits, centers, floor)
    model = "connected_polygon"
    if convex:
        outline = convex
        model = "supported_convex"
    result = dict(
        model=model,
        coarse_outline=coarse,
        outline=outline,
        floor=floor,
        roof=roof,
        rays=ray_count + added,
        columns=len(reached),
        step_cm=STEP,
        seed=seed,
    )
    if straight and not convex:
        result.update(preview_required=True, straightened=dict(details,
            before_corners=len(coarse), after_corners=len(outline), method="wall_lines"))
    return result


def scan_local(seed, wall_hits, allow_slopes=False, fixed_planes=False):
    """Flood only through supported columns and unobstructed near-ceiling edges."""
    x, y, z = seed
    start = (x, y, z + 12)
    bottom, top = yield from query([(start, (x, y, z - 500)), (start, (x, y, z + 900))])
    normal_limit = 0.65 if allow_slopes else 0.85
    if not bottom or not top or bottom[1][2] < normal_limit or top[1][2] > -normal_limit:
        raise ValueError("Seed needs a level floor and overhead ceiling")
    floor, roof = bottom[0][2], top[0][2]
    if roof - floor < 190:
        raise ValueError("Seed has less than 190 cm of headroom")

    reached = {(0, 0)}
    frontier = reached.copy()
    supported = {}
    heights = {(0, 0): (floor, roof)}
    ray_count = 2
    while frontier:
        parents = neighbor_cells(frontier, reached, supported)
        fresh = [cell for cell in parents if cell not in supported]
        if len(supported) + len(fresh) > MAX_CELLS:
            raise ValueError("Scan exceeded the 12000-cell budget; partial room discarded")
        links = list(grid_links.first_links(parents, heights, x, y).values())
        hits, count, link_hits = yield from sample_columns(fresh, x, y, heights, parents, fixed_planes, links)
        record_heights(fresh, hits, allow_slopes, normal_limit, fixed_planes, floor, roof, supported, heights)
        frontier, crossings = yield from reachable_neighbors(parents, supported, heights, x, y,
                                                             dict(zip(links, link_hits)))
        reached.update(frontier)
        ray_count += count + crossings
    if len(reached) < 9:
        raise ValueError("Fewer than nine connected columns support the seed planes")
    if fixed_planes:
        ray_count += yield from audit_flat_floor(reached, x, y, floor, roof)
    return (yield from build_result(seed, wall_hits, reached, heights, floor, roof, ray_count))
