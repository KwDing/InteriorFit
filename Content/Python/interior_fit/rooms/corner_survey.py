"""Bounded roof proposals; connectivity is checked after wall subdivision."""
from .rays import query

def roof_sites(frame, roof, fresh, points):
    rays = [(frame.world((*points[c],roof-22)),frame.world((*points[c],roof+12))) for c in fresh]
    hits = yield from query(rays)
    return {c for c,h in zip(fresh,hits) if h and abs(frame.local(h[0])[2]-roof) <= 5
            and frame.direction(h[1])[2] < -0.98}


def expand(frame, roof, evidence):
    # Follow the narrowest observed parallel band, not an entire roof rectangle.
    # These are proposal sites; physical cell links still establish reachability.
    a,b = evidence['band']
    nx,ny = a[:2]
    offset = (a[2]-b[2])/2
    points = {key:value for key,value in evidence['points'].items() if key in evidence['measured']}
    fresh = []
    for index,distance in enumerate(range(-960,961,120)):
        key = (1000,index)
        points[key] = (nx*offset-ny*distance,ny*offset+nx*distance)
        fresh.append(key)
    covered = set(evidence['covered'])
    band_sites = yield from roof_sites(frame,roof,fresh,points)
    covered.update(band_sites)
    # Look sideways at the two measured band ends to enter the adjoining arms.
    # This recovers short end walls hidden from a centerline-only viewpoint.
    ends = sorted(band_sites)
    lateral = []
    for end in (ends[:1]+ends[-1:]):
        x,y = points[end]
        for distance in (-240,-120,120,240):
            key = (1001,len(lateral))
            points[key] = (x+nx*distance,y+ny*distance)
            lateral.append(key)
    covered.update((yield from roof_sites(frame,roof,lateral,points)))
    if not 4 <= len(covered) <= 110:
        return None
    return dict(sites=covered,hits=evidence['hits'],points=points,
                spacing=120)
