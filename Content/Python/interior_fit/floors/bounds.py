import unreal as u


def room_at(rooms, point):
    return next((r for r in rooms if u.InteriorFitLibrary.contains_point(r, u.Vector(*point))), None)


def brush_bounds(room):
    origin, extent = room.get_actor_bounds(True)
    return [(o - e, o + e) for o, e in zip(origin.to_tuple(), extent.to_tuple())]


def may_overlap(a, b):
    # Broad phase only. Overlapping boxes must pass the collision narrow phase.
    return all(
        min(hi, other_hi) - max(lo, other_lo) > 0.5
        for (lo, hi), (other_lo, other_hi) in zip(brush_bounds(a), brush_bounds(b))
    )


def door_candidate(row):
    return (
        row["structural_support"] > 0
        and row["sill_above_boundary_bottom"] <= 35
        and row["half_extent"][1] * 2 >= 65
        and row["half_extent"][2] * 2 >= 166
    )
