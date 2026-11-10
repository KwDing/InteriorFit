"""Recover hidden short walls after an ambiguous coarse survey of a bent corridor.

No Z/N labels or reference meshes are consulted. Several viewpoints measure wall
supports, a bounded arrangement proposes cells, and physical probes decide which
cells belong to the seed. Incomplete evidence leaves the existing grid fallback.
"""
import math
from . import plane_cells, plane_loop
from .rays import query
from .planar_checks import walls_match, check_heights
from .candidate import offer, prism
from .site_checks import exclude_wall_sites


def wall_groups(frame, hits):
    planes, samples = [], []
    for hit in hits:
        if not hit:
            continue
        nx,ny,nz = frame.direction(hit[1])
        if abs(nz) > 0.04:
            continue
        length = math.hypot(nx,ny)
        nx,ny = nx/length,ny/length
        x,y,_ = frame.local(hit[0])
        plane = (nx,ny,nx*x+ny*y)
        index = next((i for i,p in enumerate(planes) if plane_loop._same(plane,p)),None)
        if index is None:
            index = len(planes)
            planes.append(plane)
            samples.append([])
        samples[index].append((x,y))
    return list(zip(planes,samples))


def supports(frame, hits):
    return [plane for plane,_ in wall_groups(frame,hits)]


def roof_hit(frame, hit, roof):
    return bool(hit and abs(frame.local(hit[0])[2]-roof) <= 5 and frame.direction(hit[1])[2] < -0.98)


def verified_supports(frame, hits, roof):
    """Keep interior faces: roof on the inward side, open air on the outward side.

This removes wall-panel end faces and outside/back faces seen through openings.
Shared-roof partitions intentionally retain the conservative grid fallback.
"""
    groups = wall_groups(frame,hits)
    if len(groups)>24:
        return []
    candidates, rays = [], []
    for (nx,ny,d),points in groups:
        points = sorted(points,key=lambda p:-ny*p[0]+nx*p[1])
        # A short/occluded wall may have only one hit. It remains provisional;
        # independent wall positions verify the final outline later.
        candidates.append((nx,ny,d))
        # This is a provisional face test. The final wall check independently
        # measures two other positions at two heights before any room is offered.
        for fraction in (.5,):
            x,y = points[round(fraction*(len(points)-1))]
            for sign in (1,-1):
                p = (x+sign*15*nx,y+sign*15*ny)
                rays.append((frame.world((*p,roof-22)),frame.world((*p,roof+12))))
    checked = [roof_hit(frame,h,roof) for h in (yield from query(rays))]
    return [p for i,p in enumerate(candidates) if checked[2*i] and not checked[2*i+1]]


def bent_band(planes):
    """Mixed wall directions plus a narrow opposing pair suggest a hidden bend."""
    directions = []
    for nx,ny,_ in planes:
        if not any(abs(nx*x+ny*y) > 0.995 for x,y in directions):
            directions.append((nx,ny))
    return 3 <= len(directions) <= 8 and bool(band_pair(planes))


def band_pair(planes):
    pairs = [(a,b) for i,a in enumerate(planes) for b in planes[i+1:]
             if a[0]*b[0]+a[1]*b[1] < -0.999 and 50 < -(a[2]+b[2]) < 240
             and not any(abs(a[0]*p[0]+a[1]*p[1]) < .05 for p in planes)]
    return min(pairs,key=lambda pair:-(pair[0][2]+pair[1][2])) if pairs else None


def viewpoints(sites, points, spacing):
    points = [points[key] for key in sorted(sites)]
    chosen = [(0,0)]
    for _ in range(3):
        point = max(points,key=lambda p:min(math.dist(p,q) for q in chosen))
        if min(math.dist(point,q) for q in chosen) < spacing:
            break
        chosen.append(point)
    return chosen[1:]


def measure_walls(frame, roof, sites, points, spacing):
    rays = []
    for x,y in viewpoints(sites,points,spacing):
        start = frame.world((x,y,roof-5))
        for i in range(16):
            angle = i*math.tau/16
            rays.append((start,frame.world((x+2200*math.cos(angle),y+2200*math.sin(angle),roof-5))))
    return (yield from query(rays))


def occupied_cells(frame, roof, cells, blocked_evidence=None):
    centers = [plane_cells.center(poly) for poly in cells]
    rays = [(frame.world((x,y,roof-22)),frame.world((x,y,roof+12))) for x,y in centers]
    hits = yield from query(rays)
    sites = {i for i,h in enumerate(hits) if h and abs(frame.local(h[0])[2]-roof) <= 5
             and frame.direction(h[1])[2] < -0.98}
    seed = next((i for i in sorted(sites) if plane_cells.contains(cells[i],(0,0))),None)
    if seed is None:
        return set()
    pairs = [(items[0][0],items[1][0]) for items in plane_cells.edges(cells).values()
             if len(items)==2 and all(item[0] in sites for item in items)]
    rays = [(frame.world((*centers[a],roof-30)),frame.world((*centers[b],roof-30))) for a,b in pairs]
    blocked = yield from query(rays)
    graph = {i:set() for i in sites}
    for (a,b),hit in zip(pairs,blocked):
        if not hit:
            graph[a].add(b)
            graph[b].add(a)
    reached, work = {seed},[seed]
    while work:
        for cell in graph[work.pop()]-reached:
            reached.add(cell)
            work.append(cell)
    if any(hit and a in reached and b in reached for (a,b),hit in zip(pairs,blocked)):
        if blocked_evidence is not None:
            blocked_evidence.extend(hit for (a,b),hit in zip(pairs,blocked)
                                    if hit and a in reached and b in reached)
        return set()  # A real interior partition requires the conservative fallback.
    return reached


