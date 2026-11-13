"""Load host project overrides for Interior Fit."""

import json
from pathlib import Path
from typing import Any

import unreal as u


def load_project_options() -> dict[str, Any]:
    path = Path(u.Paths.project_config_dir()) / "InteriorFit.json"
    options = (
        json.loads(path.read_text(encoding="utf-8-sig"))
        if path.exists()
        else {}
    )
    if not isinstance(options, dict):
        raise ValueError("Config/InteriorFit.json must be a JSON object")
    return options
