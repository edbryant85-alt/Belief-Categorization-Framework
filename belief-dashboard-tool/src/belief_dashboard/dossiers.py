from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.sources import SourceRegistrationError, title_from_filename, validate_source_file


class QueueSetupError(RuntimeError):
    pass


class DuplicateSourceError(ValueError):
    pass


def register_source(
    source_path: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    source_type: str = "",
    title: str = "",
    author: str = "",
    url: str = "",
    allow_duplicate: bool = False,
    registered_on: date | None = None,
) -> dict[str, Any]:
    path = validate_source_file(source_path, config)
    queue_path = Path(queue_dir)
    dossiers_path = queue_path / config["queues"]["files"]["source_dossiers"]
    import_log_path = queue_path / config["queues"]["files"]["import_log"]
    _require_queue_file(dossiers_path)
    _require_queue_file(import_log_path)

    existing_rows = read_source_dossiers(dossiers_path)
    original_file_path = str(path)
    if not allow_duplicate and _has_existing_source_path(existing_rows, original_file_path):
        raise DuplicateSourceError(
            f"Source already registered for original_file_path: {original_file_path}. "
            "Pass --allow-duplicate to register it again."
        )

    source_id = next_source_id(existing_rows)
    row = {header: "" for header in QUEUE_SCHEMAS["source_dossiers"]}
    row.update(
        {
            "source_id": source_id,
            "source_type": source_type,
            "title": title or title_from_filename(path),
            "author_or_speaker": author,
            "date_added": (registered_on or date.today()).isoformat(),
            "original_file_path": original_file_path,
            "url": url,
            "processing_status": "registered",
        }
    )

    _append_csv_row(dossiers_path, QUEUE_SCHEMAS["source_dossiers"], row)
    append_import_log(
        import_log_path,
        operation="register_source",
        file_path=original_file_path,
        status="success",
        message=f"Registered source {source_id}.",
    )
    return {"source_id": source_id, "dossier_path": str(dossiers_path), "row": row}


def read_source_dossiers(dossiers_path: str | Path) -> list[dict[str, str]]:
    path = Path(dossiers_path)
    _require_queue_file(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def find_source_dossier(
    source_id: str,
    queue_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, str]:
    dossiers_path = Path(queue_dir) / config["queues"]["files"]["source_dossiers"]
    for row in read_source_dossiers(dossiers_path):
        if row.get("source_id") == source_id:
            return row
    raise SourceRegistrationError(f"Source ID not found in source_dossiers.csv: {source_id}")


def find_source_dossiers(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    query: str | None = None,
    source_id: str | None = None,
    file_path: str | Path | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    dossiers_path = Path(queue_dir) / config["queues"]["files"]["source_dossiers"]
    rows = read_source_dossiers(dossiers_path)
    query_text = (query or "").strip().lower()
    source_id_text = (source_id or "").strip().lower()
    file_text = str(file_path or "").strip().lower()
    matches: list[dict[str, str]] = []
    for row in rows:
        if source_id_text and source_id_text not in (row.get("source_id") or "").lower():
            continue
        if file_text and file_text not in str(Path(row.get("original_file_path") or "")).lower():
            continue
        if query_text:
            haystack = " ".join(
                row.get(field, "")
                for field in [
                    "source_id",
                    "title",
                    "source_type",
                    "author_or_speaker",
                    "participants",
                    "url",
                    "context",
                    "short_summary",
                    "original_file_path",
                ]
            ).lower()
            if query_text not in haystack:
                continue
        matches.append(row)
    return matches[:limit] if limit is not None else matches


def next_source_id(rows: list[dict[str, str]]) -> str:
    highest = 0
    for row in rows:
        match = re.fullmatch(r"SRC(\d{4})", (row.get("source_id") or "").strip())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"SRC{highest + 1:04d}"


def append_import_log(
    import_log_path: str | Path,
    *,
    operation: str,
    file_path: str,
    status: str,
    message: str,
    logged_at: datetime | None = None,
) -> None:
    path = Path(import_log_path)
    _require_queue_file(path)
    rows = _read_csv_rows(path)
    log_id = f"LOG{len(rows) + 1:04d}"
    row = {
        "log_id": log_id,
        "timestamp": (logged_at or datetime.now()).replace(microsecond=0).isoformat(),
        "operation": operation,
        "file_path": file_path,
        "status": status,
        "message": message,
    }
    _append_csv_row(path, QUEUE_SCHEMAS["import_log"], row)


def _require_queue_file(path: Path) -> None:
    if not path.exists():
        raise QueueSetupError(
            f"Required queue file not found: {path}. Run: python -m belief_dashboard.cli init-queues"
        )


def _has_existing_source_path(rows: list[dict[str, str]], source_path: str) -> bool:
    target = str(Path(source_path))
    return any(str(Path(row.get("original_file_path") or "")) == target for row in rows)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_csv_row(path: Path, headers: list[str], row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writerow({header: row.get(header, "") for header in headers})
