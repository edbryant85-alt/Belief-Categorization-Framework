from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_FILENAME = "config.yaml"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    cwd_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config
    return project_root() / DEFAULT_CONFIG_FILENAME


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")

    return data
