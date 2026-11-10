"""Public floor authoring commands; each invocation owns an independent traversal."""

import json
import unreal as u
from . import openings
from .floors.bounds import (
    brush_bounds as brush_bounds,
    may_overlap as may_overlap,
    room_at as room_at,
    door_candidate as door_candidate,
)
from .floors.session import FloorSession, MAX_ROOMS as MAX_ROOMS, MAX_PROBES as MAX_PROBES


def run(seed, done, failed, report_dir=None):
    FloorSession(seed, done, failed, report_dir).advance()


def selected():
    _, actors, _ = openings.scene()
    selection = actors.get_selected_level_actors()
    if len(selection) != 1 or isinstance(selection[0], u.Volume):
        raise ValueError("在本层可通行空间中选一个种子 Actor")
    if confirm_floor():
        run(selection[0], review_result, u.log_error)


def confirm_floor():
    prompt = "沿门洞逐房制作本层，最多 12 间，达到上限即保留结果并停止。已有 Room（含楼梯间）作为边界。每房生成限 500 ms。完成后请复核自动近似的 Rooms，再勾选需要的 Portal。继续？"
    return u.EditorDialog.show_message("Interior Fit", prompt, u.AppMsgType.YES_NO) == u.AppReturnType.YES


def review_result(data):
    if data.get('stop_reason')=='room_limit':
        u.EditorDialog.show_message('Interior Fit','已达到 12 间上限，已完成的 Rooms 保留。请审核本批结果；需要继续时，从尚未处理的房间重新开始。',u.AppMsgType.OK)
    if data["rows"]:
        u.InteriorFitLibrary.show_openings(json.dumps(data))
    else:
        message = f"创建 {len(data['created_rooms'])} 个 Room，没有可审核的门。"
        if data["skipped"]:
            message += "\n" + data["skipped"][0]["reason"]
        u.EditorDialog.show_message(
            "Interior Fit", message + "\n详见 Saved/InteriorFit/floor_rooms.json。", u.AppMsgType.OK
        )
