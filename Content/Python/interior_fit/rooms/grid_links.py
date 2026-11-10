"""Co-schedule the first flood link with column probes; validate its height later.

A cell needs one clear entrance, not a clear edge from every reached parent.
Speculation changes scheduling only: a hit is reused only for the exact directed
segment that the measured column heights require. Steps trigger fresh traces.
"""
from .rays import STEP, query


def segment(parent, cell, heights, x, y):
    parent_roof = heights[parent][1]
    roof = min(parent_roof, heights.get(cell, heights[parent])[1]) - 30
    return ((x + parent[0]*STEP, y + parent[1]*STEP, roof),
            (x + cell[0]*STEP, y + cell[1]*STEP, roof))


def first_links(parents, heights, x, y):
    return {cell: segment(previous[0], cell, heights, x, y)
            for cell, previous in parents.items()}


def reachable(parents, supported, heights, x, y, cached):
    """Check alternate entrances only until each cell has a clear valid link."""
    remaining = {
        cell: [parent for parent in previous
               if abs(heights[parent][0]-heights[cell][0]) <= 38
               and abs(heights[parent][1]-heights[cell][1]) <= 70]
        for cell, previous in parents.items() if supported[cell]
    }
    found, count = set(), 0
    while remaining:
        requests = {cell: segment(previous.pop(0), cell, heights, x, y)
                    for cell, previous in remaining.items() if previous}
        if not requests:
            break
        missing = list(dict.fromkeys(ray for ray in requests.values() if ray not in cached))
        cached.update(zip(missing, (yield from query(missing))))
        count += len(missing)
        found.update(cell for cell, ray in requests.items() if not cached[ray])
        remaining = {cell: previous for cell, previous in remaining.items()
                     if cell not in found and previous}
    return found, count
