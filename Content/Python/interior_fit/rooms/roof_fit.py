"""Fit either an A-frame or a horizontally oriented ellipsoid to independent shell returns."""
import math
import random
from itertools import combinations
from .frame import cross, dot, unit
from .rays import query
from . import roof_mesh


def _solve(matrix, rhs):
    rows = [list(row)+[v] for row, v in zip(matrix, rhs)]
    for i in range(len(rows)):
        pivot = max(range(i, len(rows)), key=lambda j: abs(rows[j][i]))
        if abs(rows[pivot][i]) < 1e-9:
            return None
        rows[i], rows[pivot] = rows[pivot], rows[i]
        rows[i] = [v/rows[i][i] for v in rows[i]]
        for j, row in enumerate(rows):
            if j != i:
                rows[j] = [v-row[i]*w for v, w in zip(row, rows[i])]
    return [row[-1] for row in rows]


def _feature(p):
    x, y, z = (v/500 for v in p)
    return (x*x, x*y, y*y, x, y, 1, z), z*z


def _coefficients(samples):
    rows, values = zip(*[_feature(p) for p, n in samples])
    cols = list(zip(*rows))
    return _solve([[dot(a, b) for b in cols] for a in cols], [dot(a, values) for a in cols])


def _inlier(coeff, p, normal):
    row, value = _feature(p)
    a, b, c, d, e, _, g = coeff
    x, y, z = (v/500 for v in p)
    grad = (2*a*x+b*y+d, b*x+2*c*y+e, g-2*z)
    length = math.sqrt(dot(grad, grad))
    return (length > 1e-6 and abs(dot(row, coeff)-value)*500 < 6*length
            and dot(grad, normal) > 0.94*length)


def _axes(coeff):
    a, b, c, d, e, f, g = coeff
    center = _solve([[-2*a, -b], [-b, -2*c]], [d, e])
    if not center:
        return None
    x, y = center
    z = g/2
    height2 = f+(x*d+y*e)/2+z*z
    mid, delta = -(a+c)/2, math.hypot(a-c, b)/2
    if mid-delta <= 0 or height2 <= z*z:
        return None
    radii = [500*math.sqrt(height2/k) for k in (mid+delta, mid-delta, 1)]
    if min(radii) < 80 or max(radii) > 1800:
        return None
    return (500*x, 500*y, 500*z), radii, math.atan2(-b, c-a)/2


def _dome(frame, train, test, triangle_budget=None):
    rng = random.Random(2971)
    best = []
    for _ in range(32):
        coeff = _coefficients(rng.sample(train, 9))
        if not coeff or not _axes(coeff):
            continue
        support = [s for s in train if _inlier(coeff, *s)]
        if len(support) > len(best):
            best = support
        if len(best) >= 0.96*len(train):
            break
    if len(best) < 0.84*len(train):
        return None
    coeff = _coefficients(best)
    axes = _axes(coeff) if coeff else None
    if axes and sum(_inlier(coeff, *s) for s in test) >= 0.82*len(test):
        if triangle_budget is not None:
            from .budget_cap import build
            if isinstance(triangle_budget, dict):
                from .room_budget import cap_target
                triangle_budget = min(cap_target(axes[0], axes[1], triangle_budget),
                                      triangle_budget.get("cap_max", 48))
            return build(frame, *axes, triangle_budget)
        return roof_mesh.ellipsoid(frame, *axes)


def _plane_groups(samples):
    groups = []
    for p, n in samples:
        d = dot(p, n)
        match = next((g for g in groups if dot(g[0], n) > 0.999 and abs(g[1]-d) < 3), None)
        if match:
            match[2] += 1
        else:
            groups.append([n, d, 1])
    return groups


def _ridge(frame, samples, test, groups=None):
    groups = _plane_groups(samples) if groups is None else groups
    planes = [(n, d) for n, d, k in groups if k >= 3]
    if len(planes) != 4 or sum(n[2] < -0.15 for n, d in planes) != 2:
        return None
    if sum(any(abs(dot(p, m)-d) < 4 and dot(n, m) > .99 for m, d in planes) for p, n in test) < 0.85*len(test):
        return None
    planes.append(((0, 0, 1), 0))
    vertices = []
    for group in combinations(planes, 3):
        normals, offsets = zip(*group)
        p = _solve(normals, offsets)
        if p and all(dot(p, n) >= d-0.1 for n, d in planes):
            vertices.append(tuple(p))
    if len(vertices) != 6:
        return None
    faces = []
    for n, d in planes:
        ids = [i for i, p in enumerate(vertices) if abs(dot(p, n)-d) < 0.2]
        if len(ids) < 3:
            return None
        center = [sum(vertices[i][k] for i in ids)/len(ids) for k in range(3)]
        x = unit(tuple(a-b for a, b in zip(vertices[ids[0]], center)))
        y = cross(x, n)
        faces.append(sorted(ids, key=lambda i: math.atan2(dot(vertices[i], y)-dot(center, y),
                                                          dot(vertices[i], x)-dot(center, x))))
    outline = [vertices[i] for i in reversed(faces[-1])]
    fitted = roof_mesh.result(frame, "ridge_prism", outline, vertices, faces)
    fitted["inward_planes"] = planes
    return fitted


