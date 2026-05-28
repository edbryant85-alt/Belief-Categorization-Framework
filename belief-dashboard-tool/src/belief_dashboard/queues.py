from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import (
    CRITERIA_SCORE_FIELDS,
    MI5_COLUMNS,
    QUEUE_SCHEMAS,
    REFLECTION_JOURNAL_TEMPLATE,
    WEIGHT_FIELDS,
)
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


def init_queues(base_dir: str | Path, config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    queue_dir = Path(base_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    files_config = config["queues"]["files"]
    result: dict[str, Any] = {
        "base_dir": str(queue_dir),
        "force": force,
        "created": [],
        "skipped": [],
        "overwritten": [],
    }

    for queue_name, headers in QUEUE_SCHEMAS.items():
        path = queue_dir / files_config[queue_name]
        action = _write_csv_template(path, headers, force=force)
        if queue_name == "approved_updates" and action == "skipped":
            if migrate_approved_updates_schema(path):
                action = "overwritten"
        result[action].append(str(path))

    journal_path = queue_dir / files_config["reflection_journal"]
    action = _write_text_template(journal_path, REFLECTION_JOURNAL_TEMPLATE, force=force)
    result[action].append(str(journal_path))
    return result


def validate_queues(
    base_dir: str | Path,
    config: dict[str, Any],
    *,
    validated_at: datetime | None = None,
) -> dict[str, Any]:
    queue_dir = Path(base_dir)
    files_config = config["queues"]["files"]
    result: dict[str, Any] = {
        "queue_base_dir": str(queue_dir),
        "validation_timestamp": timestamp_iso(validated_at),
        "required_files": {},
        "errors": [],
        "warnings": [],
        "overall_status": "pass",
        "next_step_notes": [],
    }

    for queue_name, headers in QUEUE_SCHEMAS.items():
        if queue_name not in files_config:
            result["warnings"].append(f"Queue file config is missing for optional queue: {queue_name}")
            continue
        path = queue_dir / files_config[queue_name]
        file_result = _validate_csv_file(queue_name, path, headers, config)
        result["required_files"][queue_name] = file_result
        result["errors"].extend(file_result["errors"])
        result["warnings"].extend(file_result["warnings"])

    _validate_cluster_cross_references(queue_dir, config, result)

    journal_path = queue_dir / files_config["reflection_journal"]
    journal_result = {
        "path": str(journal_path),
        "exists": journal_path.exists(),
        "errors": [],
        "warnings": [],
    }
    if not journal_path.exists():
        journal_result["errors"].append(f"Missing required file: {journal_path}")
    result["required_files"]["reflection_journal"] = journal_result
    result["errors"].extend(journal_result["errors"])

    result["overall_status"] = _status_for(result["errors"], result["warnings"])
    result["next_step_notes"] = _next_step_notes(result)
    return result


def write_queue_validation_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"queue_validation_{stamp}.md"
    json_path = reports_path / f"queue_validation_{stamp}.json"

    markdown_path.write_text(render_queue_validation_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_queue_validation_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Queue Validation Report",
        "",
        f"- Queue base directory: `{result['queue_base_dir']}`",
        f"- Validation timestamp: `{result['validation_timestamp']}`",
        f"- Overall status: `{result['overall_status']}`",
        "",
        "## Required Files",
    ]
    for queue_name, file_result in result["required_files"].items():
        lines.append(f"- `{queue_name}`: {_yes_no(file_result['exists'])} ({file_result['path']})")

    lines.extend(["", "## Errors", *_bullet_list(result["errors"])])
    lines.extend(["", "## Warnings", *_bullet_list(result["warnings"])])
    lines.extend(["", "## Next-Step Notes", *_bullet_list(result["next_step_notes"]), ""])
    return "\n".join(lines)


def _write_csv_template(path: Path, headers: list[str], *, force: bool) -> str:
    if path.exists() and not force:
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
    return "overwritten" if existed else "created"


def _write_text_template(path: Path, content: str, *, force: bool) -> str:
    if path.exists() and not force:
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    return "overwritten" if existed else "created"


def _validate_csv_file(
    queue_name: str,
    path: Path,
    expected_headers: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "expected_headers": expected_headers,
        "headers_found": [],
        "row_count": 0,
        "errors": [],
        "warnings": [],
    }

    if not path.exists():
        result["errors"].append(f"Missing required file: {path}")
        return result

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers_found = reader.fieldnames or []
        result["headers_found"] = headers_found
        if headers_found != expected_headers:
            result["errors"].append(
                f"{path.name} headers do not match expected schema or order."
            )
            return result
        for row_number, row in enumerate(reader, start=2):
            result["row_count"] += 1
            _validate_row(queue_name, row, row_number, result, config)

    return result


def _validate_row(
    queue_name: str,
    row: dict[str, str | None],
    row_number: int,
    result: dict[str, Any],
    config: dict[str, Any],
) -> None:
    if queue_name in {"proposed_updates", "approved_updates"}:
        _validate_mi5_labels(row, row_number, result, config)
    if queue_name in WEIGHT_FIELDS:
        for field in WEIGHT_FIELDS[queue_name]:
            _validate_zero_to_five(row.get(field), field, row_number, result)
    if queue_name == "proposed_updates":
        _validate_allowed_value(
            row.get("review_status"),
            "review_status",
            row_number,
            result,
            config["allowed_values"]["review_statuses"],
        )
    if queue_name == "extracted_claims":
        _validate_allowed_value(
            row.get("claim_type"),
            "claim_type",
            row_number,
            result,
            config["allowed_values"]["claim_types"],
        )
    if queue_name == "source_triage":
        _validate_allowed_value(
            row.get("triage_status"),
            "triage_status",
            row_number,
            result,
            config["allowed_values"]["triage_statuses"],
        )
        _validate_allowed_value(
            row.get("recommended_action"),
            "recommended_action",
            row_number,
            result,
            config["allowed_values"]["triage_actions"],
        )
        _validate_zero_to_five(row.get("priority_0_5"), "priority_0_5", row_number, result)
    if queue_name == "evidence_clusters":
        _validate_allowed_value(
            row.get("status"),
            "status",
            row_number,
            result,
            config["allowed_values"].get("cluster_statuses", []),
        )
    if queue_name == "source_cluster_members":
        _validate_allowed_value(
            row.get("source_role"),
            "source_role",
            row_number,
            result,
            config["allowed_values"].get("source_cluster_roles", []),
        )
        _validate_allowed_value(
            row.get("status"),
            "status",
            row_number,
            result,
            config["allowed_values"].get("source_cluster_member_statuses", []),
        )
        _validate_zero_to_five(row.get("relevance_0_5"), "relevance_0_5", row_number, result)
        _validate_zero_to_five(row.get("priority_0_5"), "priority_0_5", row_number, result)
    if queue_name == "criteria_matrix":
        for field in CRITERIA_SCORE_FIELDS:
            _validate_zero_to_five(row.get(field), field, row_number, result)
    if queue_name == "approved_updates":
        _validate_allowed_value(
            row.get("export_status"),
            "export_status",
            row_number,
            result,
            ["exported"],
        )


def migrate_approved_updates_schema(path: str | Path) -> bool:
    approved_path = Path(path)
    if not approved_path.exists():
        return False
    with approved_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = reader.fieldnames or []
    expected = QUEUE_SCHEMAS["approved_updates"]
    if headers == expected:
        return False
    legacy = expected[: -4]
    if headers != legacy:
        return False
    with approved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=expected)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in expected})
    return True


