from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.export_verification import latest_output_workbook
from belief_dashboard.manual_imports import queue_summary
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


def current_workbook_status(
    *,
    main_workbook: str | Path,
    outputs_dir: str | Path,
    export_reports_dir: str | Path,
    verification_reports_dir: str | Path,
    promotion_reports_dir: str | Path,
    recovery_reports_dir: str | Path,
    promoted_archive_dir: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    main = Path(main_workbook)
    latest_output = latest_output_workbook(outputs_dir)
    result = {
        "status_timestamp": timestamp_iso(checked_at),
        "main_workbook_path": str(main),
        "main_workbook_exists": main.exists(),
        "main_workbook_modified_timestamp": _modified_timestamp(main),
        "latest_output_workbook": str(latest_output) if latest_output else "",
        "latest_export_report": str(_latest_file(export_reports_dir, "workbook_export_*.json") or ""),
        "latest_verification_report": str(_latest_file(verification_reports_dir, "export_verification_*.json") or ""),
        "latest_promotion_report": str(_latest_file(promotion_reports_dir, "workbook_promotion_*.json") or ""),
        "latest_recovery_report": str(_latest_file(recovery_reports_dir, "workbook_rollback_*.json") or ""),
        "latest_promoted_archive": str(_latest_file(promoted_archive_dir, "*.xlsx") or ""),
        "queue_summary": _queue_summary_or_empty(queue_dir, config),
    }
    return result


def promotion_history(
    reports_dir: str | Path,
    change_log_path: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    change_rows = _change_rows(change_log_path, "promote_output_workbook")
    rows = []
    for report_path, data in _json_reports(reports_dir, "workbook_promotion_*.json"):
        rows.append(
            {
                "timestamp": data.get("promotion_timestamp", ""),
                "promoted_workbook": data.get("candidate_output_workbook_path", ""),
                "main_workbook_path": data.get("main_workbook_path", ""),
                "archive_path": data.get("archive_path", ""),
                "status": data.get("overall_status", ""),
                "report_path": str(report_path),
            }
        )
    for row in change_rows:
        if not any(existing["timestamp"] == row.get("timestamp") and existing["promoted_workbook"] == row.get("input_file") for existing in rows):
            rows.append(
                {
                    "timestamp": row.get("timestamp", ""),
                    "promoted_workbook": row.get("input_file", ""),
                    "main_workbook_path": row.get("output_file", ""),
                    "archive_path": "",
                    "status": row.get("status", ""),
                    "report_path": "",
                }
            )
    return _history_result("promotion", _sort_and_limit(rows, limit))


def export_history(
    reports_dir: str | Path,
    change_log_path: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    del change_log_path
    rows = []
    for report_path, data in _json_reports(reports_dir, "workbook_export_*.json"):
        rows.append(
            {
                "timestamp": data.get("export_timestamp", ""),
                "source_workbook": data.get("workbook_path", ""),
                "backup_workbook": data.get("backup_workbook_path", ""),
                "output_workbook": data.get("output_workbook_path", ""),
                "rows_exported": data.get("rows_exported", 0),
                "status": data.get("overall_status", ""),
                "report_path": str(report_path),
            }
        )
    return _history_result("export", _sort_and_limit(rows, limit))


def verification_history(
    reports_dir: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    rows = []
    for report_path, data in _json_reports(reports_dir, "export_verification_*.json"):
        rows.append(
            {
                "timestamp": data.get("verification_timestamp", ""),
                "verified_workbook": data.get("output_workbook_path", ""),
                "verification_status": data.get("overall_status", ""),
                "rows_considered": data.get("approved_rows_considered", 0),
                "matching_rows": data.get("matching_exported_rows_found", 0),
                "missing_rows": data.get("missing_exported_rows", 0),
                "mismatches": data.get("value_mismatches", 0),
                "formula_concerns": data.get("formula_concerns", 0),
                "mark_exported_used": data.get("mark_exported_requested", False),
                "report_path": str(report_path),
            }
        )
    return _history_result("verification", _sort_and_limit(rows, limit))


def list_promoted_archives(archive_dir: str | Path, *, limit: int | None = None) -> dict[str, Any]:
    rows = []
    for path in Path(archive_dir).glob("*.xlsx"):
        if path.is_file():
            rows.append(
                {
                    "archive_filename": path.name,
                    "path": str(path),
                    "modified_timestamp": _modified_timestamp(path),
                    "size": path.stat().st_size,
                }
            )
    rows.sort(key=lambda row: row["modified_timestamp"], reverse=True)
    if limit is not None:
        rows = rows[:limit]
    return {"history_type": "promoted_archives", "rows": rows, "count": len(rows)}


def render_current_status_markdown(status: dict[str, Any]) -> str:
    queue_counts = status.get("queue_summary", {}).get("counts", {})
    lines = [
        "# Current Workbook Status",
        "",
        f"- Main workbook path: `{status['main_workbook_path']}`",
        f"- Main workbook exists: `{status['main_workbook_exists']}`",
        f"- Main workbook modified timestamp: `{status['main_workbook_modified_timestamp']}`",
        f"- Latest output workbook: `{status['latest_output_workbook']}`",
        f"- Latest export report: `{status['latest_export_report']}`",
        f"- Latest verification report: `{status['latest_verification_report']}`",
        f"- Latest promotion report: `{status['latest_promotion_report']}`",
        f"- Latest recovery report: `{status['latest_recovery_report']}`",
        f"- Latest promoted archive: `{status['latest_promoted_archive']}`",
        "",
        "## Queue Summary",
    ]
    if queue_counts:
        lines.extend(f"- {name}: `{count}`" for name, count in queue_counts.items())
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def render_history_table(history: dict[str, Any]) -> str:
    rows = history["rows"]
    if not rows:
        return "No rows found."
    headers = list(rows[0].keys())
    lines = [" | ".join(headers), " | ".join("---" for _ in headers)]
    for row in rows:
        lines.append(" | ".join(str(row.get(header, "")) for header in headers))
    return "\n".join(lines)


def render_history_markdown(history: dict[str, Any]) -> str:
    title = history["history_type"].replace("_", " ").title()
    return f"# {title} History\n\n{render_history_table(history)}\n"


def write_current_status_report(status: dict[str, Any], reports_dir: str | Path, *, written_at: datetime | None = None) -> Path:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    path = reports_path / f"current_workbook_status_{timestamp_for_filename(written_at)}.md"
    if path.exists():
        raise FileExistsError("Current workbook status report already exists; refusing to overwrite.")
    path.write_text(render_current_status_markdown(status), encoding="utf-8")
    return path


def write_history_reports(history: dict[str, Any], reports_dir: str | Path, *, written_at: datetime | None = None) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    prefix = f"{history['history_type']}_history"
    markdown_path = reports_path / f"{prefix}_{stamp}.md"
    json_path = reports_path / f"{prefix}_{stamp}.json"
    if markdown_path.exists() or json_path.exists():
        raise FileExistsError("History report already exists; refusing to overwrite.")
    markdown_path.write_text(render_history_markdown(history), encoding="utf-8")
    json_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _json_reports(reports_dir: str | Path, pattern: str) -> list[tuple[Path, dict[str, Any]]]:
    reports = []
    for path in Path(reports_dir).glob(pattern):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            reports.append((path, data))
    return reports


def _history_result(history_type: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"history_type": history_type, "rows": rows, "count": len(rows)}


def _sort_and_limit(rows: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
    if limit is not None:
        return rows[:limit]
    return rows


def _latest_file(directory: str | Path, pattern: str) -> Path | None:
    files = [path for path in Path(directory).glob(pattern) if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _modified_timestamp(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()


def _queue_summary_or_empty(queue_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return queue_summary(queue_dir, config)
    except (FileNotFoundError, KeyError):
        return {}


def _change_rows(path: str | Path, operation: str) -> list[dict[str, str]]:
    change_log = Path(path)
    if not change_log.exists():
        return []
    with change_log.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("operation") == operation]
