"""Validate the editor box-scan settings and limits."""

import math

# Bounds for the user-configurable box sampling grid.
MAX_SCAN_RANGE_CM = 1500
MIN_SCAN_GRID_CM = 25


def validate_settings(settings):
    for name in ("range_cm", "grid_cm", "step_cm", "headroom_cm"):
        value = settings[name]
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid " + name)
    if (
        settings["range_cm"] > MAX_SCAN_RANGE_CM
        or settings["grid_cm"] < MIN_SCAN_GRID_CM
    ):
        raise ValueError(
            f"Scan budget exceeded: range <={MAX_SCAN_RANGE_CM} cm, "
            f"grid >={MIN_SCAN_GRID_CM} cm"
        )
