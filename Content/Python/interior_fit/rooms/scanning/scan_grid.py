"""Sample connected floor and ceiling columns with editor ray batches."""

from collections import defaultdict
from interior_fit.rooms.ray_queries import (
    MAX_CELLS,
    NEIGHBORS,
    STEP,
    RayHitField,
    query,
)
from interior_fit.rooms.refine_wall_boundary import (
    refine_edges,
    supported_convex,
)
from interior_fit.spline_contour import lake_outline, validate_simple_outline
from interior_fit.rooms.scanning import probe_grid_links as grid_links


# Column probes bracket the previous measured planes. Reusing a narrow
# floor hit requires a small margin inside the 16 cm half-span.
NARROW_FLOOR_PROBE_HALF_SPAN_CM = 16
BROAD_FLOOR_PROBE_HALF_SPAN_CM = 38
NARROW_FLOOR_REUSE_RADIUS_CM = 15.99
CEILING_PROBE_HALF_SPAN_CM = 24
RETRY_CEILING_HALF_SPAN_CM = 70
MIN_HEADROOM_CM = 190
FLAT_HEIGHT_TOLERANCE_CM = 12
AUDIT_SAMPLE_TARGET = 96
AUDIT_FLOOR_HALF_SPAN_CM = 55
AUDIT_CEILING_HALF_SPAN_CM = 75
SEED_START_LIFT_CM = 12
SEED_FLOOR_SEARCH_DEPTH_CM = 500
SEED_CEILING_SEARCH_HEIGHT_CM = 900
FLOOR_NORMAL_MIN_Z = 0.85
FLAT_CEILING_NORMAL_MAX_Z = -0.98
SLOPED_SURFACE_MIN_ABS_Z = 0.65


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
    for i, j in fresh:
        px, py = x + i * STEP, y + j * STEP
        low, high = heights[parents[i, j][0]]
        radius = (
            NARROW_FLOOR_PROBE_HALF_SPAN_CM
            if fixed_planes
            else BROAD_FLOOR_PROBE_HALF_SPAN_CM
        )
        rays.extend(
            [
                ((px, py, low + radius), (px, py, low - radius)),
                (
                    (px, py, high - CEILING_PROBE_HALF_SPAN_CM),
                    (px, py, high + CEILING_PROBE_HALF_SPAN_CM),
                ),
            ]
        )
    column_count = len(rays)
    rays.extend(links)
    combined = yield from query(rays)
    hits, link_hits = combined[:column_count], combined[column_count:]
    if fixed_planes:
        return hits, len(rays), link_hits

    # A valid first hit strictly inside the short interval already answers both
    # downward queries. Check near the parent floor when the first hit is
    # farther away, where a raised object can obscure the structural floor.
    extra, slots = [], []
    for k, (i, j) in enumerate(fresh):
        px, py = x + i * STEP, y + j * STEP
        low, high = heights[parents[i, j][0]]
        broad, ceiling = hits[2 * k : 2 * k + 2]
        # A miss on the broad segment proves its contained narrow segment
        # misses.
        if broad and (
            broad[RayHitField.NORMAL][2] <= FLOOR_NORMAL_MIN_Z
            or abs(broad[RayHitField.POINT][2] - low)
            >= NARROW_FLOOR_REUSE_RADIUS_CM
        ):
            extra.append(
                (
                    (px, py, low + NARROW_FLOOR_PROBE_HALF_SPAN_CM),
                    (px, py, low - NARROW_FLOOR_PROBE_HALF_SPAN_CM),
                )
            )
            slots.append(2 * k)
        if not ceiling or ceiling[RayHitField.NORMAL][2] > -FLOOR_NORMAL_MIN_Z:
            extra.append(
                (
                    (px, py, high - RETRY_CEILING_HALF_SPAN_CM),
                    (px, py, high + RETRY_CEILING_HALF_SPAN_CM),
                )
            )
            slots.append(2 * k + 1)
    for slot, hit in zip(slots, (yield from query(extra))):
        if slot % 2 or (
            hit and hit[RayHitField.NORMAL][2] > FLOOR_NORMAL_MIN_Z
        ):
            hits[slot] = hit
    return hits, len(rays) + len(extra), link_hits


def record_heights(
    fresh,
    hits,
    allow_slopes,
    normal_limit,
    fixed_planes,
    floor,
    roof,
    supported,
    heights,
):
    for k, cell in enumerate(fresh):
        low, high = hits[2 * k : 2 * k + 2]
        if (
            not allow_slopes
            and low
            and high
            and -0.99 < high[RayHitField.NORMAL][2] < -0.7
        ):
            raise ValueError("Curved ceiling")
        valid = (
            low
            and high
            and low[RayHitField.NORMAL][2] > normal_limit
            and high[RayHitField.NORMAL][2]
            < (-normal_limit if allow_slopes else FLAT_CEILING_NORMAL_MAX_Z)
            and high[RayHitField.POINT][2] - low[RayHitField.POINT][2]
            >= MIN_HEADROOM_CM
        )
        supported[cell] = bool(valid)
        if valid:
            heights[cell] = (
                (floor, roof)
                if fixed_planes
                else (low[RayHitField.POINT][2], high[RayHitField.POINT][2])
            )


def reachable_neighbors(parents, supported, heights, x, y, cached=None):
    return (
        yield from grid_links.reachable(
            parents, supported, heights, x, y, cached or {}
        )
    )