def _confirm_sparse_gable(frame, samples, test, groups):
    """Corroborate a lightly observed end wall without accepting a single doorway return."""
    roofs = [(n,d) for n,d,k in groups if n[2] < -0.15 and k >= 3]
    ends = [(n,d,k) for n,d,k in groups if abs(n[2]) < 0.04]
    if len(roofs) != 2 or len(ends) != 2:
        return None
    weak, strong = sorted(ends, key=lambda plane: plane[2])
    n, offset, count = weak
    if count >= 3 or strong[2] < 3 or dot(n,strong[0]) > -0.999:
        return None
    if any(abs(dot(n,m)) > 0.04 for m,_ in roofs):
        return None
    # Build only a hypothesis. Probe both lower shoulders and the upper gable
    # from its interior, so a door at the center can stay open.
    proposal = [(n,offset,3) if (m,d)==(n,offset) else (m,d,k) for m,d,k in groups]
    candidate = _ridge(frame,samples,test,proposal)
    vertices = [p for p in candidate["vertices"] if abs(dot(n,p)-offset)<0.2] if candidate else []
    if len(vertices) != 3:
        return None
    center = tuple(sum(p[i] for p in vertices)/3 for i in range(3))
    sites = [tuple((a+b)/2 for a,b in zip(p,center)) for p in vertices]
    def endpoint(p, step):
        return frame.world(tuple(a+step*b for a,b in zip(p,n)))
    hits = yield from query([(endpoint(p,16),endpoint(p,-16)) for p in sites])
    if all(h and dot(frame.direction(h[1]),n) > 0.995
           and abs(dot(frame.local(h[0]),n)-offset) < 3 for h in hits):
        return candidate


def fit(frame, seed, triangle_budget=None):
    origin = frame.local(seed)
    rays = []
    for j, tilt in enumerate((-12, 5, 29, 53, 75)):
        elevation = math.radians(tilt)
        for i in range(16):
            angle = math.tau*(i+0.31*j)/16
            v = (math.cos(angle)*math.cos(elevation), math.sin(angle)
                 * math.cos(elevation), math.sin(elevation))
            rays.append((seed, frame.world(tuple(a+2600*b for a, b in zip(origin, v)))))
    hits = yield from query(rays)
    samples = [(frame.local(h[0]), frame.direction(h[1]))
               for h in hits if h and frame.direction(h[1])[2] < 0.85]
    train = [s for i, s in enumerate(samples) if i % 4]
    test = samples[::4]
    if len(samples) < 53:
        return None
    groups = _plane_groups(train)
    candidate = _ridge(frame, train, test, groups)
    if not candidate:
        candidate = yield from _confirm_sparse_gable(frame,train,test,groups)
    if not candidate:
        candidate = _dome(frame, train, test, triangle_budget)
    if not candidate:
        return None
    ring = candidate["local_outline"]
    # The shell equations do not guarantee a level floor. Check below the
    # measured seed plane at distinct positions before closing it with one face.
    points = ring[::max(1, len(ring)//10)]
    if "triangle_budget" in candidate:
        # Coarse, volume-balanced corners can extend past the physical floor.
        # Validate the measured building independently of the rendering budget.
        cx,cy,cz = candidate["center"]
        a,b,h = candidate["radii"]
        yaw = candidate["yaw_radians"]
        scale = math.sqrt(1-(cz/h)**2)
        points = []
        for i in range(10):
            angle = i*math.tau/10
            x,y = a*scale*math.cos(angle),b*scale*math.sin(angle)
            points.append((cx+x*math.cos(yaw)-y*math.sin(yaw),
                           cy+x*math.sin(yaw)+y*math.cos(yaw),0))
    floors = yield from query([(frame.world((x*0.65, y*0.65, 70)), frame.world((x*0.65, y*0.65, -30)))
                               for x, y, _ in points])
    if all(h and abs(frame.local(h[0])[2]) < 4 and frame.direction(h[1])[2] > 0.98 for h in floors):
        if candidate["model"] == "ellipsoid_cap" and triangle_budget is None:
            from .thick_shell import within_wall
            return (yield from within_wall(frame,candidate,hits))
        return candidate
