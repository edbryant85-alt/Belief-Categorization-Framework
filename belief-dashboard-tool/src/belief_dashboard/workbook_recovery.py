from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso
from belief_dashboard.workbook import inspect_workbook


CHANGE_LOG_HEADERS = QUEUE_SCHEMAS["change_log"]


def rollback_workbook(
    archive_path: str | Path,
    main_workbook_path: str | Path,
    config: dict[str, Any],
    *,
    rollback_archive_dir: str | Path,
    reports_dir: str | Path,
    queue_dir: str | Path,
    dry_run: bool = False,
    rolled_back_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = timestamp_iso(rolled_back_at)
    stamp = timestamp_for_filename(rolled_back_at)
    archive = Path(archive_path)
    main = Path(main_workbook_path)
    rollback_archive = Path(rollback_archive_dir) / f"{main.stem}_pre_rollback_{stamp}{main.suffix}"
    markdown_path = Path(reports_dir) / f"workbook_rollback_{stamp}.md"
    json_path = Path(reports_dir) / f"workbook_rollback_{stamp}.json"
    result: dict[str, Any] = {
        "selected_archive_path": str(archive),
        "main_workbook_path": str(main),
        "rollback_timestamp": timestamp,
        "dry_run": dry_run,
        "selected_archive_exists": archive.exists(),
        "main_workbook_exists": main.exists(),
        "archive_inspection_passed": False,
        "archive_inspection_status": "",
        "rollback_archive_path": "" if dry_run else str(rollback_archive),
        "main_workbook_replaced": False,
        "markdown_report_path": "" if dry_run else str(markdown_path),
        "json_report_path": "" if dry_run else str(json_path),
        "change_log_updated": False,
        "warnings": [],
        "errors": [],
        "overall_status": "fail",
        "next_step_notes": [],
    }

    if not archive.exists():
        result["errors"].append(f"Selected archive not found: {archive}")
    if not main.exists():
        result["errors"].append(f"Main workbook not found: {main}")
    if archive.exists():
        inspection = inspect_workbook(archive, config)
        result["archive_inspection_status"] = inspection["overall_status"]
        result["archive_inspection_passed"] = inspection["overall_status"] == "pass"
        if not result["archive_inspection_passed"]:
            result["errors"].append("Selected archive failed basic workbook inspection.")
    if not dry_run:
        if rollback_archive.exists():
            result["errors"].append(f"Rollback archive path already exists; refusing to overwrite: {rollback_archive}")
        if markdown_path.exists() or json_path.exists():
            result["errors"].append("Rollback report path already exists; refusing to overwrite.")
    if result["errors"]:
        return _finalize(result, rolled_back=False)
    if dry_run:
        return _finalize(result, rolled_back=False)

    rollback_archive.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main, rollback_archive)
    shutil.copy2(archive, main)
    result["main_workbook_replaced"] = True
    _append_change_log(
        Path(queue_dir) / config["queues"]["files"]["change_log"],
        input_file=str(archive),
        output_file=str(main),
        status="pass",
        details=f"Rolled back main workbook from archive after preserving pre-rollback workbook at {rollback_archive}.",
        changed_at=rolled_back_at,
    )
    result["change_log_updated"] = True
    return _finalize(result, rolled_back=True)


def write_workbook_rollback_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"workbook_rollback_{stamp}.md"
    json_path = reports_path / f"workbook_rollback_{stamp}.json"
    if markdown_path.exists() or json_path.exists():
        raise FileExistsError("Rollback report already exists; refusing to overwrite.")
    markdown_path.write_text(render_workbook_rollback_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_workbook_rollback_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Workbook Rollback Report",
        "",
        f"- Selected archive path: `{result['selected_archive_path']}`",
        f"- Main workbook path: `{result['main_workbook_path']}`",
        f"- Rollback timestamp: `{result['rollback_timestamp']}`",
        f"- Dry-run status: `{result['dry_run']}`",
        f"- Selected archive exists: `{result['selected_archive_exists']}`",
        f"- Main workbook exists: `{result['main_workbook_exists']}`",
        f"- Archive inspection passed: `{result['archive_inspection_passed']}`",
        f"- Archive inspection status: `{result['archive_inspection_status']}`",
        f"- Rollback archive path: `{result['rollback_archive_path']}`",
        f"- Main workbook replaced: `{result['main_workbook_replaced']}`",
        f"- Change log updated: `{result['change_log_updated']}`",
        f"- Overall status: `{result['overall_status']}`",
        "",
        "## Warnings",
        *_bullet_list(result["warnings"]),
        "",
        "## Errors",
        *_bullet_list(result["errors"]),
        "",
        "## Next-Step Notes",
        *_bullet_list(result["next_step_notes"]),
        "",
    ]
    return "\n".join(lines)


def _append_change_log(
    path: Path,
    *,
    input_file: str,
    output_file: str,
    status: str,
    details: str,
    changed_at: datetime | None,
) -> None:
    rows = _read_rows(path)
    rows.append(
        {
            "change_id": f"CHG{len(rows) + 1:04d}",
            "timestamp": (changed_at or datetime.now()).replace(microsecond=0).isoformat(),
            "operation": "rollback_workbook",
            "input_file": input_file,
            "output_file": output_file,
            "status": status,
            "details": details,
        }
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHANGE_LOG_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in CHANGE_LOG_HEADERS})


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _finalize(result: dict[str, Any], *, rolled_back: bool) -> dict[str, Any]:
    if result["errors"]:
        result["overall_status"] = "fail"
        result["next_step_notes"] = ["Fix rollback errors before replacing the main workbook."]
    elif result["warnings"]:
        result["overall_status"] = "warning"
        result["next_step_notes"] = ["Rollback checks passed with warnings. Review the report before relying on the main workbook."]
    else:
        result["overall_status"] = "pass"
        if rolled_back:
            result["next_step_notes"] = ["Rollback completed successfully. The pre-rollback main workbook is archived and the selected archive was preserved."]
        else:
            result["next_step_notes"] = ["Dry run completed successfully. No files were written."]
    return result


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
