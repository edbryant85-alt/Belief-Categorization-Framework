from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import MI5_COLUMNS, QUEUE_SCHEMAS
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


REVIEW_TARGETS = {
    "approved": "approved_updates",
    "rejected": "rejected_updates",
    "deferred": "deferred_updates",
}


class ReviewError(ValueError):
    pass


def review_proposal(
    proposal_id: str,
    action: str,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    reviewer: str,
    reason: str = "",
    notes: str = "",
    revisit_date: str = "",
    weight: str | None = None,
    category: str | None = None,
    mi5_overrides: dict[str, str] | None = None,
    reviewed_on: date | None = None,
    reviewed_at: datetime | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    today = (reviewed_on or date.today()).isoformat()
    timestamp = timestamp_iso(reviewed_at)
    result = _base_result(proposal_id, action, reviewer, timestamp)

    if action not in REVIEW_TARGETS:
        result["errors"].append(f"Unsupported review action: {action}")
        return _finalize(result)
    if not reviewer.strip():
        result["errors"].append("Reviewer is required.")
        return _finalize(result)
    if action in {"rejected", "deferred"} and not reason.strip():
        result["errors"].append("Reason is required for rejection and deferral.")
        return _finalize(result)

    paths = _queue_paths(queue_path, config)
    proposed_rows = _read_rows(paths["proposed_updates"])
    proposal_index, proposal = _find_proposal(proposed_rows, proposal_id)
    if proposal is None:
        result["errors"].append(f"Proposal ID not found in proposed_updates.csv: {proposal_id}")
        return _finalize(result)

    result["source_id"] = proposal.get("source_id", "")
    result["claim_id"] = proposal.get("claim_id", "")
    result["target_queue"] = str(paths[REVIEW_TARGETS[action]])

    existing_review_queue = _existing_review_queue(proposal_id, paths)
    if existing_review_queue:
        result["errors"].append(
            f"Proposal {proposal_id} already exists in {existing_review_queue}. It cannot be reviewed again."
        )
    current_status = (proposal.get("review_status") or "").strip()
    if current_status in {"approved", "rejected", "deferred"}:
        result["errors"].append(
            f"Proposal {proposal_id} is already marked as {current_status} in proposed_updates.csv."
        )

    _validate_approval_overrides(action, weight, mi5_overrides or {}, result, config)
    if result["errors"]:
        return _finalize(result)

    target_row = _build_target_row(
        proposal,
        action,
        reviewer=reviewer,
        reason=reason,
        notes=notes,
        revisit_date=revisit_date,
        weight=weight,
        category=category,
        mi5_overrides=mi5_overrides or {},
        today=today,
    )
    target_name = REVIEW_TARGETS[action]
    target_rows = _read_rows(paths[target_name])
    target_rows.append(target_row)
    proposed_rows[proposal_index]["review_status"] = action

    _replace_csv(paths[target_name], QUEUE_SCHEMAS[target_name], target_rows)
    _replace_csv(paths["proposed_updates"], QUEUE_SCHEMAS["proposed_updates"], proposed_rows)
    _append_change_log(
        paths["change_log"],
        operation=f"review_proposal:{action}",
        input_file=str(paths["proposed_updates"]),
        output_file=str(paths[target_name]),
        status="success",
        details=f"Reviewed proposal {proposal_id} as {action} by {reviewer}.",
        changed_at=reviewed_at,
    )

    result["proposed_status_updated"] = True
    result["target_queue_row_appended"] = True
    result["overall_status"] = "pass"
    result["next_step_notes"] = ["Review action completed. No Excel workbook changes were made."]
    return result


def list_proposals(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    status: str | None = None,
    source_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    proposed_path = Path(queue_dir) / config["queues"]["files"]["proposed_updates"]
    rows = _read_rows(proposed_path)
    filtered = []
    for row in rows:
        if status is not None and (row.get("review_status") or "") != status:
            continue
        if source_id is not None and (row.get("source_id") or "") != source_id:
            continue
        filtered.append(row)
    if limit is not None:
        return filtered[:limit]
    return filtered


def render_proposals_table(rows: list[dict[str, str]]) -> str:
    headers = ["proposal_id", "source_id", "claim_id", "category", "suggested_weight_0_5", "review_status", "evidence_preview"]
    output = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows:
        values = [
            row.get("proposal_id", ""),
            row.get("source_id", ""),
            row.get("claim_id", ""),
            row.get("category", ""),
            row.get("suggested_weight_0_5", ""),
            row.get("review_status", ""),
            _preview(row.get("evidence_argument", "")),
        ]
        output.append(" | ".join(values))
    return "\n".join(output)


def write_review_report(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    proposal_id = result["proposal_id"]
    action = result["action"]
    markdown_path = reports_path / f"proposal_review_{proposal_id}_{action}_{stamp}.md"
    json_path = reports_path / f"proposal_review_{proposal_id}_{action}_{stamp}.json"
    markdown_path.write_text(render_review_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_review_report(result: dict[str, Any]) -> str:
    lines = [
        "# Proposal Review Report",
        "",
        f"- Proposal ID: `{result['proposal_id']}`",
        f"- Action taken: `{result['action']}`",
        f"- Reviewer: `{result['reviewer']}`",
        f"- Timestamp: `{result['timestamp']}`",
        f"- Source ID: `{result['source_id']}`",
        f"- Claim ID: `{result['claim_id']}`",
        f"- Target queue: `{result['target_queue']}`",
        f"- Proposed row status updated: `{result['proposed_status_updated']}`",
        f"- Target queue row appended: `{result['target_queue_row_appended']}`",
        f"- Overall status: `{result['overall_status']}`",
        "",
        "## Errors",
        *_bullet_list(result["errors"]),
        "",
        "## Warnings",
        *_bullet_list(result["warnings"]),
        "",
        "## Next-Step Notes",
        *_bullet_list(result["next_step_notes"]),
        "",
    ]
    return "\n".join(lines)


def _build_target_row(
    proposal: dict[str, str],
    action: str,
    *,
    reviewer: str,
    reason: str,
    notes: str,
    revisit_date: str,
    weight: str | None,
    category: str | None,
    mi5_overrides: dict[str, str],
    today: str,
) -> dict[str, str]:
    if action == "approved":
        row = {header: "" for header in QUEUE_SCHEMAS["approved_updates"]}
        for field in ["proposal_id", "claim_id", "source_id", "evidence_argument", "source_book"]:
            row[field] = proposal.get(field, "")
        row["category"] = category if category is not None else proposal.get("category", "")
        row["approved_weight_0_5"] = weight if weight is not None else proposal.get("suggested_weight_0_5", "")
        for field in MI5_COLUMNS:
            row[field] = mi5_overrides.get(field, proposal.get(field, ""))
        row["notes"] = _append_review_note(proposal.get("notes", ""), notes)
        row["approved_by"] = reviewer
        row["approved_date"] = today
        return row
    if action == "rejected":
        return {
            "proposal_id": proposal.get("proposal_id", ""),
            "claim_id": proposal.get("claim_id", ""),
            "source_id": proposal.get("source_id", ""),
            "evidence_argument": proposal.get("evidence_argument", ""),
            "rejection_reason": reason,
            "rejected_by": reviewer,
            "rejected_date": today,
            "notes": notes,
        }
    return {
        "proposal_id": proposal.get("proposal_id", ""),
        "claim_id": proposal.get("claim_id", ""),
        "source_id": proposal.get("source_id", ""),
        "evidence_argument": proposal.get("evidence_argument", ""),
        "deferral_reason": reason,
        "revisit_date": revisit_date,
        "deferred_by": reviewer,
        "deferred_date": today,
        "notes": notes,
    }


def _validate_approval_overrides(
    action: str,
    weight: str | None,
    mi5_overrides: dict[str, str],
    result: dict[str, Any],
    config: dict[str, Any],
) -> None:
    if action != "approved":
        return
    if weight is not None:
        try:
            value = float(weight)
        except ValueError:
            result["errors"].append("Approval weight must be numeric from 0 to 5.")
        else:
            if value < 0 or value > 5:
                result["errors"].append("Approval weight must be between 0 and 5.")
    allowed_mi5 = set(config["allowed_values"]["mi5_labels"])
    for field, value in mi5_overrides.items():
        if value and value not in allowed_mi5:
            result["errors"].append(f"{field} has invalid MI5 value '{value}'.")


def _existing_review_queue(proposal_id: str, paths: dict[str, Path]) -> str:
    for queue_name in ["approved_updates", "rejected_updates", "deferred_updates"]:
        for row in _read_rows(paths[queue_name]):
            if row.get("proposal_id") == proposal_id:
                return f"{queue_name}.csv"
    return ""


def _find_proposal(rows: list[dict[str, str]], proposal_id: str) -> tuple[int, dict[str, str] | None]:
    for index, row in enumerate(rows):
        if row.get("proposal_id") == proposal_id:
            return index, row
    return -1, None


def _append_change_log(
    path: Path,
    *,
    operation: str,
    input_file: str,
    output_file: str,
    status: str,
    details: str,
    changed_at: datetime | None,
) -> None:
    rows = _read_rows(path)
    row = {
        "change_id": f"CHG{len(rows) + 1:04d}",
        "timestamp": (changed_at or datetime.now()).replace(microsecond=0).isoformat(),
        "operation": operation,
        "input_file": input_file,
        "output_file": output_file,
        "status": status,
        "details": details,
    }
    rows.append(row)
    _replace_csv(path, QUEUE_SCHEMAS["change_log"], rows)


def _queue_paths(queue_dir: Path, config: dict[str, Any]) -> dict[str, Path]:
    return {
        name: queue_dir / filename
        for name, filename in config["queues"]["files"].items()
        if name in QUEUE_SCHEMAS
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _replace_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    os.replace(temp_path, path)


def _base_result(proposal_id: str, action: str, reviewer: str, timestamp: str) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "action": action,
        "reviewer": reviewer,
        "timestamp": timestamp,
        "source_id": "",
        "claim_id": "",
        "target_queue": "",
        "proposed_status_updated": False,
        "target_queue_row_appended": False,
        "warnings": [],
        "errors": [],
        "overall_status": "fail",
        "next_step_notes": [],
    }


def _finalize(result: dict[str, Any]) -> dict[str, Any]:
    result["overall_status"] = "fail" if result["errors"] else "pass"
    if result["errors"]:
        result["next_step_notes"] = ["Review action failed. No queue rows were changed."]
    return result


def _append_review_note(existing: str, note: str) -> str:
    if not note:
        return existing
    review_note = f"Review note: {note}"
    if existing:
        return f"{existing}\n{review_note}"
    return review_note


def _preview(value: str, limit: int = 72) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