def audit_flat_floor(reached, x, y, floor, roof):
    # The planar fallback is only for locally occluded flat floors. Audit
    # coverage before
    # accepting it, including the ring just beyond the candidate where a raised
    # landing may begin.
    ring = {
        (i + di, j + dj) for i, j in reached for di, dj in NEIGHBORS
    } - reached
    sites = sorted(reached | ring)
    samples = sites[:: max(1, len(sites) // AUDIT_SAMPLE_TARGET)]
    checks = []
    for i, j in samples:
        px, py = x + i * STEP, y + j * STEP
        checks.extend(
            [
                (
                    (px, py, floor + AUDIT_FLOOR_HALF_SPAN_CM),
                    (px, py, floor - AUDIT_FLOOR_HALF_SPAN_CM),
                ),
                (
                    (px, py, roof - AUDIT_CEILING_HALF_SPAN_CM),
                    (px, py, roof + AUDIT_CEILING_HALF_SPAN_CM),
                ),
            ]
        )
    checked = yield from query(checks)
    changed = 0
    for k in range(0, len(checked), 2):
        low, high = checked[k : k + 2]
        if (
            low
            and high
            and (
                abs(low[RayHitField.POINT][2] - floor)
                > FLAT_HEIGHT_TOLERANCE_CM
                or abs(high[RayHitField.POINT][2] - roof)
                > FLAT_HEIGHT_TOLERANCE_CM
            )
        ):
            changed += 1
    if changed > max(3, len(samples) * 0.06):
        raise ValueError(
            "Planar fallback conflicts with measured height changes"
        )
    return len(checks)


def build_result(seed, wall_hits, reached, heights, floor, roof, ray_count):
    x, y, _ = seed
    centers = [(x + i * STEP, y + j * STEP, floor) for i, j in sorted(reached)]
    try:
        outline = lake_outline(centers, STEP, STEP * 0.68)
    except ValueError as error:
        raise ValueError(
            "Room footprint has holes, corner contact or excessive outline "
            "complexity"
        ) from error
    validate_simple_outline(outline)
    # Small seams retain the accurate plane fit. Substantial connected steps
    # get a 3D surface.
    significant = sum(
        abs(heights[c][0] - floor) > FLAT_HEIGHT_TOLERANCE_CM
        or abs(heights[c][1] - roof) > FLAT_HEIGHT_TOLERANCE_CM
        for c in reached
    )
    if significant >= 4:
        records = [
            (
                i,
                j,
                round(heights[i, j][0] / 2) * 2,
                round(heights[i, j][1] / 2) * 2,
            )
            for i, j in sorted(reached)
        ]
        from interior_fit.rooms.geometry.align_wall_edges import (
            align_outer_edges,
        )

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
    from interior_fit.rooms.geometry.reconstruct_straight_walls import (
        reconstruct,
    )

    straight = reconstruct(outline, STEP)
    details = {} if straight else None
    outline, added = yield from refine_edges(
        straight or outline, roof, details
    )
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
        result.update(
            preview_required=True,
            straightened=dict(
                details,
                before_corners=len(coarse),
                after_corners=len(outline),
                method="wall_lines",
            ),
        )
    return result


def scan_local(seed, wall_hits, allow_slopes=False, fixed_planes=False):
    """
    Flood only through supported columns and unobstructed near-ceiling
    edges.
    """
    x, y, z = seed
    start = (x, y, z + SEED_START_LIFT_CM)
    bottom, top = yield from query(
        [
            (start, (x, y, z - SEED_FLOOR_SEARCH_DEPTH_CM)),
            (start, (x, y, z + SEED_CEILING_SEARCH_HEIGHT_CM)),
        ]
    )
    normal_limit = (
        SLOPED_SURFACE_MIN_ABS_Z if allow_slopes else FLOOR_NORMAL_MIN_Z
    )
    if (
        not bottom
        or not top
        or bottom[RayHitField.NORMAL][2] < normal_limit
        or top[RayHitField.NORMAL][2] > -normal_limit
    ):
        raise ValueError("Seed needs a level floor and overhead ceiling")
    floor, roof = bottom[RayHitField.POINT][2], top[RayHitField.POINT][2]
    if roof - floor < MIN_HEADROOM_CM:
        raise ValueError(
            f"Seed has less than {MIN_HEADROOM_CM} cm of headroom"
        )

    reached = {(0, 0)}
    frontier = reached.copy()
    supported = {}
    heights = {(0, 0): (floor, roof)}
    ray_count = 2
    while frontier:
        parents = neighbor_cells(frontier, reached, supported)
        fresh = [cell for cell in parents if cell not in supported]
        if len(supported) + len(fresh) > MAX_CELLS:
            raise ValueError(
                f"Scan exceeded the {MAX_CELLS}-cell budget; partial room "
                f"discarded"
            )
        links = list(grid_links.first_links(parents, heights, x, y).values())
        hits, count, link_hits = yield from sample_columns(
            fresh, x, y, heights, parents, fixed_planes, links
        )
        record_heights(
            fresh,
            hits,
            allow_slopes,
            normal_limit,
            fixed_planes,
            floor,
            roof,
            supported,
            heights,
        )
        frontier, crossings = yield from reachable_neighbors(
            parents, supported, heights, x, y, dict(zip(links, link_hits))
        )
        reached.update(frontier)
        ray_count += count + crossings
    if len(reached) < 9:
        raise ValueError(
            "Fewer than nine connected columns support the seed planes"
        )
    if fixed_planes:
        ray_count += yield from audit_flat_floor(reached, x, y, floor, roof)
    return (
        yield from build_result(
            seed, wall_hits, reached, heights, floor, roof, ray_count
        )
    )
