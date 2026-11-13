"""Bounded roof proposals; connectivity is checked after wall subdivision."""

from interior_fit.rooms.ray_queries import RayHitField, query

# Extend the measured centerline and probe sideways into adjoining arms.
BAND_SPACING_CM = 120
BAND_REACH_CM = 960
LATERAL_OFFSETS_CM = (-240, -120, 120, 240)
MIN_COVERED_SITES = 4
MAX_COVERED_SITES = 110
ROOF_PROBE_BELOW_CM = 22
ROOF_PROBE_ABOVE_CM = 12
ROOF_HEIGHT_TOLERANCE_CM = 5
ROOF_NORMAL_MAX_Z = -0.98
# Keep synthetic site keys separate from the original grid coordinates.
BAND_SITE_KEY = 1000
LATERAL_SITE_KEY = 1001


def roof_sites(frame, roof, fresh, points):
    rays = [
        (
            frame.world((*points[cell], roof - ROOF_PROBE_BELOW_CM)),
            frame.world((*points[cell], roof + ROOF_PROBE_ABOVE_CM)),
        )
        for cell in fresh
    ]
    hits = yield from query(rays)
    return {
        c
        for c, h in zip(fresh, hits)
        if h
        and abs(frame.local(h[RayHitField.POINT])[2] - roof)
        <= ROOF_HEIGHT_TOLERANCE_CM
        and frame.direction(h[RayHitField.NORMAL])[2] < ROOF_NORMAL_MAX_Z
    }


def expand(frame, roof, evidence):
    # Follow the narrowest observed parallel band, not an entire roof
    # rectangle.
    # These are proposal sites; physical cell links still establish
    # reachability.
    a, b = evidence["band"]
    nx, ny = a[:2]
    offset = (a[2] - b[2]) / 2
    points = {
        key: value
        for key, value in evidence["points"].items()
        if key in evidence["measured"]
    }
    fresh = []
    distances = range(-BAND_REACH_CM, BAND_REACH_CM + 1, BAND_SPACING_CM)
    for index, distance in enumerate(distances):
        key = (BAND_SITE_KEY, index)
        points[key] = (
            nx * offset - ny * distance,
            ny * offset + nx * distance,
        )
        fresh.append(key)
    covered = set(evidence["covered"])
    band_sites = yield from roof_sites(frame, roof, fresh, points)
    covered.update(band_sites)
    # Look sideways at the two measured band ends to enter the adjoining arms.
    # This recovers short end walls hidden from a centerline-only viewpoint.
    ends = sorted(band_sites)
    lateral = []
    for end in ends[:1] + ends[-1:]:
        x, y = points[end]
        for distance in LATERAL_OFFSETS_CM:
            key = (LATERAL_SITE_KEY, len(lateral))
            points[key] = (x + nx * distance, y + ny * distance)
            lateral.append(key)
    covered.update((yield from roof_sites(frame, roof, lateral, points)))
    if not MIN_COVERED_SITES <= len(covered) <= MAX_COVERED_SITES:
        return None
    return dict(
        sites=covered,
        hits=evidence["hits"],
        points=points,
        spacing=BAND_SPACING_CM,
    )
