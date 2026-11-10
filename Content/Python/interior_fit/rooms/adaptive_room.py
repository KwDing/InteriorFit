"""Discover planar room walls from a small number of physically checked viewpoints.

No footprint lattice is filled. New views are chosen from visible wall returns
or roof evidence beyond an incomplete candidate. Existing directed-ray caching
and the whole-scan budget still apply to every query below.
"""
import math
from . import corner_room, plane_cells, plane_loop
from .candidate import offer, prism
from .planar_checks import check_heights, representative_points, walls_match
from .rays import query, together
from .site_checks import closest_edge


def possible_views(frame, hits, start):
    points = []
    for hit in hits:
        if not hit or abs(frame.direction(hit[1])[2])>.04:
            continue
        x,y,_ = frame.local(hit[0])
        if not 100 < math.dist(start,(x,y)) < 2200:
            continue
        points.append((start[0]+.72*(x-start[0]),start[1]+.72*(y-start[1])))
    return points


def choose_view(points, visited):
    if not points:
        return None
    point = max(points,key=lambda p:min(math.dist(p,v) for v in visited))
    return point if min(math.dist(point,v) for v in visited)>80 else None


def check_view(frame, roof, point, visited):
    x,y = point
    origin = min(visited,key=lambda p:math.dist(p,point))
    rays = [(frame.world((x,y,roof*.55)),frame.world((x,y,roof+12))),
            (frame.world((*origin,roof-30)),frame.world((x,y,roof-30)))]
    ceiling,obstruction = yield from query(rays)
    return corner_room.roof_hit(frame,ceiling,roof) and not obstruction


def check_frontier(frame,roof,point,ring,cells,reached):
    """Reach the new arm through its shared edge, not a seed-to-arm chord."""
    _,foot,_ = closest_edge(ring,point)
    anchor = (2*foot[0]-point[0],2*foot[1]-point[1])
    owner = next((i for i in sorted(reached) if plane_cells.contains(cells[i],anchor)),None)
    if owner is None:
        return False
    center = plane_cells.center(cells[owner])
    rays = [(frame.world((*a,roof-30)),frame.world((*b,roof-30)))
            for a,b in ((center,anchor),(anchor,point))]
    return not any((yield from query(rays)))


def boundary_sites(frame, roof, ring):
    """A lower adjacent ceiling is a height transition, not an outdoor opening."""
    points = []
    for a,b in zip(ring,ring[1:]+ring[:1]):
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = math.hypot(dx,dy)
        for t in (.25,.75):
            points.append((a[0]+t*dx+18*dy/length,a[1]+t*dy-18*dx/length))
    rays = [(frame.world((*p,roof*.55)),frame.world((*p,roof+220))) for p in points]
    frontier,transitions = [],[]
    for point,hit in zip(points,(yield from query(rays))):
        if not hit or frame.direction(hit[1])[2]>-.98:
            continue
        height = frame.local(hit[0])[2]
        if 5 < abs(height-roof) <= 70:
            # A window lintel also has a downward normal. Require roof evidence
            # beyond the wall thickness before selecting the stepped-roof path.
            _,foot,_ = closest_edge(ring,point)
            far = (foot[0]+4*(point[0]-foot[0]),foot[1]+4*(point[1]-foot[1]))
            transitions.append((far,height))
        elif abs(height-roof)>5:
            continue
        else:
            frontier.append(point)
    confirmation = [(frame.world((*p,h-12)),frame.world((*p,h+12))) for p,h in transitions]
    links = []
    for point in frontier:
        _,foot,_ = closest_edge(ring,point)
        anchor = (2*foot[0]-point[0],2*foot[1]-point[1])
        links.append((frame.world((*anchor,roof-5)),frame.world((*point,roof-5))))
    hits = yield from query(confirmation+links)
    changed = any(corner_room.roof_hit(frame,h,height) for (_,height),h in zip(transitions,hits))
    return [p for p,h in zip(frontier,hits[len(confirmation):]) if not h],changed


