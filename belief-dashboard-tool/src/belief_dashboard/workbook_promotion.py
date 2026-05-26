from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso
from belief_dashboard.workbook import inspect_workbook


CHANGE_LOG_HEADERS = QUEUE_SCHEMAS["change_log"]


def promote_output_workbook(
    workbook_path: str | Path,
    verification_report_path: str | Path,
    main_workbook_path: str | Path,
    config: dict[str, Any],
    *,
    archive_dir: str | Path,
    reports_dir: str | Path,
    queue_dir: str | Path,
    dry_run: bool = False,
    promoted_at: datetime | None = None,
) -> dict[str, Any]:
    promoted_timestamp = timestamp_iso(promoted_at)
    stamp = timestamp_for_filename(promoted_at)
    candidate = Path(workbook_path)
    verification_report = Path(verification_report_path)
    main_workbook = Path(main_workbook_path)
    archive_path = Path(archive_dir) / _archive_name(main_workbook, stamp)
    markdown_path = Path(reports_dir) / f"workbook_promotion_{stamp}.md"
    json_path = Path(reports_dir) / f"workbook_promotion_{stamp}.json"
    result: dict[str, Any] = {
        "candidate_output_workbook_path": str(candidate),
        "main_workbook_path": str(main_workbook),
        "verification_report_path": str(verification_report),
        "verification_status": "",
        "promotion_timestamp": promoted_timestamp,
        "dry_run": dry_run,
        "candidate_workbook_exists": candidate.exists(),
        "main_workbook_exists": main_workbook.exists(),
        "verification_report_exists": verification_report.exists(),
        "verification_report_matched_candidate": False,
        "candidate_unchanged_since_verification": False,
        "candidate_hash_sha256": "",
        "basic_workbook_inspection_passed": False,
        "basic_workbook_inspection_status": "",
        "archive_path": "" if dry_run else str(archive_path),
        "main_workbook_replaced": False,
        "markdown_report_path": "" if dry_run else str(markdown_path),
        "json_report_path": "" if dry_run else str(json_path),
        "change_log_updated": False,
        "warnings": [],
        "errors": [],
        "overall_status": "fail",
        "next_step_notes": [],
    }

    _validate_inputs(result, candidate, main_workbook, verification_report, config)
    if result["candidate_workbook_exists"]:
        result["candidate_hash_sha256"] = _sha256(candidate)

    report_data = _load_verification_report(verification_report, result)
    if report_data is not None:
        _validate_verification_report(result, report_data, candidate, verification_report, config)

    if result["candidate_workbook_exists"]:
        inspection = inspect_workbook(candidate, config)
        result["basic_workbook_inspection_status"] = inspection["overall_status"]
        result["basic_workbook_inspection_passed"] = inspection["overall_status"] == "pass"
        if not result["basic_workbook_inspection_passed"]:
            result["errors"].append("Candidate workbook failed basic workbook inspection.")

    if not dry_run:
        _validate_output_paths(result, archive_path, markdown_path, json_path)

    if result["errors"]:
        return _finalize(result, promoted=False)
    if dry_run:
        return _finalize(result, promoted=False)

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main_workbook, archive_path)
    shutil.copy2(candidate, main_workbook)
    result["main_workbook_replaced"] = True
    _append_change_log(
        Path(queue_dir) / config["queues"]["files"]["change_log"],
        input_file=str(candidate),
        output_file=str(main_workbook),
        status="pass",
        details=f"Promoted verified output workbook after archiving previous main workbook to {archive_path}.",
        changed_at=promoted_at,
    )
    result["change_log_updated"] = True
    return _finalize(result, promoted=True)


