"""Engine-independent conservative plane voting and floor-component classification."""

from collections import deque
from statistics import median
import math


def select_plane(hits, tolerance=12.0, minimum_votes=3):
    """Require spatially distinct probes; distant lone hits cannot close an opening."""
    candidates = []
    for hit in hits:
        group = [item for item in hits if abs(item["distance"] - hit["distance"]) <= tolerance]
        offsets = {item["offset"] for item in group}
        heights = {item["height"] for item in group}
        if len(group) >= minimum_votes and len(offsets) >= 2 and len(heights) >= 2:
            candidates.append(group)
    if not candidates:
        return None
    chosen = min(candidates, key=lambda group: median(item["distance"] for item in group))
    return {"distance": median(item["distance"] for item in chosen), "votes": len(chosen), "evidence": chosen}


def floor_component(cells, seed_key, step_height, edge_clear):
    """Actual step threshold, never half-story teleporting; keep local floor heights."""
    if seed_key not in cells:
        return set()
    reached = {seed_key}
    pending = deque([seed_key])
    while pending:
        key = pending.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            other = (key[0] + dx, key[1] + dy)
            if other in reached or other not in cells:
                continue
            if abs(cells[key]["floor"] - cells[other]["floor"]) > step_height:
                continue
            if edge_clear(cells[key], cells[other]):
                reached.add(other)
                pending.append(other)
    return reached


def validate_settings(settings):
    for name in ("range_cm", "grid_cm", "step_cm", "headroom_cm"):
        value = settings[name]
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid " + name)
    if settings["range_cm"] > 1500 or settings["grid_cm"] < 25:
        raise ValueError("Scan budget exceeded: range <=1500 cm, grid >=25 cm")
