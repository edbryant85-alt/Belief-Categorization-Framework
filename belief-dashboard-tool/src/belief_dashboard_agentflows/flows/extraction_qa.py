from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from belief_dashboard.utils import timestamp_for_filename
from belief_dashboard_agentflows.cli_runner import CliResult, run_cli_command
from belief_dashboard_agentflows.config_reader import read_config
from belief_dashboard_agentflows.queue_reader import manual_imports_dir, read_csv_rows, read_queue, reports_dir
from belief_dashboard_agentflows.reports.json import write_json_report
from belief_dashboard_agentflows.reports.markdown import write_markdown_report
from belief_dashboard_agentflows.schema_reader import criteria_score_fields


IMPORT_TYPES = ("extracted_claims", "criteria_matrix", "proposed_updates")


def run_extraction_qa(
    source_id: str,
    *,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    output_format: str = "markdown",
    save: bool = False,
) -> dict[str, Any]:
    config = read_config(project_dir, config_path)
    imports_dir = manual_imports_dir(project_dir, config)
    files = {
        "extracted_claims": imports_dir / f"{source_id}_extracted_claims.csv",
        "criteria_matrix": imports_dir / f"{source_id}_criteria_matrix.csv",
        "proposed_updates": imports_dir / f"{source_id}_proposed_updates.csv",
    }
    commands: list[CliResult] = []
    blockers: list[str] = []
    warnings: list[str] = []
    cleaned_candidates: list[str] = []

    for import_type, file_path in files.items():
        if not file_path.exists():
            blockers.append(f"Missing manual import file for {import_type}: {file_path}")
            continue
        result = run_cli_command(
            ["validate-import", "--type", import_type, "--file", str(file_path)],
            project_dir=project_dir,
            config_path=config_path,
        )
        commands.append(result)
        if result.return_code != 0:
            warnings.append(f"CLI validation did not pass for {import_type}.")
            cleaned_path = _cleaned_path(file_path)
            clean_result = run_cli_command(
                ["clean-import", "--type", import_type, "--file", str(file_path), "--output", str(cleaned_path)],
                project_dir=project_dir,
                config_path=config_path,
            )
            commands.append(clean_result)
            if clean_result.return_code == 0:
                cleaned_candidates.append(str(cleaned_path))

    extracted = read_csv_rows(files["extracted_claims"])
    criteria = read_csv_rows(files["criteria_matrix"])
    proposals = read_csv_rows(files["proposed_updates"])
    existing_claim_ids = {row.get("claim_id", "") for row in read_queue(project_dir, config, "extracted_claims")}
    batch_claim_ids = {row.get("claim_id", "") for row in extracted if row.get("claim_id", "")}
    known_claim_ids = existing_claim_ids | batch_claim_ids

    _check_duplicate_ids("extracted_claims", extracted, "claim_id", blockers)
    _check_duplicate_ids("criteria_matrix", criteria, "claim_id", blockers)
    _check_duplicate_ids("proposed_updates", proposals, "proposal_id", blockers)
    _check_source_ids(source_id, [*extracted, *criteria, *proposals], warnings)
    _check_references("criteria_matrix", criteria, known_claim_ids, blockers)
    _check_references("proposed_updates", proposals, known_claim_ids, blockers)
    _check_orphans(batch_claim_ids, criteria, proposals, warnings)
    _check_quality(criteria, proposals, warnings)

    validation_failed = any(command.return_code != 0 for command in commands if command.command and command.command[0] == "validate-import")
    if blockers:
        status = "blocked"
    elif validation_failed or cleaned_candidates:
        status = "needs_cleanup"
    else:
        status = "pass"

    report = {
        "title": "Extraction QA Report",
        "flow": "extraction-qa",
        "source_id": source_id,
        "status": status,
        "files": {name: str(path) for name, path in files.items()},
        "cleaned_candidates": cleaned_candidates,
        "blockers": blockers,
        "warnings": warnings,
        "recommended_next_command": _next_command(status, source_id, cleaned_candidates),
        "commands_run": [_command_summary(command) for command in commands],
    }
    if save:
        _write_reports(project_dir, "extraction_qa", source_id, report)
    return report


