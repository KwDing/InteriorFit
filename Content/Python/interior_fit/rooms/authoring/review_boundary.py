"""
Inspect a planar budget exception in the viewport before authoring the
Room.
"""

import json
import unreal as u
from interior_fit.rooms.authoring.create_room_brushes import create_room
from interior_fit.rooms.frame import FloorFrame, cross
from interior_fit.rooms.describe_review_evidence import (
    message as evidence_message,
)

_pending = None


def show_final(world, result, label, prepared):
    """
    Show the automatically reconstructed/decimated mesh without another
    trigger step.
    """
    global _pending
    from interior_fit.rooms.authoring.preview_room import create

    preview, count = create(world, result, label, prepared)
    if result.get("candidate_checks"):
        preview.set_actor_label(preview.get_actor_label() + " 待复核")
    preview.set_editor_property(
        "tags", list(preview.tags) + [u.Name("InteriorFitBoundaryReview")]
    )
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    if _pending and u.SystemLibrary.is_valid(_pending[0]):
        actors.destroy_actor(_pending[0])
    _pending = preview, result, label, dict(prepared=prepared, triangles=count)
    actors.set_selected_level_actors([preview])
    detail = result.get("straightened")
    message = (
        f"已自动拉直：{detail['before_corners']} → {detail['after_corners']} 个角，"
        f"{detail['wall_supported']}/{detail['wall_total']} 段有多点墙面支持。"
        if detail
        else "已生成最终几何候选。"
    )
    message = evidence_message(result) or message
    if result.get("flattened_cap"):
        message += "\n当前面数预算下的椭球帽为平顶，请核对顶面和墙边。"
    u.log_warning(
        message
        + f"最终 Room 为 {count} 个声学三角形。橙色为最终网格；检查后可执行「采纳所选 Room 候选」，或删除预览重新拟合。"
    )


def wire_points(result, outline):
    frame = FloorFrame(result["origin"], result["axis_z"])
    frame.x = result["axis_x"]
    frame.y = cross(frame.z, frame.x)
    lo = [frame.world((x, y, result["floor"])) for x, y in outline]
    hi = [frame.world((x, y, result["roof"])) for x, y in outline]
    # One continuous polyline: bottom perimeter, posts, then top perimeter.
    points = lo + [lo[0]]
    for a, b in zip(lo, hi):
        points.extend((a, b, a))
    points.extend((lo[0], hi[0], *hi[1:], hi[0]))
    return points


def show(world, result, label, info):
    global _pending
    preview = u.InteriorFitLibrary.create_surface_preview(
        world,
        json.dumps(
            dict(
                shape="RoomCandidate",
                sources=[],
                label=label,
                points=wire_points(result, info["outline"]),
            )
        ),
    )
    if not preview:
        raise ValueError("无法创建边界候选预览")
    preview.set_editor_property(
        "tags", list(preview.tags) + [u.Name("InteriorFitBoundaryReview")]
    )
    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    if _pending and u.SystemLibrary.is_valid(_pending[0]):
        actors.destroy_actor(_pending[0])
    _pending = preview, result, label, info
    actors.set_selected_level_actors([preview])
    u.log_warning(
        f"边界差 {info['error']:.1f} cm，容许 {info['tolerance']:.1f} cm。"
        + evidence_message(result)
        + "可移动视口检查橙色线框，再选择工具 → Audio Auto Fit → 采纳所选 Room 候选。"
    )
    return preview


def apply_selected():
    from interior_fit.editor_scene_adapter import (
        configure_wwise_room,
        room_volumes,
    )

    actors = u.get_editor_subsystem(u.EditorActorSubsystem)
    subsystem = u.get_editor_subsystem(u.UnrealEditorSubsystem)
    if (
        not _pending
        or not u.SystemLibrary.is_valid(_pending[0])
        or subsystem.get_game_world()
        or actors.get_selected_level_actors() != [_pending[0]]
        or _pending[0].get_world() != subsystem.get_editor_world()
    ):
        u.EditorDialog.show_message(
            "Interior Fit",
            "在编辑模式选中当前橙色 Room 候选后重试。",
            u.AppMsgType.OK,
        )
        return
    preview, result, label, info = _pending
    if any(
        u.InteriorFitLibrary.contains_point(v, u.Vector(*result["seed"]))
        for v in room_volumes()
    ):
        u.EditorDialog.show_message(
            "Interior Fit",
            "已有 Room 覆盖这个起点。请重新审核。",
            u.AppMsgType.OK,
        )
        return
    if "prepared" in info:
        message = (
            f"最终网格包含 {info['triangles']} 个声学三角形。\n\n"
            "按当前网格创建 Room？"
        )
    else:
        message = (
            f"边界偏差 {info['error']:.1f} cm，"
            f"容许 {info['tolerance']:.1f} cm。\n\n"
            "按当前线框创建 Room？"
        )
    if result.get("candidate_checks"):
        message = evidence_message(result) + "\n" + message
    answer = u.EditorDialog.show_message(
        "Interior Fit",
        message,
        u.AppMsgType.YES_NO,
    )
    if answer != u.AppReturnType.YES:
        return
    with u.ScopedEditorTransaction("Accept reviewed room boundary"):
        room = create_room(
            preview.get_world(),
            result,
            label,
            prepared=info.get("prepared"),
            approval=None if "prepared" in info else info,
        )
        try:
            configure_wwise_room(room)
            if not actors.destroy_actor(preview):
                raise RuntimeError("无法清除 Room 候选预览。")
        except Exception:
            if not actors.destroy_actor(room):
                u.log_error("无法清理采纳失败的 Room：" + label)
            raise
    # Undo can restore this Actor. Keep its review data until a new review.
    actors.set_selected_level_actors([room])
