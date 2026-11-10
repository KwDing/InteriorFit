"""Inspect a planar budget exception in the viewport before authoring the Room."""
import json
import unreal as u
from .rooms.brush import create_room
from .rooms.frame import FloorFrame, cross
from .rooms.review_evidence import message as evidence_message

_pending = None


def show_final(world, result, label, prepared):
    """Show the automatically reconstructed/decimated mesh without another trigger step."""
    global _pending
    from .room_preview import create
    preview,count = create(world,result,label,prepared)
    if result.get('candidate_checks'):
        preview.set_actor_label(preview.get_actor_label()+' 待复核')
    preview.tags = list(preview.tags)+[u.Name('InteriorFitBoundaryReview')]
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    if _pending and u.SystemLibrary.is_valid(_pending[0]):
        actors.destroy_actor(_pending[0])
    _pending = preview,result,label,dict(prepared=prepared,triangles=count)
    actors.set_selected_level_actors([preview])
    detail = result.get('straightened')
    message = (f"已自动拉直：{detail['before_corners']} → {detail['after_corners']} 个角，"
               f"{detail['wall_supported']}/{detail['wall_total']} 段有多点墙面支持。" if detail
               else '已生成最终几何候选。')
    message = evidence_message(result) or message
    u.log_warning(message+f'最终 Room 为 {count} 个声学三角形。橙色为最终网格；检查后可执行「采纳所选 Room 候选」，或删除预览重新拟合。')


def wire_points(result, outline):
    frame = FloorFrame(result["origin"],result["axis_z"])
    frame.x = result["axis_x"]
    frame.y = cross(frame.z,frame.x)
    lo = [frame.world((x,y,result["floor"])) for x,y in outline]
    hi = [frame.world((x,y,result["roof"])) for x,y in outline]
    # One continuous polyline: bottom perimeter, posts, then top perimeter.
    points = lo + [lo[0]]
    for a,b in zip(lo,hi):
        points.extend((a,b,a))
    points.extend((lo[0],hi[0],*hi[1:],hi[0]))
    return points


def show(world,result,label,info):
    global _pending
    preview = u.InteriorFitLibrary.create_surface_preview(world,json.dumps(dict(
        shape="RoomCandidate",sources=[],label=label,points=wire_points(result,info["outline"]))))
    if not preview:
        raise ValueError("无法创建边界候选预览")
    preview.tags = list(preview.tags) + [u.Name("InteriorFitBoundaryReview")]
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    if _pending and u.SystemLibrary.is_valid(_pending[0]):
        actors.destroy_actor(_pending[0])
    _pending = preview,result,label,info
    actors.set_selected_level_actors([preview])
    u.log_warning(f"边界差 {info['error']:.1f} cm，容许 {info['tolerance']:.1f} cm。"
                  +evidence_message(result)+"可移动视口检查橙色线框，再选择工具 → Audio Auto Fit → 采纳所选 Room 候选。")
    return preview


def apply_selected():
    global _pending
    from .editor import configure_wwise_room, room_volumes
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    subsystem = u.get_editor_subsystem(u.UnrealEditorSubsystem)
    if (not _pending or not u.SystemLibrary.is_valid(_pending[0]) or subsystem.get_game_world()
            or actors.get_selected_level_actors() != [_pending[0]] or _pending[0].get_world()!=subsystem.get_editor_world()):
        u.EditorDialog.show_message("Interior Fit","在编辑模式选中当前橙色 Room 候选后重试。",u.AppMsgType.OK)
        return
    preview,result,label,info = _pending
    if any(u.InteriorFitLibrary.contains_point(v,u.Vector(*result["seed"])) for v in room_volumes()):
        u.EditorDialog.show_message("Interior Fit","已有 Room 覆盖这个起点，请重新审核。",u.AppMsgType.OK)
        return
    msg = (f"按当前最终网格创建 Room（{info['triangles']} 个声学三角形）？"
           if 'prepared' in info else
           f"边界偏差 {info['error']:.1f} cm，容许 {info['tolerance']:.1f} cm。按当前线框创建 Room？")
    msg = evidence_message(result)+'\n'+msg if result.get('candidate_checks') else msg
    if u.EditorDialog.show_message("Interior Fit",msg,u.AppMsgType.YES_NO)!=u.AppReturnType.YES:
        return
    with u.ScopedEditorTransaction("Accept reviewed room boundary"):
        room = (create_room(preview.get_world(),result,label,prepared=info['prepared']) if 'prepared' in info
                else create_room(preview.get_world(),result,label,approval=info))
        try:
            configure_wwise_room(room)
        except Exception:
            actors.destroy_actor(room)
            raise
    actors.destroy_actor(preview)
    _pending = None
    actors.set_selected_level_actors([room])
