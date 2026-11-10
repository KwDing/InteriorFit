"""Editor-only adoption policy. All dimensions entering this module are in centimetres."""
import json
import math
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[4] / "Config" / "RoomBudget.json"
HEIGHT_MODELS = {"stepped_heightfield", "stair_layers", "strip_profile"}


def settings():
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    if type(config["enabled"]) is not bool:
        raise ValueError("RoomBudget.enabled must be true or false")
    for key in ("micro_volume_m3", "large_volume_m3", "long_diagonal_m",
                "max_volume_change", "boundary_fraction"):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid RoomBudget setting: {key}")
    if config["micro_volume_m3"] >= config["large_volume_m3"] or max(
            config["max_volume_change"], config["boundary_fraction"]) >= 1:
        raise ValueError("Invalid RoomBudget thresholds")
    return config if config["enabled"] else None


def cap_target(center, radii, config):
    a, b, h = radii
    cut = center[2] / h
    volume = math.pi*a*b*h*(1+cut)**2*(2-cut)/3e6
    diagonal = math.hypot(2*a, 2*b, h+center[2])/100
    if volume < config["micro_volume_m3"]:
        return 12
    if diagonal > config["long_diagonal_m"] and volume > config["large_volume_m3"]:
        return 36
    return 24 if volume > config["large_volume_m3"] else 16


def deep_notch(points):
    """Distance to the convex envelope stays meaningful on finely sampled concave walls."""
    if len(points) < 4:
        return False
    def chain(vertices):
        edge = []
        for x,y in vertices:
            while len(edge)>1:
                a,b = edge[-2:]
                if (b[0]-a[0])*(y-a[1]) > (b[1]-a[1])*(x-a[0]):
                    break
                edge.pop()
            edge.append((x,y))
        return edge[:-1]
    samples = sorted(set((p[0],p[1]) for p in points))
    hull = chain(samples)+chain(reversed(samples))
    if len(hull)==len(samples):
        return False
    # Support-line distances give the clearance of an interior point to the hull.
    lines = []
    for a,b in zip(hull,hull[1:]+hull[:1]):
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = math.hypot(dx,dy)
        if length: lines.append((a,-dy/length,dx/length))
    return bool(lines) and any(all((x-a[0])*nx+(y-a[1])*ny>100 for a,nx,ny in lines)
                               for x,y in samples)


def limits(model, points, volume, diagonal, config):
    if volume < config["micro_volume_m3"]:
        return (12,)
    levels = [12, 16, 20, 24]
    if model in {"wall_plane_prism","connected_polygon","circular_prism"}:
        if deep_notch(points) or diagonal > config["long_diagonal_m"]:
            levels.extend([36, 48])
    elif model in HEIGHT_MODELS and diagonal > config["long_diagonal_m"]:
        levels.extend([36, 48])
    return levels


def stair_ramp(sections):
    """Keep both landings. Check the linear floor against both ends of every tread."""
    if len(sections) < 3 or max(row[3] for row in sections)-min(row[3] for row in sections)>1:
        return None
    start, end = sections[0], sections[-1]
    first = max(start[0],start[1]-(sections[1][1]-sections[1][0])/2)
    last = min(end[1],end[0]+(sections[-2][1]-sections[-2][0])/2)
    if last <= first or first <= start[0] or last >= end[1]:
        return None
    for lo,hi,floor,_ in sections:
        for x in (lo,hi):
            t = max(0,min(1,(x-first)/(last-first)))
            if abs(start[2]+t*(end[2]-start[2])-floor)>11:
                return None
    return [(start[0],start[2]),(first,start[2]),(last,end[2]),(end[1],end[2]),
            (end[1],end[3]),(start[0],start[3])]