def _cleaned_path(file_path: Path) -> Path:
    if file_path.name.endswith("_cleaned.csv"):
        return file_path
    return file_path.with_name(f"{file_path.stem}_cleaned.csv")


def _check_duplicate_ids(queue_name: str, rows: list[dict[str, str]], field: str, blockers: list[str]) -> None:
    counts = Counter(row.get(field, "") for row in rows if row.get(field, ""))
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    for duplicate in duplicates:
        blockers.append(f"{queue_name} contains duplicate {field}: {duplicate}")


def _check_source_ids(source_id: str, rows: list[dict[str, str]], warnings: list[str]) -> None:
    mismatches = sorted({row.get("source_id", "") for row in rows if row.get("source_id", "") and row.get("source_id", "") != source_id})
    for mismatch in mismatches:
        warnings.append(f"Row references source_id {mismatch}, expected {source_id}.")


def _check_references(queue_name: str, rows: list[dict[str, str]], known_claim_ids: set[str], blockers: list[str]) -> None:
    missing = sorted({row.get("claim_id", "") for row in rows if row.get("claim_id", "") and row.get("claim_id", "") not in known_claim_ids})
    for claim_id in missing:
        blockers.append(f"{queue_name} references missing claim_id: {claim_id}")


def _check_orphans(batch_claim_ids: set[str], criteria: list[dict[str, str]], proposals: list[dict[str, str]], warnings: list[str]) -> None:
    criteria_ids = {row.get("claim_id", "") for row in criteria}
    proposal_ids = {row.get("claim_id", "") for row in proposals}
    for claim_id in sorted(batch_claim_ids - criteria_ids):
        warnings.append(f"Claim {claim_id} has no criteria row in this import batch.")
    for claim_id in sorted(batch_claim_ids - proposal_ids):
        warnings.append(f"Claim {claim_id} has no proposed update in this import batch.")


def _check_quality(criteria: list[dict[str, str]], proposals: list[dict[str, str]], warnings: list[str]) -> None:
    score_fields = criteria_score_fields()
    for row in criteria:
        values = [row.get(field, "") for field in score_fields if row.get(field, "") != ""]
        if len(values) >= 6 and len(set(values)) == 1:
            warnings.append(f"Criteria row {row.get('claim_id', '')} has suspiciously uniform scores.")
    for row in proposals:
        if row.get("suggested_weight_0_5") in {"4", "5"} and not row.get("suggestion_rationale", "").strip():
            warnings.append(f"Proposal {row.get('proposal_id', '')} has high suggested weight without rationale.")
        if not row.get("uncertainty_notes", "").strip():
            warnings.append(f"Proposal {row.get('proposal_id', '')} has blank uncertainty notes.")


def _next_command(status: str, source_id: str, cleaned_candidates: list[str]) -> str:
    if status == "blocked":
        return "Fix blocking issues, then rerun extraction-qa."
    if cleaned_candidates:
        return f"Review cleaned candidates for {source_id}, then run validate-import on each cleaned file."
    return f"Run append-import for {source_id} files only after human review."


def _command_summary(result: CliResult) -> dict[str, Any]:
    return {
        "command": " ".join(result.command),
        "return_code": result.return_code,
        "risk": result.policy.risk.value,
        "stdout_preview": result.stdout[:1000],
        "stderr_preview": result.stderr[:1000],
    }


def _write_reports(project_dir: str | Path, flow_name: str, source_id: str, report: dict[str, Any]) -> None:
    base = reports_dir(project_dir) / flow_name
    stamp = timestamp_for_filename()
    write_markdown_report(base / f"{flow_name}_{source_id}_{stamp}.md", report)
    write_json_report(base / f"{flow_name}_{source_id}_{stamp}.json", report)
