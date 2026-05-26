from __future__ import annotations

from datetime import datetime
from pathlib import Path


def resolve_project_path(path_value: str | Path, base_dir: str | Path | None = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path

    root = Path(base_dir) if base_dir is not None else Path.cwd()
    return root / path


def timestamp_for_filename(now: datetime | None = None) -> str:
    value = now or datetime.now()
    return value.strftime("%Y-%m-%d_%H%M%S")


def timestamp_iso(now: datetime | None = None) -> str:
    value = now or datetime.now()
    return value.replace(microsecond=0).isoformat()
