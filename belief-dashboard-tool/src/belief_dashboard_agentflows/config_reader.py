from __future__ import annotations

from pathlib import Path
from typing import Any

from belief_dashboard.config import load_config


def read_config(project_dir: str | Path = ".", config_path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(project_dir) / path
    return load_config(path)
