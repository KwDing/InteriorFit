"""Review, preview and confirm opening candidates in the editor."""

import json
import math
from pathlib import Path

import unreal as u

from .create_portals import create_batch
from .discover_openings import discover, scene


def open_selected(selected_objects=False):
    try:
        _, actors, _ = scene()
        selected = actors.get_selected_level_actors()
        if not selected:
            raise RuntimeError(
                "Select Room volumes or door/window mesh actors first"
            )
        if selected_objects and any(isinstance(a, u.Volume) for a in selected):
            raise RuntimeError(
                "Select physical door/window actors, not Volumes"
            )
        data = discover(selected, selected_objects)
        path = Path(u.Paths.project_saved_dir()) / "InteriorFit/openings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if not data["rows"]:
            raise RuntimeError(
                "No supported openings found. Check collision or use "
                "selected door/window objects."
            )
        if not u.InteriorFitLibrary.show_openings(json.dumps(data)):
            raise RuntimeError("Could not open the Openings panel")
    except Exception as error:
        u.log_error("Interior Fit Openings: " + str(error))
        u.EditorDialog.show_message(
            "Interior Fit Openings", str(error), u.AppMsgType.OK
        )


def _focus_rows(rows):
    """Frame all selected openings, including each rectangle's world-space yaw.
    """
    if not rows:
        return
    lower = [float("inf")] * 3
    upper = [-float("inf")] * 3
    for row in rows:
        angle = math.radians(row["yaw"])
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        e = row["half_extent"]
        extent = [c * e[0] + s * e[1], s * e[0] + c * e[1], e[2]]
        for axis in range(3):
            lower[axis] = min(lower[axis], row["center"][axis] - extent[axis])
            upper[axis] = max(upper[axis], row["center"][axis] + extent[axis])
    u.InteriorFitLibrary.focus_opening(
        u.Vector(*[(a + b) / 2 for a, b in zip(lower, upper)]),
        u.Vector(*[(b - a) / 2 + 20 for a, b in zip(lower, upper)]),
    )


def apply_action(action, data):
    try:
        world, _, _ = scene()
        if world.get_path_name() != data["world"]:
            raise RuntimeError("Map changed; rescan openings")
        if action in ("preview", "focus"):
            rows = data["rows"]
            if not u.InteriorFitLibrary.draw_opening_previews(
                world, json.dumps(rows)
            ):
                raise RuntimeError("Could not draw opening previews")
            _focus_rows(rows)
            u.log(
                f"Interior Fit: previewing {len(rows)} checked openings (Open "
                f"state does not control inclusion)"
            )
            return
        if action != "create":
            raise ValueError("Unknown opening action")
        created = create_batch(data)
        u.EditorDialog.show_message(
            "Interior Fit",
            f"Created {len(created)} Portals.\n\n"
            "You can undo this action. Save the map when ready.",
            u.AppMsgType.OK,
        )
    except Exception as error:
        u.log_error("Interior Fit Openings: " + str(error))
        u.EditorDialog.show_message(
            "Interior Fit Openings", str(error), u.AppMsgType.OK
        )
