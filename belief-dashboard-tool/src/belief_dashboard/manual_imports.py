from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import append_import_log
from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS, MI5_COLUMNS, QUEUE_SCHEMAS
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


ID_FIELDS = {
    "source_triage": "source_id",
    "extracted_claims": "claim_id",
    "criteria_matrix": "claim_id",
    "proposed_updates": "proposal_id",
}

REQUIRED_FIELDS = {
    "source_triage": ["source_id", "triage_status", "priority_0_5", "recommended_action"],
    "extracted_claims": ["claim_id", "source_id", "claim_text"],
    "criteria_matrix": ["claim_id", "source_id"],
    "proposed_updates": [
        "proposal_id",
        "claim_id",
        "source_id",
        "evidence_argument",
        "category",
        "source_book",
    ],
}

CLAIM_TYPE_ALIASES = {
    "metaphysical claim": "metaphysical_claim",
    "metaphysical": "metaphysical_claim",
    "moral claim": "moral_claim",
    "moral": "moral_claim",
    "social claim": "moral_claim",
    "social": "moral_claim",
    "moral social claim": "moral_claim",
    "moral anthropology claim": "moral_claim",
    "practical claim": "moral_claim",
    "practical": "moral_claim",
    "interpretive claim": "interpretive_claim",
    "interpretive": "interpretive_claim",
    "metaethical claim": "interpretive_claim",
    "metaethical": "interpretive_claim",
    "historical claim": "historical_claim",
    "historical": "historical_claim",
    "textual claim": "historical_claim",
    "textual": "historical_claim",
    "explanatory claim": "historical_claim",
    "explanatory": "historical_claim",
    "scientific claim": "scientific_claim",
    "scientific": "scientific_claim",
    "technological claim": "scientific_claim",
    "technological": "scientific_claim",
    "probabilistic claim": "argument",
    "probabilistic": "argument",
    "epistemic claim": "interpretive_claim",
    "epistemic": "interpretive_claim",
    "limit claim": "interpretive_claim",
    "limit": "interpretive_claim",
    "sociological claim": "historical_claim",
    "sociological": "historical_claim",
    "trilemma": "argument",
    "conclusion": "argument",
    "theological claim": "theological_claim",
    "theological": "theological_claim",
    "theological anthropology claim": "theological_claim",
    "theological analogy": "theological_claim",
    "theological analogy claim": "theological_claim",
    "existential claim": "existential_claim",
    "existential": "existential_claim",
    "definition claim": "definition",
    "objection claim": "objection",
    "defeater claim": "defeater",
    "counter-defeater": "counter_defeater",
    "counter defeater": "counter_defeater",
    "counter-defeater claim": "counter_defeater",
    "counter defeater claim": "counter_defeater",
}

REVIEW_STATUS_ALIASES = {
    "needs_review": "proposed",
    "needs review": "proposed",
    "pending_manual_review": "proposed",
    "pending manual review": "proposed",
    "pending_review": "proposed",
    "pending review": "proposed",
    "manual_review": "proposed",
    "manual review": "proposed",
    "pending": "proposed",
    "review_needed": "proposed",
    "review needed": "proposed",
}


