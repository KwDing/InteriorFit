"""Exclude ceiling samples that lie over measured walls."""

from interior_fit.rooms.geometry import wall_plane_cells as plane_cells
from interior_fit.rooms.geometry.outline_queries import closest_edge
from interior_fit.rooms.ray_queries import RayHitField, query

# Only probe just outside the contour, where roof samples may lie over a wall.
MIN_EXTERIOR_SAMPLE_DISTANCE_CM = 4
MAX_EXTERIOR_SAMPLE_DISTANCE_CM = 12
WALL_PROBE_HALF_SPAN_CM = 18
WALL_PROBE_BELOW_ROOF_CM = 5
WALL_OFFSET_TOLERANCE_CM = 4
WALL_NORMAL_MIN_DOT = 0.995


def exclude_wall_sites(frame, roof, ring, sites, points):
    """Only exclude a near-exterior roof point after measuring its actual wall.

    A ceiling can cover the wall's thickness. It does not make that material
    room air. Keep the existing 4 cm matching tolerance for all other points.
    """
    suspects, rays = [], []
    for key in sorted(sites):
        if plane_cells.inside(ring, points[key]) or plane_cells.near_edge(
            ring, points[key]
        ):
            continue
        distance, (x, y), (nx, ny) = closest_edge(ring, points[key])
        if (
            not MIN_EXTERIOR_SAMPLE_DISTANCE_CM
            < distance
            <= MAX_EXTERIOR_SAMPLE_DISTANCE_CM
        ):
            continue
        suspects.append((key, x, y, nx, ny))
        dx, dy = WALL_PROBE_HALF_SPAN_CM * nx, WALL_PROBE_HALF_SPAN_CM * ny
        height = roof - WALL_PROBE_BELOW_ROOF_CM
        rays.append(
            (
                frame.world((x + dx, y + dy, height)),
                frame.world((x - dx, y - dy, height)),
            )
        )
    ignored = set()
    for (key, x, y, nx, ny), hit in zip(suspects, (yield from query(rays))):
        if not hit:
            continue
        px, py, _ = frame.local(hit[RayHitField.POINT])
        hx, hy, _ = frame.direction(hit[RayHitField.NORMAL])
        if (
            abs((px - x) * nx + (py - y) * ny) < WALL_OFFSET_TOLERANCE_CM
            and hx * nx + hy * ny > WALL_NORMAL_MIN_DOT
        ):
            ignored.add(key)
    return (
        sites - ignored,
        {key: p for key, p in points.items() if key not in ignored},
        len(ignored),
    )
