"""Align wall edges with the sampled grid boundary."""


def align_outer_edges(walls, reached, x, y, step):
    """
    Snap only outer lattice lines supported by multiple near-axis wall
    returns.
    """
    corrections = []
    for axis, coord, origin in (("x", 0, x), ("y", 1, y)):
        ids = [cell[coord] for cell in reached]
        for index, sign in ((min(ids), 1), (max(ids) + 1, -1)):
            edge = origin + (index - 0.5) * step
            values = sorted(
                p[coord]
                for n, p in walls
                if n[coord] * sign > 0.9995
                and abs(p[coord] - edge) < step * 0.48
            )
            if len(values) >= 3 and values[-1] - values[0] < 3:
                corrections.append((axis, index, values[len(values) // 2]))
    return corrections
