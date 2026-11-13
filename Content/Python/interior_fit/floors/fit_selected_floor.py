"""
Public floor authoring commands; each invocation owns an independent
traversal.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
import unreal as u
from interior_fit.editor_scene_adapter import show_error
from interior_fit.portals import discover_openings
from interior_fit.floors.room_scan_session import (
    FloorSession,
    MAX_ROOMS as MAX_ROOMS,
    MAX_PROBES as MAX_PROBES,
    ROOM_GENERATION_LIMIT_MS,
)


def run(
    seed: u.Actor,
    done: Callable[[dict[str, Any]], None],
    failed: Callable[[str], None],
    report_dir: str | Path | None = None,
) -> None:
    FloorSession(seed, done, failed, report_dir).advance()


def selected() -> None:
    try:
        _, actors, _ = discover_openings.scene()
        selection = actors.get_selected_level_actors()
        if len(selection) != 1 or isinstance(selection[0], u.Volume):
            raise ValueError("在本层可通行空间中选一个种子 Actor")
        if confirm_floor():
            run(selection[0], review_result, show_error)
    except Exception as error:
        show_error(error)


def confirm_floor() -> bool:
    prompt = (
        "沿门洞逐房制作本层。已有 Room（含楼梯间）作为边界。\n"
        f"最多制作 {MAX_ROOMS} 间，达到上限时保留已完成的结果。\n"
        f"每间 Room 的生成时限为 {ROOM_GENERATION_LIMIT_MS} ms。\n\n"
        "完成后，请复核自动拟合的 Rooms，再勾选需要的 Portal。\n"
        "继续制作本层？"
    )
    answer = u.EditorDialog.show_message(
        "Interior Fit",
        prompt,
        u.AppMsgType.YES_NO,
    )
    return answer == u.AppReturnType.YES


def review_result(data: dict[str, Any]) -> None:
    if data.get("stop_reason") == "room_limit":
        u.EditorDialog.show_message(
            "Interior Fit",
            f"已达到 {MAX_ROOMS} 间上限，已完成的 Rooms 保留。\n\n"
            "请审核本批结果。需要继续时，从尚未处理的房间重新开始。",
            u.AppMsgType.OK,
        )
    if data["rows"]:
        if not u.InteriorFitLibrary.show_openings(json.dumps(data)):
            raise RuntimeError(
                "Rooms 已保留，但无法打开门洞审核面板。"
                "门洞数据已写入 Saved/InteriorFit/floor_rooms.json。"
            )
    else:
        message = (
            f"创建 {len(data['created_rooms'])} 个 Room，没有可审核的门。"
        )
        if data["skipped"]:
            message += "\n" + data["skipped"][0]["reason"]
        u.EditorDialog.show_message(
            "Interior Fit",
            message + "\n\n详见 Saved/InteriorFit/floor_rooms.json。",
            u.AppMsgType.OK,
        )