def support_planes(frame,roof,observed):
    """A real wall remains a boundary under eaves or a roof spanning a courtyard.

    Roof on the inside is required. Roof on the outside does not invalidate a
    face: occupied_cells tests physical links, and final checks test its walls.
    """
    groups = corner_room.wall_groups(frame,observed)
    if len(groups)>16:
        return []
    rays = []
    for (nx,ny,d),points in groups:
        points = sorted(points,key=lambda p:-ny*p[0]+nx*p[1])
        x,y = points[len(points)//2]
        p = (x+15*nx,y+15*ny)
        rays.append((frame.world((*p,roof-22)),frame.world((*p,roof+12))))
    hits = yield from query(rays)
    return [plane for (plane,_),h in zip(groups,hits) if corner_room.roof_hit(frame,h,roof)]


def layout(frame, roof, observed):
    planes = yield from support_planes(frame,roof,observed)
    for _ in range(2):
        cells = plane_cells.partition(planes,2200)
        if not cells:
            return None
        blocked = []
        reached = yield from corner_room.occupied_cells(frame,roof,cells,blocked)
        if reached:
            ring = plane_cells.outline(cells,reached,min_corners=3)
            return (ring,cells,reached,planes) if ring else None
        # A blocked chord in a connected U can be an unmeasured exterior wall.
        # Split on its actual hit, then rerun the same partition safety checks.
        extra = [p for p in corner_room.supports(frame,blocked)
                 if not any(plane_loop._same(p,old) for old in planes)]
        if not extra:
            return None
        planes += extra
        observed.extend(blocked)
    return None


def validate(frame,roof,ring,cells,reached,model):
    checks = dict(roof_connectivity='passed',roof_boundary='pending',walls='pending',heights='pending')
    # Preserve the newly closed geometry before the next batch can exhaust the
    # budget. Pending evidence stays visible; this is not automatic acceptance.
    yield offer(model,**checks)
    points = representative_points([plane_cells.center(cells[i]) for i in sorted(reached)],limit=8)
    boundary,wall_ok,height_ok = yield from together([
        boundary_sites(frame,roof,ring),walls_match(frame,ring,roof,fractions=(.25,.75)),
        check_heights(frame,points,roof)])
    frontier,changed = boundary
    checks['roof_boundary'] = 'conflict' if frontier or changed else 'passed'
    checks['walls'] = 'passed' if wall_ok else 'conflict'
    checks['heights'] = 'passed' if height_ok else 'conflict'
    yield offer(model,**checks)
    if changed:
        return False,frontier,True
    if frontier:
        return False,frontier,False
    model['candidate_checks'] = checks
    return True,[],False  # A closed, measured boundary remains reviewable on conflict.


def select_views(points,visited,limit):
    selected = []
    for _ in range(limit):
        point = choose_view(points,visited+selected)
        if point is None:
            break
        selected.append(point)
    return selected


def observe(frame,roof,points,checks):
    """Independent access checks and wall fans share their dispatch frames."""
    allowed = yield from together(checks)
    points = [p for p,ok in zip(points,allowed) if ok]
    groups = yield from together([corner_room.measure_missing_view(frame,roof,p) for p in points])
    extra = yield from together([refine_corners(frame,roof,p,group) for p,group in zip(points,groups)])
    return points,[h for group in groups+extra for h in group if h]


def refine_corners(frame,roof,point,hits):
    """Resolve up to four oblique normal changes between the 16 fan directions."""
    gaps = []
    for index,a in enumerate(hits):
        b = hits[(index+1)%len(hits)]
        if not a or not b:
            continue
        na,nb = frame.direction(a[1]),frame.direction(b[1])
        dot = na[0]*nb[0]+na[1]*nb[1]
        if max(abs(na[2]),abs(nb[2]))<.04 and .05<abs(dot)<.995:
            gaps.append((math.dist(a[0],b[0]),index))
    x,y = point
    angles = [(i+.5)*math.tau/16 for _,i in sorted(gaps,reverse=True)[:4]]
    rays = [(frame.world((x,y,roof-5)),frame.world((x+2200*math.cos(a),y+2200*math.sin(a),roof-5)))
            for a in angles]
    return (yield from query(rays))


def look_ahead(frame,roof,origin,planes,visited):
    """Two axial rays see down a narrow corridor between uniform fan angles."""
    pair = corner_room.band_pair(planes)
    if not pair:
        return [],[]
    a,b = pair
    nx,ny = a[:2]
    shift = (a[2]-b[2])/2-nx*origin[0]-ny*origin[1]
    center = origin[0]+shift*nx,origin[1]+shift*ny
    x,y = center
    rays = [(frame.world((x,y,roof-22)),frame.world((x,y,roof+12))),
            (frame.world((*origin,roof-5)),frame.world((x,y,roof-5)))]
    rays += [(frame.world((x,y,roof-5)),frame.world((x-sign*2200*ny,y+sign*2200*nx,roof-5)))
             for sign in (-1,1)]
    ceiling,blocked,*ends = yield from query(rays)
    if blocked or not corner_room.roof_hit(frame,ceiling,roof):
        return [],[]
    proposals = []
    for hit in ends:
        if hit:
            px,py,_ = frame.local(hit[0])
            proposals.append((x+.88*(px-x),y+.88*(py-y)))
    points = select_views(proposals,visited,1)
    return (yield from observe(frame,roof,points,[check_view(frame,roof,p,[center]) for p in points]))


def fit(frame, pilot, roof):
    observed = [h for h in pilot if h]
    planes = corner_room.supports(frame,observed)
    if not 3 <= len(planes) <= 12 or roof<190:
        return None
    visited = [(0,0)]
    points = select_views(possible_views(frame,observed,(0,0)),visited,3)
    added,hits = yield from observe(frame,roof,points,[check_view(frame,roof,p,visited) for p in points])
    visited += added
    observed += hits
    for attempt in range(3):
        candidate = yield from layout(frame,roof,observed)
        frontier = []
        if candidate:
            ring,cells,reached,planes = candidate
            stable = plane_cells.stable_outline(ring)
            if not stable:
                return None
            model = prism(frame,roof,stable,len(reached))
            passed,frontier,changed = yield from validate(frame,roof,ring,cells,reached,model)
            if changed:
                return dict(height_change=True)
            if passed:
                model.update(preview_required=True,verified_wall_planes=dict(method='adaptive_views',
                    planes=len(planes),cells=len(cells),interior_cells=len(reached),viewpoints=len(visited)))
                return model
        if attempt==2:
            break
        points = select_views(frontier,visited,2)
        if not points:
            break
        checks = [check_frontier(frame,roof,p,ring,cells,reached) for p in points]
        added,hits = yield from observe(frame,roof,points,checks)
        if not added:
            break
        visited += added
        observed += hits
        if attempt==0 and len(added)==1 and corner_room.bent_band(corner_room.supports(frame,observed)):
            more,extra = yield from look_ahead(frame,roof,added[0],corner_room.supports(frame,observed),visited)
            visited += more
            observed += extra
    return None
