import math
from ..core import select_plane, floor_component, validate_settings
from .scene import trace

DEFAULTS = {"range_cm": 900.0, "grid_cm": 50.0, "step_cm": 45.0, "headroom_cm": 190.0}


def position(seed, yaw, x, y, z):
    angle = math.radians(yaw)
    return [seed[0] + x * math.cos(angle) - y * math.sin(angle), seed[1] + x * math.sin(angle) + y * math.cos(angle), z]


def vertical_surface(world, start, end_z, ignored):
    # Exact modular seams can return an edge normal or miss. Require nearby planar support.
    hits = []
    for dx, dy in ((0, 0), (2, 2), (-2, 2), (2, -2), (-2, -2)):
        hit = trace(world, [start[0] + dx, start[1] + dy, start[2]], [start[0] + dx, start[1] + dy, end_z], ignored)
        if hit and abs(hit["normal"][2]) > 0.7:
            hits.append(hit)
    if len(hits) < 3:
        return None
    hits.sort(key=lambda hit: hit["point"][2])
    middle = hits[len(hits) // 2]
    if sum(abs(hit["point"][2] - middle["point"][2]) < 10 for hit in hits) < 3:
        return None
    return middle


def plane_votes(world, seed, yaw, floor, roof, axis, sign, settings, ignored):
    hits = []
    angle = math.radians(yaw + axis * 90)
    normal = [math.cos(angle) * sign, math.sin(angle) * sign]
    for fraction in (0.45, 0.8, 0.9, 0.95):
        z = floor + (roof - floor) * fraction
        for offset in (-60.0, 0.0, 60.0):
            local = [0.0, 0.0]
            local[1 - axis] = offset
            start = position(seed, yaw, *local, z)
            end = [start[0] + normal[0] * settings["range_cm"], start[1] + normal[1] * settings["range_cm"], z]
            hit = trace(world, start, end, ignored)
            if hit and abs(sum(hit["normal"][i] * normal[i] for i in (0, 1))) > 0.92:
                distance = sum((hit["point"][i] - start[i]) * normal[i] for i in (0, 1))
                if distance > 10:
                    hits.append(dict(hit, distance=distance, offset=offset, height=fraction))
    voted = select_plane(hits)
    local = opening_plane(world, seed, yaw, floor, roof, axis, sign, settings, ignored)
    candidates = [p for p in (voted, local) if p]
    return min(candidates, key=lambda p: p["distance"]) if candidates else None


def _lintel_hits(world, seed, floor, roof, direction, point, offset, max_distance, ignored):
    hits = []
    for fraction in (0.78, 0.82, 0.86, 0.9, 0.94, 0.97):
        z = floor + (roof - floor) * fraction
        a = [point[0] - direction[0] * 75, point[1] - direction[1] * 75, z]
        b = [point[0] + direction[0] * 35, point[1] + direction[1] * 35, z]
        for start, end in ((a, b), (b, a)):
            hit = trace(world, start, end, ignored)
            if not hit or abs(sum(hit["normal"][i] * direction[i] for i in (0, 1))) < 0.92:
                continue
            measured = sum((hit["point"][i] - seed[i]) * direction[i] for i in (0, 1))
            if 10 < measured < max_distance:
                hits.append(
                    dict(hit, distance=measured, offset=offset, height=fraction, method="local_roof_edge_lintel")
                )
    return hits


def opening_plane(world, seed, yaw, floor, roof, axis, sign, settings, ignored):
    """Find the local roof edge first, then test the lintel from both sides of that edge.

    Short reverse probes handle one-sided art without tracing back from the opposite building.
    No upper structure means unresolved, not a fabricated closing wall.
    """
    hits = []
    angle = math.radians(yaw + axis * 90)
    direction = [math.cos(angle) * sign, math.sin(angle) * sign]
    for offset in (-60.0, 0.0, 60.0):
        for distance in range(50, int(settings["range_cm"]) + 1, 25):
            local = [0.0, 0.0]
            local[axis] = distance * sign
            local[1 - axis] = offset
            p = position(seed, yaw, *local, roof - 50)
            overhead = vertical_surface(world, p, roof + 40, ignored)
            if overhead and abs(overhead["point"][2] - roof) < 40:
                continue
            hits.extend(_lintel_hits(world, seed, floor, roof, direction, p, offset, settings["range_cm"], ignored))
            break
    return select_plane(hits)


def _floor_issues(footprint, total, reached, cells, floor, roof, settings):
    issues = []
    if footprint < total * 0.9:
        issues.append("Nonrectangular or unsupported floor/ceiling footprint: box creation refused")
    if not reached:
        issues.append("Seed has no connected standing-floor sample")
    # A raised hit with continuous structural floor beneath it is furniture, not a new floor.
    if any(not cells[k]["base_supported"] and cells[k]["floor"] - floor > settings["step_cm"] for k in reached):
        issues.append("Stairs/split level detected: separate landing/shaft authoring required")
    if reached and any(abs(cells[k]["roof"] - roof) > 30 for k in reached):
        issues.append("Ceiling discontinuity/opening: inspect before room authoring")
    return issues


def sample_floor(world, seed, yaw, bounds, floor, roof, settings, ignored):
    grid = settings["grid_cm"]
    cells = {}
    footprint = 0
    # Keep standing-floor validation off wall trim and door lintels; boundary probes are separate.
    inner = [bounds[0] + 35, bounds[1] - 35, bounds[2] + 35, bounds[3] - 35]
    total = max(0, math.floor(inner[1] / grid) - math.ceil(inner[0] / grid) + 1) * max(
        0, math.floor(inner[3] / grid) - math.ceil(inner[2] / grid) + 1
    )
    if total > 2500:
        return {"cells": [], "coverage": 0, "issues": ["Floor grid exceeds 2500-cell editor budget"]}
    for ix in range(math.ceil(inner[0] / grid), math.floor(inner[1] / grid) + 1):
        for iy in range(math.ceil(inner[2] / grid), math.floor(inner[3] / grid) + 1):
            p = position(seed, yaw, ix * grid, iy * grid, floor + settings["headroom_cm"])
            base = vertical_surface(world, [p[0], p[1], floor + 30], floor - 50, ignored)
            ceiling = vertical_surface(world, [p[0], p[1], roof - 50], roof + 40, ignored)
            if base and ceiling and abs(base["point"][2] - floor) < 30 and abs(ceiling["point"][2] - roof) < 40:
                footprint += 1
            down = vertical_surface(world, p, floor - 50, ignored)
            if not down or down["normal"][2] < 0.7:
                continue
            z = down["point"][2]
            up = ceiling
            if not up or up["point"][2] - z < settings["headroom_cm"]:
                continue
            cells[ix, iy] = {
                "point": [p[0], p[1], z],
                "floor": z,
                "roof": up["point"][2],
                "base_supported": bool(base and abs(base["point"][2] - floor) < 30),
            }

    def clear(a, b):
        return all(
            trace(world, [*a["point"][:2], a["floor"] + h], [*b["point"][:2], b["floor"] + h], ignored) is None
            for h in (40, 120, 180)
        )

    reached = floor_component(cells, (0, 0), settings["step_cm"], clear)
    issues = _floor_issues(footprint, total, reached, cells, floor, roof, settings)
    return {
        "cells": [dict(cells[k], key=list(k), connected=k in reached) for k in cells],
        "coverage": footprint / max(total, 1),
        "reachable_fraction": len(reached) / max(total, 1),
        "walk_clearance_certified": False,
        "issues": issues,
    }


def scan_at(world, seed, yaw, ignored, settings=None):
    settings = dict(settings or DEFAULTS)
    validate_settings(settings)
    result = {"seed": seed, "yaw": yaw, "settings": settings, "issues": [], "kind": "conservative_box_candidate"}
    down = vertical_surface(world, seed, seed[2] - 500, ignored)
    up = vertical_surface(world, seed, seed[2] + 700, ignored)
    result.update(floor_hit=down, roof_hit=up)
    if not down or not up or down["normal"][2] < 0.7:
        result["issues"].append("Seed needs supported floor and ceiling within local scan range")
        return result
    floor = down["point"][2]
    roof = up["point"][2]
    if roof - floor < settings["headroom_cm"]:
        result["issues"].append("Insufficient clear height or seed inside furniture")
        return result
    planes = [
        plane_votes(world, seed, yaw, floor, roof, axis, sign, settings, ignored)
        for axis, sign in ((0, -1), (0, 1), (1, -1), (1, 1))
    ]
    result.update(floor=floor, roof=roof, planes=planes)
    if any(p is None for p in planes):
        result["issues"].append("Unresolved boundary: no supported wall plane; move seed or mark opening")
        return result
    bounds = [-planes[0]["distance"], planes[1]["distance"], -planes[2]["distance"], planes[3]["distance"]]
    result["bounds_local"] = bounds
    sampled = sample_floor(world, seed, yaw, bounds, floor, roof, settings, ignored)
    result.update(sampled)
    result["center"] = position(seed, yaw, (bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (floor + roof) / 2)
    result["half_extent"] = [(bounds[1] - bounds[0]) / 2, (bounds[3] - bounds[2]) / 2, (roof - floor) / 2]
    # Sparse geometry is evidence only. Explicit confirmation is required for open boundary candidates.
    result["requires_visual_review"] = True
    return result


def scan(world, seed, yaw, ignored, settings=None):
    """Search bounded nearby probes; original point must remain inside the result.

    Existing acoustic Rooms are ignored, never used as fitted geometry. A high-level
    segment prevents jumping through a partition/door lintel into another room.
    """
    settings = dict(settings or DEFAULTS)
    validate_settings(settings)
    attempts = []
    # Starting on the floor is normal editor placement. Lift the *probe*, not the Actor.
    probe = list(seed)
    probe[2] += 20
    down = vertical_surface(world, probe, probe[2] - 500, ignored)
    if down:
        probe[2] = down["point"][2] + 120
    for dx, dy in ((0, 0), (75, 0), (-75, 0), (0, 75), (0, -75), (75, 75), (-75, 75), (75, -75), (-75, -75)):
        candidate = position(probe, yaw, dx, dy, probe[2])
        result = scan_at(world, candidate, yaw, ignored, settings)
        attempts.append({"probe": candidate, "issues": result["issues"], "coverage": result.get("coverage", 0)})
        if result["issues"]:
            continue
        angle = math.radians(yaw)
        vx = seed[0] - candidate[0]
        vy = seed[1] - candidate[1]
        x = vx * math.cos(angle) + vy * math.sin(angle)
        y = -vx * math.sin(angle) + vy * math.cos(angle)
        b = result["bounds_local"]
        if not (b[0] - 5 <= x <= b[1] + 5 and b[2] - 5 <= y <= b[3] + 5):
            continue
        z = result["floor"] + (result["roof"] - result["floor"]) * 0.9
        if (dx or dy) and trace(world, [seed[0], seed[1], z], [candidate[0], candidate[1], z], ignored):
            continue
        result.update(
            original_seed=list(seed),
            probe_attempts=attempts,
            automatic_probe_offset=[candidate[i] - seed[i] for i in range(3)],
        )
        return result
    if not result["issues"]:
        result["issues"] = ["No reliable candidate containing the original point in the same compartment"]
    result.update(original_seed=list(seed), probe_attempts=attempts)
    return result
