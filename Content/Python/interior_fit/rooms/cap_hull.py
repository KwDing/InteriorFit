"""A convex ellipsoid cap built from aligned regular polygons and a flat floor."""
import math

from .roof_mesh import result
from .frame import cross, dot


def is_convex(cap):
    """Verify a closed, consistently wound shell and every local convex dihedral."""
    vertices = cap["vertices"]
    opposites = {}
    for a, b, c in cap["triangles"]:
        for i, j, k in ((a, b, c), (b, c, a), (c, a, b)):
            if (i, j) in opposites:
                return False
            opposites[i, j] = k
    for (i, j), k in opposites.items():
        other = opposites.get((j, i))
        if other is None:
            return False
        a = vertices[i]
        directions = [tuple(x-y for x, y in zip(vertices[t], a)) for t in (j, k, other)]
        inward = cross(directions[0], directions[1])
        length = math.sqrt(dot(inward, inward))
        if length < 1.e-6 or dot(inward, directions[2]) < -0.001*length:
            return False
    return True


def _band_faces(lower, upper):
    """Side hull of two parallel regular polygons, ordered by their support directions."""
    faces = []
    for source, target, reverse in ((lower, upper, False), (upper, lower, True)):
        ids, phase = source
        other, other_phase = target
        for i, v in enumerate(ids):
            # At this edge's outward normal, pick the extremal vertex on the
            # other ring. Break equal-support ties in opposite directions.
            normal_turn = phase + (i+0.5)/len(ids)
            support = (normal_turn-other_phase)*len(other)
            j = math.floor(support+0.5+(-1.e-9 if reverse else 1.e-9))
            face = (v, ids[(i+1) % len(ids)], other[j % len(other)])
            faces.append(face[::-1] if reverse else face)
    return faces


def staggered(frame, center, radii, theta, chord_cm):
    """Allocate angular samples by ring circumference; keep the base exactly planar."""
    cx, cy, cz = center
    a, b, h = radii
    radius = max(radii)
    angle = 2*math.acos(1-min(chord_cm/radius, 0.3))
    factor = 1+0.72*chord_cm/radius
    low = math.asin(-cz/(h*factor))
    bands = max(3, math.ceil((math.pi/2-low)/(0.866*angle)))
    vertices, faces, rings = [], [], []
    for j in range(bands):
        phi = low+(math.pi/2-low)*j/bands
        count = max(5, math.ceil(math.tau*math.cos(phi)/angle))
        phase = 0.5*(j % 2)/count
        ring = list(range(len(vertices), len(vertices)+count)), phase
        scale = factor*math.cos(phi)
        z = cz+h*factor*math.sin(phi) if j else 0.0
        for i in range(count):
            az = math.tau*(phase+i/count)
            x, y = scale*a*math.cos(az), scale*b*math.sin(az)
            vertices.append((cx+x*math.cos(theta)-y*math.sin(theta),
                             cy+x*math.sin(theta)+y*math.cos(theta), z))
        if rings:
            faces.extend(_band_faces(rings[-1], ring))
        else:
            faces.append(ring[0][::-1])
        rings.append(ring)
    apex = len(vertices)
    vertices.append((cx, cy, cz+h))
    ids = rings[-1][0]
    faces.extend((v, ids[(i+1) % len(ids)], apex) for i, v in enumerate(ids))
    cap = result(frame, "ellipsoid_cap", vertices[:len(rings[0][0])], vertices, faces)
    cap.update(center=center, radii=radii, yaw_radians=theta, hull_chord_cm=chord_cm)
    return cap


def build(frame, center, radii, theta, chord_cm):
    """Chord sagitta is a resolution parameter; verify the cooked collision separately."""
    cx, cy, cz = center
    a, b, h = radii
    radius = max(radii)
    sides = max(12, 2 * math.ceil(math.pi / (2 * math.acos(1 - min(chord_cm/radius, 0.3)))))
    start = math.asin(-cz / h)
    bands = max(3, math.ceil((math.pi/2 - start) * sides / math.tau))
    # Place each facet between the inscribed chord and its parallel tangent.
    # A plain inscribed hull systematically excludes a band along the entire wall.
    meridian = 2 / (1 + math.cos((math.pi/2 - start) / (2*bands)))
    azimuth = 2 / (1 + math.cos(math.pi/sides))
    start = math.asin(-cz / (h*meridian))
    directions = []
    for i in range(sides):
        angle = math.tau * i / sides
        x, y = a*math.cos(angle), b*math.sin(angle)
        directions.append((x*math.cos(theta)-y*math.sin(theta), x*math.sin(theta)+y*math.cos(theta)))
    vertices, faces = [], [list(reversed(range(sides)))]
    for j in range(bands):
        latitude = start + (math.pi/2-start)*j/bands
        scale = meridian*azimuth*math.cos(latitude)
        z = cz + h*meridian*math.sin(latitude) if j else 0.0
        vertices.extend((cx+scale*x, cy+scale*y, z) for x, y in directions)
        if j:
            for i in range(sides):
                k = (i+1) % sides
                faces.append(((j-1)*sides+i, (j-1)*sides+k, j*sides+k, j*sides+i))
    apex = len(vertices)
    vertices.append((cx, cy, cz+h))
    faces.extend(((bands-1)*sides+i, (bands-1)*sides+(i+1) % sides, apex) for i in range(sides))
    cap = result(frame, "ellipsoid_cap", vertices[:sides], vertices, faces)
    cap.update(center=center, radii=radii, yaw_radians=theta, hull_chord_cm=chord_cm)
    return cap