def _validate_mi5_labels(
    row: dict[str, str | None],
    row_number: int,
    result: dict[str, Any],
    config: dict[str, Any],
) -> None:
    allowed = config["allowed_values"]["mi5_labels"]
    for field in MI5_COLUMNS:
        _validate_allowed_value(row.get(field), field, row_number, result, allowed)


def _validate_allowed_value(
    value: str | None,
    field: str,
    row_number: int,
    result: dict[str, Any],
    allowed: list[str],
) -> None:
    if value is None or value.strip() == "":
        return
    if value.strip() not in allowed:
        result["errors"].append(
            f"Row {row_number}: {field} has invalid value '{value}'."
        )


def _validate_cluster_cross_references(queue_dir: Path, config: dict[str, Any], result: dict[str, Any]) -> None:
    files_config = config["queues"]["files"]
    required = {"source_dossiers", "evidence_clusters", "source_cluster_members"}
    if not required.issubset(files_config):
        return
    source_path = queue_dir / files_config["source_dossiers"]
    cluster_path = queue_dir / files_config["evidence_clusters"]
    member_path = queue_dir / files_config["source_cluster_members"]
    if not source_path.exists() or not cluster_path.exists() or not member_path.exists():
        return
    source_ids = _ids_from_csv(source_path, "source_id")
    cluster_ids = _ids_from_csv(cluster_path, "cluster_id")
    with member_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            cluster_id = (row.get("cluster_id") or "").strip()
            source_id = (row.get("source_id") or "").strip()
            if cluster_id and cluster_id not in cluster_ids:
                error = f"Row {row_number}: cluster_id not found in evidence_clusters.csv: {cluster_id}."
                result["errors"].append(error)
                result["required_files"]["source_cluster_members"]["errors"].append(error)
            if source_id and source_id not in source_ids:
                error = f"Row {row_number}: source_id not found in source_dossiers.csv: {source_id}."
                result["errors"].append(error)
                result["required_files"]["source_cluster_members"]["errors"].append(error)


def _ids_from_csv(path: Path, field: str) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            (row.get(field) or "").strip()
            for row in csv.DictReader(handle)
            if (row.get(field) or "").strip()
        }


def _validate_zero_to_five(
    value: str | None,
    field: str,
    row_number: int,
    result: dict[str, Any],
) -> None:
    if value is None or value.strip() == "":
        return
    try:
        number = float(value)
    except ValueError:
        result["errors"].append(
            f"Row {row_number}: {field} must be blank or numeric from 0 to 5."
        )
        return
    if number < 0 or number > 5:
        result["errors"].append(
            f"Row {row_number}: {field} must be between 0 and 5."
        )


def _status_for(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "fail"
    if warnings:
        return "warning"
    return "pass"


def _next_step_notes(result: dict[str, Any]) -> list[str]:
    if result["errors"]:
        return ["Fix queue validation errors before later phases depend on these files."]
    if result["warnings"]:
        return ["Review queue validation warnings before using these files in later phases."]
    return ["Queue files match Phase 2 expectations. No workbook changes were made."]


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