def write_workbook_promotion_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"workbook_promotion_{stamp}.md"
    json_path = reports_path / f"workbook_promotion_{stamp}.json"
    if markdown_path.exists() or json_path.exists():
        raise FileExistsError("Promotion report already exists; refusing to overwrite.")
    markdown_path.write_text(render_workbook_promotion_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_workbook_promotion_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Workbook Promotion Report",
        "",
        f"- Candidate output workbook path: `{result['candidate_output_workbook_path']}`",
        f"- Main workbook path: `{result['main_workbook_path']}`",
        f"- Verification report path: `{result['verification_report_path']}`",
        f"- Verification status: `{result['verification_status']}`",
        f"- Promotion timestamp: `{result['promotion_timestamp']}`",
        f"- Dry-run status: `{result['dry_run']}`",
        f"- Candidate workbook exists: `{result['candidate_workbook_exists']}`",
        f"- Main workbook exists: `{result['main_workbook_exists']}`",
        f"- Verification report exists: `{result['verification_report_exists']}`",
        f"- Verification report matched candidate: `{result['verification_report_matched_candidate']}`",
        f"- Candidate unchanged since verification: `{result['candidate_unchanged_since_verification']}`",
        f"- Basic workbook inspection passed: `{result['basic_workbook_inspection_passed']}`",
        f"- Basic workbook inspection status: `{result['basic_workbook_inspection_status']}`",
        f"- Archive path: `{result['archive_path']}`",
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


def _validate_inputs(
    result: dict[str, Any],
    candidate: Path,
    main_workbook: Path,
    verification_report: Path,
    config: dict[str, Any],
) -> None:
    if not candidate.exists():
        result["errors"].append(f"Candidate output workbook not found: {candidate}")
    if not main_workbook.exists():
        result["errors"].append(f"Main workbook not found: {main_workbook}")
    if not verification_report.exists():
        result["errors"].append(f"Verification report not found: {verification_report}")
    if not config.get("workbook_promotion", {}).get("require_verification", True):
        result["warnings"].append("Config does not require verification, but this command still requires a report.")


def _load_verification_report(path: Path, result: dict[str, Any]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"Verification report is not valid JSON: {exc}")
        return None
    if not isinstance(data, dict):
        result["errors"].append("Verification report JSON must contain an object.")
        return None
    return data


def _validate_verification_report(
    result: dict[str, Any],
    report_data: dict[str, Any],
    candidate: Path,
    verification_report: Path,
    config: dict[str, Any],
) -> None:
    status = str(report_data.get("overall_status", ""))
    result["verification_status"] = status
    accepted = set(config.get("workbook_promotion", {}).get("accepted_verification_statuses", ["pass"]))
    if status not in accepted:
        result["errors"].append(f"Verification status '{status}' is not accepted for promotion.")

    report_workbook = str(report_data.get("output_workbook_path", "")).strip()
    if not report_workbook:
        result["errors"].append("Verification report does not include output_workbook_path.")
    elif _same_path(candidate, Path(report_workbook)):
        result["verification_report_matched_candidate"] = True
    elif _same_path(candidate, verification_report.parent / report_workbook):
        result["verification_report_matched_candidate"] = True
    else:
        result["errors"].append("Verification report does not refer to the candidate output workbook.")

    verification_timestamp = str(report_data.get("verification_timestamp", "")).strip()
    if candidate.exists() and verification_timestamp:
        verified_at = _parse_timestamp(verification_timestamp)
        if verified_at is not None:
            candidate_mtime = datetime.fromtimestamp(candidate.stat().st_mtime)
            if candidate_mtime.replace(microsecond=0) <= verified_at.replace(microsecond=0):
                result["candidate_unchanged_since_verification"] = True
            else:
                result["errors"].append("Candidate workbook appears to have changed after verification.")
        else:
            result["warnings"].append("Could not parse verification timestamp for workbook stability check.")
    elif candidate.exists():
        result["warnings"].append("Verification report has no timestamp for workbook stability check.")


def _validate_output_paths(result: dict[str, Any], archive_path: Path, markdown_path: Path, json_path: Path) -> None:
    if archive_path.exists():
        result["errors"].append(f"Archive path already exists; refusing to overwrite: {archive_path}")
    if markdown_path.exists() or json_path.exists():
        result["errors"].append("Promotion report path already exists; refusing to overwrite.")


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
            "operation": "promote_output_workbook",
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


def _archive_name(workbook: Path, stamp: str) -> str:
    return f"{workbook.stem}_pre_promotion_{stamp}{workbook.suffix}"


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _finalize(result: dict[str, Any], *, promoted: bool) -> dict[str, Any]:
    if result["errors"]:
        result["overall_status"] = "fail"
        result["next_step_notes"] = ["Fix promotion errors before replacing the main workbook."]
    elif result["warnings"]:
        result["overall_status"] = "warning"
        result["next_step_notes"] = ["Promotion checks passed with warnings. Review the report before relying on the main workbook."]
    else:
        result["overall_status"] = "pass"
        if promoted:
            result["next_step_notes"] = ["Promotion completed successfully. The previous main workbook is archived and the output workbook was preserved."]
        else:
            result["next_step_notes"] = ["Dry run completed successfully. No files were written."]
    return result


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
