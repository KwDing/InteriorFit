"""Append a stair or ceiling profile to an Unreal dynamic mesh."""

import unreal as u


def append_profile(mesh, result, profile=None):
    sections = result["sections"]
    chain = []
    for index, ordered in ((2, sections), (3, reversed(sections))):
        for row in ordered:
            ends = row[:2] if index == 2 else row[1::-1]
            for x in ends:
                point = (x, row[index])
                if not chain or chain[-1] != point:
                    chain.append(point)
    # Flat consecutive tread/roof runs share a line; intermediate vertices
    # cannot change occupancy and need no cap triangles.
    chain = [
        v
        for i, v in enumerate(chain)
        if (v[0] - chain[i - 1][0]) * (chain[(i + 1) % len(chain)][1] - v[1])
        != (v[1] - chain[i - 1][1]) * (chain[(i + 1) % len(chain)][0] - v[0])
    ]
    low, high = result["lateral"]
    direction = u.Vector(0, 1, 0) if result["axis"] else u.Vector(1, 0, 0)
    rot = u.MathLibrary.make_rot_from_xy(direction, u.Vector(0, 0, 1))
    offset = u.Vector(low, 0, 0) if result["axis"] else u.Vector(0, high, 0)
    from interior_fit.rooms.authoring.append_prism_mesh import append

    append(
        mesh,
        [u.Vector2D(*p) for p in (profile or chain)],
        high - low,
        u.Transform(location=offset, rotation=rot),
    )
    return len(profile or chain)