def validate_manual_import(
    import_type: str,
    import_file: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    validated_at: datetime | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    file_path = Path(import_file)
    target_queue = queue_path / config["queues"]["files"].get(import_type, "")
    result: dict[str, Any] = {
        "import_type": import_type,
        "import_file_path": str(file_path),
        "validation_timestamp": timestamp_iso(validated_at),
        "target_queue_file": str(target_queue),
        "row_count": 0,
        "header_status": "not_checked",
        "duplicate_id_status": "not_checked",
        "source_id_reference_status": "not_checked",
        "claim_id_reference_status": "not_applicable",
        "mi5_validation_status": "not_applicable",
        "score_weight_validation_status": "not_applicable",
        "overall_status": "fail",
        "errors": [],
        "warnings": [],
        "next_step_notes": [],
    }

    if import_type not in config["manual_imports"]["supported_import_types"]:
        result["errors"].append(f"Unsupported import type: {import_type}")
        return _finalize_result(result)
    if not file_path.exists():
        result["errors"].append(f"Import file not found: {file_path}")
        return _finalize_result(result)
    if not target_queue.exists():
        result["errors"].append(
            f"Target queue file not found: {target_queue}. Run: python -m belief_dashboard.cli init-queues"
        )
        return _finalize_result(result)

    rows, headers = _read_csv(file_path)
    result["row_count"] = len(rows)
    expected_headers = QUEUE_SCHEMAS[import_type]
    if headers != expected_headers:
        result["header_status"] = "fail"
        result["errors"].append(f"Headers do not match expected {import_type} schema or order.")
        return _finalize_result(result)
    result["header_status"] = "pass"

    source_ids = _existing_ids(queue_path / config["queues"]["files"]["source_dossiers"], "source_id")
    existing_claim_ids = _existing_ids(queue_path / config["queues"]["files"]["extracted_claims"], "claim_id")
    existing_target_ids = _existing_ids(target_queue, ID_FIELDS[import_type])
    batch_claim_ids = _batch_claim_ids(import_type, file_path, rows, config)

    _validate_required_fields(import_type, rows, result)
    _validate_duplicate_ids(import_type, rows, existing_target_ids, result)
    _validate_source_references(rows, source_ids, result)
    _validate_type_specific_fields(import_type, rows, existing_claim_ids | batch_claim_ids, result, config)
    return _finalize_result(result)


def write_manual_import_report(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    import_type = result["import_type"]
    markdown_path = reports_path / f"{import_type}_import_validation_{stamp}.md"
    json_path = reports_path / f"{import_type}_import_validation_{stamp}.json"
    markdown_path.write_text(render_manual_import_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def clean_manual_import(
    import_type: str,
    import_file: str | Path,
    output_file: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    cleaned_at: datetime | None = None,
) -> dict[str, Any]:
    source_path = Path(import_file)
    output_path = Path(output_file)
    result: dict[str, Any] = {
        "import_type": import_type,
        "import_file_path": str(source_path),
        "output_file_path": str(output_path),
        "cleaned_timestamp": timestamp_iso(cleaned_at),
        "row_count": 0,
        "changes": [],
        "warnings": [],
        "errors": [],
        "overall_status": "fail",
        "next_step_notes": [],
    }
    if import_type not in config["manual_imports"]["supported_import_types"]:
        result["errors"].append(f"Unsupported import type: {import_type}")
        return _finalize_clean_result(result)
    if not source_path.exists():
        result["errors"].append(f"Import file not found: {source_path}")
        return _finalize_clean_result(result)
    rows, headers = _read_csv(source_path)
    if headers != QUEUE_SCHEMAS[import_type]:
        result["errors"].append(f"Headers do not match expected {import_type} schema or order.")
        return _finalize_clean_result(result)

    source_titles = _source_titles(Path(queue_dir), config)
    cleaned_rows = []
    for row_index, row in enumerate(rows, start=2):
        cleaned = {header: (row.get(header) or "").strip() for header in headers}
        if import_type == "proposed_updates" and _is_blank_row(cleaned):
            result["warnings"].append(f"Row {row_index}: skipped blank proposed_updates row.")
            continue
        if import_type == "extracted_claims":
            _clean_extracted_claim(cleaned, row_index, result, config["allowed_values"]["claim_types"])
        if import_type == "proposed_updates":
            _clean_proposed_update(cleaned, row_index, result, source_titles)
        cleaned_rows.append(cleaned)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(cleaned_rows)
    result["row_count"] = len(cleaned_rows)
    return _finalize_clean_result(result)


def append_manual_import(
    import_type: str,
    import_file: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    dry_run: bool = False,
    appended_at: datetime | None = None,
) -> dict[str, Any]:
    result = validate_manual_import(import_type, import_file, queue_dir, config, validated_at=appended_at)
    result["dry_run"] = dry_run
    result["validation_passed"] = result["overall_status"] != "fail"
    result["rows_appended"] = 0
    result["append_performed"] = False

    if not result["validation_passed"] or dry_run:
        result["next_step_notes"] = _append_notes(result)
        return result

    rows, _headers = _read_csv(Path(import_file))
    target_path = Path(result["target_queue_file"])
    _append_rows(target_path, QUEUE_SCHEMAS[import_type], rows)
    result["rows_appended"] = len(rows)
    result["append_performed"] = True
    import_log_path = Path(queue_dir) / config["queues"]["files"]["import_log"]
    append_import_log(
        import_log_path,
        operation=f"append_import:{import_type}",
        file_path=str(import_file),
        status="success",
        message=f"Appended {len(rows)} rows to {target_path.name}.",
        logged_at=appended_at,
    )
    result["next_step_notes"] = _append_notes(result)
    return result


def queue_summary(queue_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    counts = {
        "source_dossiers": _row_count(queue_path / config["queues"]["files"]["source_dossiers"]),
        "source_triage": _row_count(queue_path / config["queues"]["files"]["source_triage"]),
        "evidence_clusters": _row_count(queue_path / config["queues"]["files"].get("evidence_clusters", "")),
        "source_cluster_members": _row_count(queue_path / config["queues"]["files"].get("source_cluster_members", "")),
        "extracted_claims": _row_count(queue_path / config["queues"]["files"]["extracted_claims"]),
        "criteria_matrix": _row_count(queue_path / config["queues"]["files"]["criteria_matrix"]),
        "proposed_updates": _row_count(queue_path / config["queues"]["files"]["proposed_updates"]),
        "approved_updates": _row_count(queue_path / config["queues"]["files"]["approved_updates"]),
        "rejected_updates": _row_count(queue_path / config["queues"]["files"]["rejected_updates"]),
        "deferred_updates": _row_count(queue_path / config["queues"]["files"]["deferred_updates"]),
    }
    proposed_rows, _headers = _read_csv(queue_path / config["queues"]["files"]["proposed_updates"])
    by_status = Counter((row.get("review_status") or "").strip() or "(blank)" for row in proposed_rows)
    approved_rows, _approved_headers = _read_csv(queue_path / config["queues"]["files"]["approved_updates"])
    approved_exported = sum(1 for row in approved_rows if (row.get("export_status") or "").strip() == "exported")
    return {
        "queue_dir": str(queue_path),
        "counts": counts,
        "proposed_updates_by_review_status": dict(sorted(by_status.items())),
        "approved_updates_export_tracking": {
            "total": counts["approved_updates"],
            "exported": approved_exported,
            "not_exported": counts["approved_updates"] - approved_exported,
        },
    }


def write_queue_summary(summary: dict[str, Any], reports_dir: str | Path) -> Path:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    path = reports_path / f"queue_summary_{timestamp_for_filename()}.md"
    lines = ["# Queue Summary", "", f"- Queue directory: `{summary['queue_dir']}`", "", "## Counts"]
    for name, count in summary["counts"].items():
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Proposed Updates By Review Status"])
    for status, count in summary["proposed_updates_by_review_status"].items():
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Approved Updates Export Tracking"])
    for status, count in summary["approved_updates_export_tracking"].items():
        lines.append(f"- `{status}`: {count}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_manual_import_report(result: dict[str, Any]) -> str:
    lines = [
        "# Manual Import Validation Report",
        "",
        f"- Import type: `{result['import_type']}`",
        f"- Import file path: `{result['import_file_path']}`",
        f"- Timestamp: `{result['validation_timestamp']}`",
        f"- Row count: `{result['row_count']}`",
        f"- Target queue file: `{result['target_queue_file']}`",
        f"- Header status: `{result['header_status']}`",
        f"- Duplicate ID status: `{result['duplicate_id_status']}`",
        f"- Source ID reference status: `{result['source_id_reference_status']}`",
        f"- Claim ID reference status: `{result['claim_id_reference_status']}`",
        f"- MI5 validation status: `{result['mi5_validation_status']}`",
        f"- Score/weight validation status: `{result['score_weight_validation_status']}`",
        f"- Overall status: `{result['overall_status']}`",
    ]
    if "dry_run" in result:
        lines.extend(
            [
                f"- Dry run: `{result['dry_run']}`",
                f"- Validation passed: `{result['validation_passed']}`",
                f"- Append performed: `{result['append_performed']}`",
                f"- Rows appended: `{result['rows_appended']}`",
            ]
        )
    lines.extend(["", "## Errors", *_bullet_list(result["errors"])])
    lines.extend(["", "## Warnings", *_bullet_list(result["warnings"])])
    lines.extend(["", "## Next-Step Notes", *_bullet_list(result["next_step_notes"]), ""])
    return "\n".join(lines)


def _validate_required_fields(import_type: str, rows: list[dict[str, str]], result: dict[str, Any]) -> None:
    for index, row in enumerate(rows, start=2):
        for field in REQUIRED_FIELDS[import_type]:
            if not (row.get(field) or "").strip():
                result["errors"].append(f"Row {index}: {field} is required.")


def _validate_duplicate_ids(
    import_type: str,
    rows: list[dict[str, str]],
    existing_ids: set[str],
    result: dict[str, Any],
) -> None:
    id_field = ID_FIELDS[import_type]
    seen: set[str] = set()
    duplicate_found = False
    for index, row in enumerate(rows, start=2):
        row_id = (row.get(id_field) or "").strip()
        if not row_id:
            continue
        if row_id in seen:
            duplicate_found = True
            result["errors"].append(f"Row {index}: duplicate {id_field} within import file: {row_id}.")
        seen.add(row_id)
        if row_id in existing_ids:
            duplicate_found = True
            result["errors"].append(
                f"Row {index}: {id_field} already exists in target queue: {row_id}. "
                "This is safe: no rows were appended. Remove already-imported rows from the import file or skip this append."
            )
    result["duplicate_id_status"] = "fail" if duplicate_found else "pass"


def _validate_source_references(rows: list[dict[str, str]], source_ids: set[str], result: dict[str, Any]) -> None:
    missing = False
    for index, row in enumerate(rows, start=2):
        source_id = (row.get("source_id") or "").strip()
        if source_id and source_id not in source_ids:
            missing = True
            result["errors"].append(f"Row {index}: source_id not found in source_dossiers.csv: {source_id}.")
    result["source_id_reference_status"] = "fail" if missing else "pass"


def _validate_type_specific_fields(
    import_type: str,
    rows: list[dict[str, str]],
    known_claim_ids: set[str],
    result: dict[str, Any],
    config: dict[str, Any],
) -> None:
    if import_type == "extracted_claims":
        _validate_allowed_values(rows, "claim_type", config["allowed_values"]["claim_types"], result)
        _validate_allowed_values(rows, "status", config["allowed_values"]["review_statuses"], result)
    if import_type == "source_triage":
        _validate_allowed_values(rows, "triage_status", config["allowed_values"]["triage_statuses"], result)
        _validate_allowed_values(rows, "recommended_action", config["allowed_values"]["triage_actions"], result)
        _validate_numeric_fields(rows, ["priority_0_5"], result)
        result["score_weight_validation_status"] = (
            "fail" if _has_score_weight_errors(result) else "pass"
        )
    if import_type == "criteria_matrix":
        result["claim_id_reference_status"] = _validate_claim_references(rows, known_claim_ids, result)
        _validate_numeric_fields(rows, CRITERIA_SCORE_FIELDS, result)
    if import_type == "proposed_updates":
        result["claim_id_reference_status"] = _validate_claim_references(rows, known_claim_ids, result)
        _validate_numeric_fields(rows, ["suggested_weight_0_5"], result)
        _validate_allowed_values(rows, "review_status", config["allowed_values"]["review_statuses"], result)
        for field in MI5_COLUMNS:
            _validate_allowed_values(rows, field, config["allowed_values"]["mi5_labels"], result)
        result["mi5_validation_status"] = "fail" if _has_field_errors(result, MI5_COLUMNS) else "pass"

    if import_type in {"criteria_matrix", "proposed_updates"}:
        result["score_weight_validation_status"] = (
            "fail" if _has_score_weight_errors(result) else "pass"
        )
    elif import_type in {"extracted_claims", "source_triage"}:
        result["claim_id_reference_status"] = "not_applicable"


def _validate_allowed_values(
    rows: list[dict[str, str]],
    field: str,
    allowed: list[str],
    result: dict[str, Any],
) -> None:
    for index, row in enumerate(rows, start=2):
        value = (row.get(field) or "").strip()
        if value and value not in allowed:
            result["errors"].append(
                f"Row {index}: {field} has invalid value '{value}'. Allowed values: {', '.join(allowed)}. "
                "Try clean-import to normalize common manual CSV values into a separate cleaned file."
            )


def _validate_numeric_fields(rows: list[dict[str, str]], fields: list[str], result: dict[str, Any]) -> None:
    for index, row in enumerate(rows, start=2):
        for field in fields:
            value = (row.get(field) or "").strip()
            if not value:
                continue
            try:
                number = float(value)
            except ValueError:
                result["errors"].append(f"Row {index}: {field} must be blank or numeric from 0 to 5.")
                continue
            if number < 0 or number > 5:
                result["errors"].append(f"Row {index}: {field} must be between 0 and 5.")


def _validate_claim_references(rows: list[dict[str, str]], known_claim_ids: set[str], result: dict[str, Any]) -> str:
    missing = False
    for index, row in enumerate(rows, start=2):
        claim_id = (row.get("claim_id") or "").strip()
        if claim_id and claim_id not in known_claim_ids:
            missing = True
            result["errors"].append(f"Row {index}: claim_id not found in extracted claims: {claim_id}.")
    return "fail" if missing else "pass"


def _batch_claim_ids(
    import_type: str,
    import_file: Path,
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> set[str]:
    if import_type == "extracted_claims":
        return {(row.get("claim_id") or "").strip() for row in rows if (row.get("claim_id") or "").strip()}

    ids: set[str] = set()
    for source_id in {(row.get("source_id") or "").strip() for row in rows if (row.get("source_id") or "").strip()}:
        sibling_paths = [import_file.parent / f"{source_id}_extracted_claims.csv"]
        sibling_paths.extend(sorted(import_file.parent.glob(f"{source_id}_*_extracted_claims.csv")))
        for sibling in sibling_paths:
            if not sibling.exists():
                continue
            sibling_rows, headers = _read_csv(sibling)
            if headers == QUEUE_SCHEMAS["extracted_claims"]:
                ids.update(
                    (row.get("claim_id") or "").strip()
                    for row in sibling_rows
                    if (row.get("claim_id") or "").strip()
                )
    return ids


def _existing_ids(path: Path, field: str) -> set[str]:
    rows, _headers = _read_csv(path)
    return {(row.get(field) or "").strip() for row in rows if (row.get(field) or "").strip()}


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), reader.fieldnames or []


def _append_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def _row_count(path: Path) -> int:
    rows, _headers = _read_csv(path)
    return len(rows)


def _finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    result["overall_status"] = "fail" if result["errors"] else ("warning" if result["warnings"] else "pass")
    if result["errors"]:
        result["next_step_notes"] = [
            "Fix validation errors before appending this import.",
            "For BOMs, extracted status labels, needs_review statuses, multi-label claim_type cells, or blank source_book cells, run clean-import and validate the cleaned copy.",
        ]
    elif result["warnings"]:
        result["next_step_notes"] = ["Review warnings before appending this import."]
    else:
        result["next_step_notes"] = ["Import is valid and can be appended or dry-run previewed."]
    return result


def _append_notes(result: dict[str, Any]) -> list[str]:
    if not result["validation_passed"]:
        return ["Validation failed. No rows were appended."]
    if result["dry_run"]:
        return [f"Dry run only. {result['row_count']} rows would be appended."]
    return [f"Appended {result['rows_appended']} rows to the target queue."]


def _clean_extracted_claim(
    row: dict[str, str],
    row_index: int,
    result: dict[str, Any],
    allowed_claim_types: list[str],
) -> None:
    if row.get("status") == "extracted":
        row["status"] = "proposed"
        result["changes"].append(f"Row {row_index}: status extracted -> proposed.")
    claim_type = row.get("claim_type", "")
    normalized_claim_type = _normalize_claim_type(claim_type, set(allowed_claim_types))
    if normalized_claim_type and normalized_claim_type != claim_type:
        row["claim_type"] = normalized_claim_type
        result["changes"].append(f"Row {row_index}: claim_type {claim_type} -> {row['claim_type']}.")
    if _has_multiple_claim_type_labels(claim_type):
        parts = _split_claim_type_labels(claim_type)
        normalized = [_normalize_claim_type(part, set(allowed_claim_types)) for part in parts]
        normalized = [value for value in normalized if value]
        if normalized:
            original = claim_type
            row["claim_type"] = normalized[0]
            note = f"Original multi-label claim_type: {original}"
            row["uncertainty_notes"] = f"{row.get('uncertainty_notes', '')}; {note}".strip("; ")
            if row["claim_type"] != normalized_claim_type:
                result["changes"].append(f"Row {row_index}: claim_type {original} -> {row['claim_type']}.")
        else:
            result["warnings"].append(f"Row {row_index}: multi-label claim_type could not be normalized: {claim_type}.")


def _clean_proposed_update(
    row: dict[str, str],
    row_index: int,
    result: dict[str, Any],
    source_titles: dict[str, str],
) -> None:
    review_status = row.get("review_status", "")
    normalized_status = REVIEW_STATUS_ALIASES.get(review_status.strip().lower().replace("-", "_"))
    if normalized_status:
        row["review_status"] = normalized_status
        result["changes"].append(f"Row {row_index}: review_status {review_status} -> {normalized_status}.")
    if not row.get("source_book"):
        source_title = source_titles.get(row.get("source_id", ""), "")
        if source_title:
            row["source_book"] = source_title
            result["changes"].append(f"Row {row_index}: blank source_book -> {source_title}.")
        else:
            result["warnings"].append(f"Row {row_index}: source_book is blank and no source title was found.")


def _normalize_claim_type(value: str, allowed: set[str]) -> str:
    normalized = _enumish(value)
    if normalized in allowed:
        return normalized
    text = value.strip().lower().replace("_", " ").replace("-", " ")
    if text in CLAIM_TYPE_ALIASES:
        return CLAIM_TYPE_ALIASES[text]
    claimless = text.removesuffix(" claim").strip()
    if claimless in CLAIM_TYPE_ALIASES:
        return CLAIM_TYPE_ALIASES[claimless]
    claimless_enum = _enumish(claimless)
    if claimless_enum in allowed:
        return claimless_enum
    for part in _split_claim_type_labels(value):
        part_normalized = _normalize_single_claim_type_label(part, allowed)
        if part_normalized:
            return part_normalized
    return ""


def _normalize_single_claim_type_label(value: str, allowed: set[str]) -> str:
    normalized = _enumish(value)
    if normalized in allowed:
        return normalized
    text = value.strip().lower().replace("_", " ").replace("-", " ")
    if text in CLAIM_TYPE_ALIASES:
        return CLAIM_TYPE_ALIASES[text]
    claimless = text.removesuffix(" claim").strip()
    if claimless in CLAIM_TYPE_ALIASES:
        return CLAIM_TYPE_ALIASES[claimless]
    claimless_enum = _enumish(claimless)
    if claimless_enum in allowed:
        return claimless_enum
    return ""


def _enumish(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


def _has_multiple_claim_type_labels(value: str) -> bool:
    return ";" in value or "/" in value


def _split_claim_type_labels(value: str) -> list[str]:
    parts = [value]
    for separator in (";", "/"):
        split_parts: list[str] = []
        for part in parts:
            split_parts.extend(part.split(separator))
        parts = split_parts
    return [part.strip() for part in parts if part.strip()]


def _is_blank_row(row: dict[str, str]) -> bool:
    return not any((value or "").strip() for value in row.values())


def _source_titles(queue_dir: Path, config: dict[str, Any]) -> dict[str, str]:
    rows, _headers = _read_csv(queue_dir / config["queues"]["files"]["source_dossiers"])
    return {
        (row.get("source_id") or "").strip(): (row.get("title") or "").strip()
        for row in rows
        if (row.get("source_id") or "").strip()
    }


def _finalize_clean_result(result: dict[str, Any]) -> dict[str, Any]:
    result["overall_status"] = "fail" if result["errors"] else ("warning" if result["warnings"] else "pass")
    if result["errors"]:
        result["next_step_notes"] = ["No cleaned import was written. Fix the errors and rerun clean-import."]
    else:
        result["next_step_notes"] = [
            "Cleaned import written to a separate file.",
            f"Next: python -m belief_dashboard.cli validate-import --type {result['import_type']} --file {result['output_file_path']}",
        ]
    return result


def _has_field_errors(result: dict[str, Any], fields: list[str]) -> bool:
    return any(any(field in error for field in fields) for error in result["errors"])


def _has_score_weight_errors(result: dict[str, Any]) -> bool:
    markers = ["must be blank or numeric from 0 to 5", "must be between 0 and 5"]
    return any(any(marker in error for marker in markers) for error in result["errors"])


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
