"""Conservative single-storey recovery for cluttered or overlapping polygon candidates."""

import math
import unreal as u
from .room_contour import NEIGHBORS, query

STEP = 40


def intersects(bounds, other):
    return all(min(hi, b) - max(lo, a) > 0.5 for (lo, hi), (a, b) in zip(bounds, other))


def cell_box(x, y, low, high):
    return ((x - 20, x + 20), (y - 20, y + 20), (low, high))


class ProtectedRoom:
    def __init__(self, actor, bounds):
        self.bounds = bounds
        self.brush = actor.get_component_by_class(u.BrushComponent)

    def blocks(self, box):
        if not intersects(box, self.bounds):
            return False
        x, y = (sum(pair) / 2 for pair in box[:2])
        bottom, top = box[2]
        slices = max(1, math.ceil((top - bottom) / 40))
        height = (top - bottom) / slices
        # If the closest brush point lies outside the enclosing sphere, this entire
        # slab is clear. This permits walkable space inside the AABB of a concave stair.
        radius = math.sqrt(2 * (STEP / 2) ** 2 + (height / 2) ** 2)
        for i in range(slices):
            p = u.Vector(x, y, bottom + height * (i + 0.5))
            distance, _ = self.brush.get_closest_point_on_collision(p)
            if distance <= radius:
                return True
        return False


def _sample_columns(fresh, floor, protected, xy, seen):
    rays = []
    for cell in fresh:
        px, py = xy(cell)
        rays.extend([((px, py, floor + 20), (px, py, floor - 25)), ((px, py, floor + 140), (px, py, floor + 580))])
    hits = yield from query(rays)
    for i, cell in enumerate(fresh):
        low, cap = hits[2 * i : 2 * i + 2]
        seen[cell] = None
        if not low or not cap or low[1][2] < 0.8 or cap[1][2] > -0.6:
            continue
        bottom, top = round(low[0][2] / 2) * 2, round(cap[0][2] / 2) * 2
        if top - bottom < 185:
            continue
        if any(r.blocks(cell_box(*xy(cell), bottom, top)) for r in protected):
            continue
        seen[cell] = (bottom, top)
    return len(rays)


def _reachable_neighbors(frontier, seen, reached, xy):
    addition = set()
    rays = []
    edges = []
    for cell in frontier:
        if not seen[cell]:
            continue
        if cell == (0, 0):
            addition.add(cell)
            continue
        for dx, dy in NEIGHBORS:
            prev = (cell[0] + dx, cell[1] + dy)
            if prev not in reached:
                continue
            lo = max(reached[prev][0], seen[cell][0])
            hi = min(reached[prev][1], seen[cell][1])
            for h in (lo + 100, hi - 20):
                rays.append(((*xy(prev), h), (*xy(cell), h)))
            edges.append(cell)
    walls = yield from query(rays)
    for i, cell in enumerate(edges):
        if not walls[2 * i] and not walls[2 * i + 1]:
            addition.add(cell)
    return addition, len(rays)


def scan(seed, floor, protected):
    x, y, z = seed

    def xy(cell):
        return (x + cell[0] * STEP, y + cell[1] * STEP)

    # Represent the walkable part of this storey; never bridge a protected staircase.
    reached = {}
    seen = {}
    frontier = {(0, 0)}
    rays_used = 0
    while frontier:
        fresh = sorted(frontier - seen.keys())
        rays_used += yield from _sample_columns(fresh, floor, protected, xy, seen)
        addition, count = yield from _reachable_neighbors(frontier, seen, reached, xy)
        rays_used += count
        reached.update((cell, seen[cell]) for cell in addition)
        frontier = {
            (i + dx, j + dy)
            for i, j in addition
            for dx, dy in NEIGHBORS
            if (i + dx, j + dy) not in reached and seen.get((i + dx, j + dy), True)
        }
        if len(seen) > 3500:
            raise ValueError("本层区域超过 3500 格，建议另设种子分区")
    if len(reached) < 12:
        raise ValueError("已有 Room 或地板碰撞阻断了本层的可达区域")
    return _storey_result(seed, floor, reached, rays_used)


def _storey_result(seed, floor, reached, rays_used):
    x, y, _ = seed
    cells = [(i, j, lo - floor, hi - floor) for (i, j), (lo, hi) in sorted(reached.items())]
    # Used only for the extent of comparison probes; the brush uses the individual columns.
    xs, ys = zip(*reached)
    footprint = [
        (i * STEP + di, j * STEP + dj, 0)
        for i, j, di, dj in (
            (min(xs), min(ys), -20, -20),
            (max(xs), min(ys), 20, -20),
            (max(xs), max(ys), 20, 20),
            (min(xs), max(ys), -20, 20),
        )
    ]
    return dict(
        model="stepped_heightfield",
        storey_cells=True,
        seed=seed,
        origin=(x, y, floor),
        axis_x=(1, 0, 0),
        axis_z=(0, 0, 1),
        floor=min(r[2] for r in cells),
        roof=max(r[3] for r in cells),
        local_outline=footprint,
        outline=[(x + a, y + b, floor) for a, b, _ in footprint],
        height_cells=cells,
        columns=len(cells),
        grid_origin=(0, 0),
        step_cm=STEP,
        rays=rays_used,
    )
