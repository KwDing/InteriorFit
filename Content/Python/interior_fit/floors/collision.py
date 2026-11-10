"""Room coexistence checks, deliberately independent of two-room merge eligibility."""
import unreal as u
from .. import floor_recovery
from .bounds import brush_bounds


def conflicts(room, nearby, result):
    """Use actual simple-collision convex pieces, not overlapping enclosing boxes.

    Unavailable/oversized collision is unknown, never silently accepted as clear.
    Only the existing cell-based recovery may resolve an unknown pair.
    """
    if not hasattr(u.InteriorFitLibrary,'classify_room_overlap'):
        raise RuntimeError('Interior Fit 的 C++ 模块需要重新编译：缺少 Room 几何重叠检查。')
    checks = [(other,u.InteriorFitLibrary.classify_room_overlap(room,other)) for other in nearby]
    evidence = [dict(other=other.get_actor_label(),relation=relation) for other,relation in checks]
    if any(relation==1 for _,relation in checks):
        return True,evidence
    unknown = [other for other,relation in checks if relation!=0]
    if not unknown:
        return False,evidence
    if not result.get('storey_cells'):
        return True,evidence
    ox,oy,oz = result['origin']
    protected = [floor_recovery.ProtectedRoom(r,brush_bounds(r)) for r in unknown]
    blocked = any(r.blocks(floor_recovery.cell_box(ox+i*40,oy+j*40,oz+lo,oz+hi))
                  for i,j,lo,hi in result['height_cells'] for r in protected)
    return blocked,evidence