def roof_ends_at_walls(frame, ring, roof):
    """A sampled wall plane must not truncate another roof-covered arm.

Shared ceilings or deep eaves are ambiguous and retain the grid fallback. This
guard is additional evidence, not permission to bridge a window or a doorway.
"""
    rays = []
    for a,b in zip(ring,ring[1:]+ring[:1]):
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = math.hypot(dx,dy)
        for t in (.25,.75):
            # Check immediately across this boundary. A distant roof can belong
            # to another arm/eave and is not evidence of continuous interior.
            x,y = a[0]+t*dx+15*dy/length,a[1]+t*dy-15*dx/length
            if not plane_cells.inside(ring,(x,y)):
                rays.append((frame.world((x,y,roof-22)),frame.world((x,y,roof+12))))
    return not any(roof_hit(frame,h,roof) for h in (yield from query(rays)))


def connect_sites(frame, roof, cells, reached, sites, points, ring):
    """Every roof proposal must physically reach its cell's connected center.

Roof continuity alone cannot merge two rooms separated by a partition that was
not included in the exterior wall supports. These links test inside each cell.
"""
    rays = []
    for site in sorted(sites):
        point = points[site]
        if plane_cells.near_edge(ring,point):
            continue  # Same 4 cm boundary ambiguity as matches_sites, not room air.
        owners = [i for i in sorted(reached) if plane_cells.contains(cells[i],point)]
        if not owners:
            return False
        center = plane_cells.center(cells[owners[0]])
        if math.dist(point,center)>1:
            rays.append((frame.world((*point,roof-30)),frame.world((*center,roof-30))))
    return not any((yield from query(rays)))


def fit(frame, roof, evidence, spacing, extent):
    sites, hits = evidence.get('sites',set()), evidence.get('hits',[])
    initial = supports(frame,hits)
    if not sites or not bent_band(initial):
        return None
    evidence['band'] = band_pair(initial)
    from .corner_survey import expand
    evidence = yield from expand(frame,roof,evidence)
    if not evidence:
        return None
    sites,hits = evidence['sites'],evidence['hits']
    spacing = evidence['spacing']
    observed = hits + (yield from measure_walls(frame,roof,sites,evidence['points'],spacing))
    layout = yield from recover_layout(frame,roof,evidence,observed,extent)
    if not layout:
        return None
    ring,cells,reached,sites,points,model,details = layout
    if not (yield from verify_candidate(frame,roof,cells,reached,sites,points,ring,model)):
        return None
    details.update(method='multi_view_planes',cells=len(cells),interior_cells=len(reached),
                   viewpoints=len(viewpoints(sites,points,spacing)))
    return ring,details


def recover_layout(frame,roof,evidence,observed,extent):
    """A roof site beyond the candidate calls for one new view, not a dense restart."""
    for repair in range(2):
        planes = yield from verified_supports(frame,observed,roof)
        cells = plane_cells.partition(planes,extent)
        if not cells:
            return None
        reached = yield from occupied_cells(frame,roof,cells)
        ring = plane_cells.outline(cells,reached)
        if not ring:
            return None
        model = prism(frame,roof,ring,len(reached))
        yield offer(model,roof_connectivity='pending',walls='pending',heights='pending',internal_links='pending')
        sites,points,wall_sites = yield from exclude_wall_sites(frame,roof,ring,evidence['sites'],evidence['points'])
        matches = plane_loop.matches_sites(ring,sites,points)
        yield offer(model,roof_connectivity='passed' if matches else 'conflict',walls='pending',heights='pending',internal_links='pending')
        if matches:
            details = dict(planes=len(planes),wall_sites=wall_sites,repair_views=repair)
            return ring,cells,reached,sites,points,model,details
        missed = [points[s] for s in sorted(sites) if not plane_cells.inside(ring,points[s])
                  and not plane_cells.near_edge(ring,points[s],12)]
        if repair or not missed:
            return None
        from .site_checks import closest_edge
        point = max(missed,key=lambda p:closest_edge(ring,p)[0])
        observed += yield from measure_missing_view(frame,roof,point)


def measure_missing_view(frame,roof,point):
    x,y = point
    start = frame.world((x,y,roof-5))
    rays = [(start,frame.world((x+2200*math.cos(i*math.tau/16),
                              y+2200*math.sin(i*math.tau/16),roof-5))) for i in range(16)]
    return (yield from query(rays))


def verify_candidate(frame,roof,cells,reached,sites,points,ring,model):
    checks = dict(roof_connectivity='passed',internal_links='pending',roof_boundary='pending',
                  walls='pending',heights='pending')
    probes = [plane_cells.center(cells[i]) for i in sorted(reached)]
    stages = (
        ('internal_links',connect_sites(frame,roof,cells,reached,sites,points,ring)),
        ('roof_boundary',roof_ends_at_walls(frame,ring,roof)),
        ('walls',walls_match(frame,ring,roof,fractions=(.25,.75))),
        ('heights',check_heights(frame,probes,roof)))
    for name,worker in stages:
        passed = yield from worker
        checks[name] = 'passed' if passed else 'conflict'
        yield offer(model,**checks)
        if not passed:
            return False
    return True
