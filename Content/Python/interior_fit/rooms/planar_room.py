"""Recover a bounded planar room from connected roof samples and measured wall lines."""

import math
from statistics import median
from .frame import FloorFrame, cross, unit
from .planar_checks import walls_match, interior_matches, check_heights, representative_points
from . import plane_loop
from .candidate import offer, prism
from .rays import NEIGHBORS, query
from ..spline_contour import _exterior_loop

SPACING = 120
REACH = 8


def _wall_frame(base, pilot):
    normals = [base.direction(hit[1]) for hit in pilot if hit]
    angles = [4 * math.atan2(y, x) for x, y, z in normals if abs(z) < 0.05]
    if len(angles) < 12:
        return None
    sx, sy = sum(map(math.cos, angles)), sum(map(math.sin, angles))
    if math.hypot(sx, sy) < 0.90 * len(angles):
        # A few repeated but non-orthogonal normals can support a faceted outline.
        directions = {round(math.atan2(y,x), 2) for x,y,z in normals if abs(z)<0.05}
        return base if len(directions) <= 12 else None
    yaw = math.atan2(sy, sx) / 4
    frame = FloorFrame(base.origin, base.z)
    frame.x = unit(tuple(a*math.cos(yaw) + b*math.sin(yaw) for a,b in zip(base.x,base.y)))
    frame.y = cross(frame.z, frame.x)
    return frame


def _connected(sites, seed, blocked=()):
    if seed not in sites:
        return set()
    found, work = {seed}, [seed]
    while work:
        cell = work.pop()
        for dx, dy in NEIGHBORS:
            other = cell[0]+dx, cell[1]+dy
            if other in sites and other not in found and (cell, other) not in blocked:
                found.add(other)
                work.append(other)
    return found


def _ceiling_sites(frame, points, roof):
    rays = [(frame.world((x,y,roof-22)), frame.world((x,y,roof+12))) for x,y in points.values()]
    return {k for k,h in zip(points, (yield from query(rays)))
            if h and abs(frame.local(h[0])[2]-roof) <= 5 and frame.direction(h[1])[2] < -0.98}


def _scout(frame, roof, fallback=None):
    # The bounded survey only proposes wall planes. The returned Brush uses their
    # intersections, so neither its dimensions nor its edge angles snap to this grid.
    lattice = range(-REACH, REACH+1)
    points = {(i,j):(i*SPACING,j*SPACING) for i in lattice for j in lattice}
    # Grow only around reachable roof sites. Testing two neighbor layers at
    # once limits editor ticks without investigating the empty far corners.
    measured, covered = set(), set()
    pending = {key for key in points if max(map(abs,key)) <= 2}
    while pending:
        fresh = {key:points[key] for key in sorted(pending)}
        measured.update(fresh)
        covered.update((yield from _ceiling_sites(frame, fresh, roof)))
        sites = _connected(covered,(0,0))
        if not sites:
            return None
        pending = set()
        frontier = sites
        for _ in range(2):
            frontier = {(i+di,j+dj) for i,j in frontier for di,dj in NEIGHBORS}
            frontier.intersection_update(points)
            frontier.difference_update(measured | pending)
            pending.update(frontier)
    if not 4 <= len(sites) <= 110 or any(max(abs(i),abs(j)) == REACH for i,j in sites):
        return None
    legs,hits = yield from _wall_links(frame,roof,sites)
    blocked = {(a,b) for (a,b,_,_),hit in zip(legs,hits) if hit}
    sites = _connected(sites, (0,0), blocked | {(b,a) for a,b in blocked})
    if fallback is not None:
        fallback.update(sites=sites, covered=covered, measured=measured,
                        hits=[h for (a,_,_,_),h in zip(legs,hits) if a in sites and h], points=points)
    if any(a in sites and b in sites for a,b in blocked):
        # Two reachable probes with a solid partition between them need a finer scan.
        return None
    planes = [[], []]
    for (a,b,dx,dy), hit in zip(legs,hits):
        if not hit or a not in sites or b in sites:
            continue
        axis = 0 if dx else 1
        if frame.direction(hit[1])[axis] * (dx+dy) < -0.995:
            planes[axis].append(frame.local(hit[0])[axis])
    boundary = {(a,b):h for (a,b,_,_),h in zip(legs,hits) if a in sites and b not in sites and h}
    return [_coordinates(values) for values in planes], sites, boundary, points


