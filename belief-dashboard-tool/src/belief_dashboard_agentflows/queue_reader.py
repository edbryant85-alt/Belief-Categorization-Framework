from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def project_path(project_dir: str | Path, path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return Path(project_dir) / path


def queue_dir(project_dir: str | Path, config: dict[str, Any]) -> Path:
    return project_path(project_dir, config["queues"]["base_dir"])


def manual_imports_dir(project_dir: str | Path, config: dict[str, Any]) -> Path:
    return project_path(project_dir, config["manual_imports"]["input_dir"])


def reports_dir(project_dir: str | Path) -> Path:
    return Path(project_dir) / "reports" / "agentflows"


def queue_file(project_dir: str | Path, config: dict[str, Any], queue_name: str) -> Path:
    return queue_dir(project_dir, config) / config["queues"]["files"][queue_name]


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_queue(project_dir: str | Path, config: dict[str, Any], queue_name: str) -> list[dict[str, str]]:
    return read_csv_rows(queue_file(project_dir, config, queue_name))


def row_by_id(rows: list[dict[str, str]], field: str) -> dict[str, dict[str, str]]:
    return {row.get(field, ""): row for row in rows if row.get(field, "")}
