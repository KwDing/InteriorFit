"""Automatically reconstruct grid stairs before spending rays on each short edge."""
import math
from .outline_lines import reconstruct_closed
from ..spline_contour import validate_simple_outline


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def edges(ring):
    return [(b[0]-a[0], b[1]-a[1]) for a, b in zip(ring, ring[1:]+ring[:1])]


def reflex_corners(ring):
    """Count substantial inward turns without assuming clockwise input."""
    signed_area = sum(cross(a, b) for a, b in zip(ring, ring[1:]+ring[:1]))
    winding = 1 if signed_area > 0 else -1
    vectors = edges(ring)
    return sum(winding*cross(a, b) < -.15*math.hypot(*a)*math.hypot(*b)
               for a, b in zip(vectors[-1:]+vectors[:-1], vectors))


def stair_motifs(ring, step):
    """A short grid edge between opposite turns suggests a staircase artifact.

    This is a proposal signal, not proof: real zigzag walls can have the same
    footprint. Requiring wall-hit support belongs to the verification stage.
    """
    vectors = edges(ring)
    found = 0
    for i, middle in enumerate(vectors):
        before, after = vectors[i-1], vectors[(i+1) % len(vectors)]
        lengths = [math.hypot(*v) for v in (before, middle, after)]
        if min(lengths) < 1e-6 or lengths[1] > step*1.25:
            continue
        turns = cross(before, middle), cross(middle, after)
        strong = abs(turns[0]) > .7*lengths[0]*lengths[1]
        strong &= abs(turns[1]) > .7*lengths[1]*lengths[2]
        found += int(strong and turns[0]*turns[1] < 0)
    return found


def area(ring):
    return abs(sum(cross(a,b) for a,b in zip(ring,ring[1:]+ring[:1])))/2


def reconstruct(points, step):
    """Return the already straightened contour, or None for an unsuitable outline.

    Coarse concavity must survive removal of one-cell artifacts. Actual wall
    measurements then refine the long edges. The resulting mesh always goes to
    the user's final preview, including any unsupported wall warning.
    """
    ring = [p[:2] for p in points]
    if not 8 <= len(ring) <= 96 or stair_motifs(ring,step) < 2:
        return None
    try:
        coarse = reconstruct_closed(ring,step)
        if not reflex_corners(coarse) or len(coarse)>len(ring)-2:
            return None
        straight = reconstruct_closed(ring,step,True)
        validate_simple_outline(straight)
    except ValueError:
        return None
    original_area = area(ring)
    if original_area < 1 or abs(area(straight)-original_area)>original_area*.12:
        return None
    return [(x,y,points[0][2]) for x,y in straight]