def _wall_links(frame, roof, sites):
    """On a shared roof, avoid surveying the far side of a separating wall."""
    lazy = len(sites) > 56
    frontier = {(0,0)} if lazy else sites.copy()
    seen, observations = set(), {}
    while frontier:
        seen.update(frontier)
        requests = set()
        for a in frontier:
            for dx,dy in NEIGHBORS:
                b = a[0]+dx, a[1]+dy
                requests.add((a,b))
                if b in sites: requests.add((b,a))
        missing = sorted(requests-observations.keys())
        rays = [(frame.world((a[0]*SPACING,a[1]*SPACING,roof-5)),
                 frame.world((b[0]*SPACING,b[1]*SPACING,roof-5))) for a,b in missing]
        observations.update(zip(missing,(yield from query(rays))))
        frontier = {b for a,b in requests if a in seen and b in sites and b not in seen
                    and not observations[a,b] and not observations[b,a]}
    legs = [(a,b,b[0]-a[0],b[1]-a[1]) for a,b in observations]
    return legs,list(observations.values())


def _coordinates(values):
    groups = []
    for value in sorted(values):
        if not groups or value-groups[-1][0] > 4:
            groups.append([])
        groups[-1].append(value)
    return [median(group) for group in groups]


def _partition(frame, planes, roof):
    xs,ys = planes
    if not (2 <= len(xs) <= 7 and 2 <= len(ys) <= 7):
        return None
    if min(b-a for seq in planes for a,b in zip(seq,seq[1:])) < 55:
        return None
    boxes = {(i,j):(x0,x1,y0,y1) for i,(x0,x1) in enumerate(zip(xs,xs[1:]))
             for j,(y0,y1) in enumerate(zip(ys,ys[1:]))}
    seed = next((k for k,(x0,x1,y0,y1) in boxes.items() if x0 <= 0 <= x1 and y0 <= 0 <= y1), None)
    centers = {k:((a+b)/2,(c+d)/2) for k,(a,b,c,d) in boxes.items()}
    sites = yield from _ceiling_sites(frame, centers, roof)
    edges = [(k,n) for k in sorted(sites) for n in ((k[0]+1,k[1]),(k[0],k[1]+1)) if n in sites]
    rays = [(frame.world((*centers[a],roof-20)),frame.world((*centers[b],roof-20))) for a,b in edges]
    blocked = {(a,b) for (a,b),h in zip(edges,(yield from query(rays))) if h}
    occupied = _connected(sites, seed, blocked | {(b,a) for a,b in blocked})
    if not occupied or any(a in occupied and b in occupied for a,b in blocked):
        return None
    try:
        loop = _exterior_loop(occupied)
    except ValueError:
        return None
    corners = [p for i,p in enumerate(loop) if loop[i-1][0] != loop[(i+1)%len(loop)][0]
               and loop[i-1][1] != loop[(i+1)%len(loop)][1]]
    if not 6 <= len(corners) <= 24:
        return None
    return [(xs[i],ys[j]) for i,j in corners], [boxes[key] for key in sorted(occupied)]


def fit(base, pilot, roof, recover_bends=True):
    frame = _wall_frame(base, pilot)
    if not frame or roof < 190:
        return None
    fallback = {}
    evidence = yield from _scout(frame, roof, fallback)
    if not evidence:
        return (yield from _bent_room(frame,roof,fallback)) if recover_bends else None
    planes, sites, boundary, points = evidence
    ring = plane_loop.corners(frame,sites,boundary)
    if ring and plane_loop.matches_sites(ring, sites, points):
        probes = representative_points([points[s] for s in sorted(sites)],limit=8)
        model = _result(frame,roof,ring,len(probes))
        checks = dict(roof_connectivity='passed',walls='pending',heights='pending')
        yield offer(model,**checks)
        walls = yield from walls_match(frame,ring,roof,fractions=(.25,.75))
        checks['walls'] = 'passed' if walls else 'conflict'
        yield offer(model,**checks)
        if walls:
            heights = yield from check_heights(frame,probes,roof)
            checks['heights'] = 'passed' if heights else 'conflict'
            yield offer(model,**checks)
            if heights:
                return model
    layout = yield from _partition(frame, planes, roof)
    if layout:
        ring,cells = layout
        if (yield from walls_match(frame,ring,roof,fractions=(.25,.75))) and (yield from interior_matches(frame,cells,roof)):
            return _result(frame,roof,ring,len(cells))
    return (yield from _bent_room(frame,roof,fallback)) if recover_bends else None


def try_band(base, pilot, roof):
    from . import corner_room
    frame = _wall_frame(base,pilot)
    if not frame or not corner_room.bent_band(corner_room.supports(frame,pilot)):
        return None,False
    evidence = dict(points={(0,0):(0,0)},sites={(0,0)},covered={(0,0)},measured={(0,0)},
                    hits=[h for h in pilot if h])
    return (yield from _bent_room(frame,roof,evidence)),True


def _bent_room(frame, roof, evidence):
    from . import corner_room
    fitted = yield from corner_room.fit(frame,roof,evidence,SPACING,SPACING*REACH)
    if not fitted:
        return None
    ring, details = fitted
    result = _result(frame,roof,ring,details['interior_cells'])
    result.update(preview_required=True, verified_wall_planes=details)
    return result


def _result(frame,roof,ring,count):
    return prism(frame,roof,ring,count)
