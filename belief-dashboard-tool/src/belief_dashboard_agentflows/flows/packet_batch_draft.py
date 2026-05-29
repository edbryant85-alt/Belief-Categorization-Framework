from __future__ import annotations

import csv
import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.extraction_workspace import diagnose_import_shape
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard_agentflows.cli_runner import CliResult, run_cli_command
from belief_dashboard_agentflows.config_reader import read_config
from belief_dashboard_agentflows.flows.extraction_qa import run_extraction_qa
from belief_dashboard_agentflows.queue_reader import manual_imports_dir, queue_dir, read_csv_rows, read_queue


IMPORT_TYPES = ("extracted_claims", "criteria_matrix", "proposed_updates")
MVP_SOURCE_ID = "SRC0018"
MVP_GROUP_NAME = "Introduction / What Good Is Apologetics"
MVP_PACKET_IDS = ["SRC0018-PKT-002", "SRC0018-PKT-003", "SRC0018-PKT-004"]
MVP_SLUG = "SRC0018_intro_apologetics"
MVP_REPORT_DIR = Path("reports/agentflow_runs/SRC0018_intro_apologetics_batch")
MVP_MANUAL_DIR = Path("data/manual_imports/generated_batches/SRC0018_intro_apologetics")


def run_packet_batch_draft(
    *,
    source_id: str,
    batch_name: str = "",
    packet_ids: list[str] | None = None,
    packet_cycle_group: str | None = None,
    overwrite: bool = False,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    project = Path(project_dir)
    config = read_config(project, config_path)
    resolved_batch = batch_name or packet_cycle_group or MVP_GROUP_NAME
    resolved_packet_ids = _resolve_mvp_packet_ids(source_id, packet_ids or [], packet_cycle_group)
    report_dir = project / MVP_REPORT_DIR
    generated_dir = report_dir / "generated"
    cleaned_dir = report_dir / "cleaned"
    logs_dir = report_dir / "logs"
    manual_dir = project / MVP_MANUAL_DIR
    output_files = _output_files(generated_dir, manual_dir, report_dir)

    try:
        _check_no_existing_outputs(output_files, overwrite=overwrite)
        packet_files = _locate_packets(project, source_id, resolved_packet_ids)
        packet_checks = _check_packet_integrity(source_id, packet_files)
        if not all(check["status"] == "pass" for check in packet_checks.values()):
            report = _base_report(project, source_id, config, resolved_batch, resolved_packet_ids, packet_files, output_files)
            report["status"] = "failed"
            report["checks"]["packet_integrity"] = packet_checks
            report["blockers"] = _failed_check_messages(packet_checks)
            _write_reports(report, report_dir)
            return report

        generated_dir.mkdir(parents=True, exist_ok=True)
        cleaned_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        manual_dir.mkdir(parents=True, exist_ok=True)

        next_ids = _next_id_summary(project, config, source_id, output_files)
        rows = _draft_rows(source_id, next_ids)
        _write_csv(output_files["generated"]["extracted_claims"], "extracted_claims", rows["extracted_claims"])
        _write_csv(output_files["generated"]["criteria_matrix"], "criteria_matrix", rows["criteria_matrix"])
        _write_csv(output_files["generated"]["proposed_updates"], "proposed_updates", rows["proposed_updates"])
        for import_type in IMPORT_TYPES:
            shutil.copy2(output_files["generated"][import_type], output_files["manual"][import_type])

        shape = {
            import_type: diagnose_import_shape(import_type, output_files["manual"][import_type], config)
            for import_type in IMPORT_TYPES
        }
        validation, clean, final_files, validation_commands = _run_validation_and_cleaning(
            project,
            config_path,
            output_files["manual"],
            cleaned_dir,
            logs_dir,
        )
        extraction_qa = run_extraction_qa(
            source_id,
            project_dir=project,
            config_path=config_path,
            extracted_claims_file=output_files["manual"]["extracted_claims"],
            criteria_matrix_file=output_files["manual"]["criteria_matrix"],
            proposed_updates_file=output_files["manual"]["proposed_updates"],
        )
        append_dry_run, dry_run_commands = _run_append_dry_runs(project, config_path, final_files, logs_dir)
        commands = [*validation_commands, *extraction_qa.get("commands_run", []), *dry_run_commands]

        report = _base_report(project, source_id, config, resolved_batch, resolved_packet_ids, packet_files, output_files)
        report.update(
            {
                "status": _overall_status(validation, extraction_qa, append_dry_run),
                "row_counts": {import_type: len(rows[import_type]) for import_type in IMPORT_TYPES},
                "next_id_summary": next_ids,
                "checks": {
                    "packet_integrity": packet_checks,
                    "shape_diagnosis": shape,
                    "clean_import": clean,
                    "validate_import": validation,
                    "extraction_qa": extraction_qa,
                    "append_import_dry_run": append_dry_run,
                },
                "commands_run": commands,
                "generated_at": (generated_at or datetime.now()).replace(microsecond=0).isoformat(),
            }
        )
        markdown_path, json_path = _write_reports(report, report_dir)
        report["output_files"]["markdown_report"] = str(markdown_path)
        report["output_files"]["json_report"] = str(json_path)
        zip_path = _write_zip(report, output_files, logs_dir, markdown_path, json_path)
        report["output_files"]["zip"] = str(zip_path)
        _write_reports(report, report_dir)
        return report
    except Exception as exc:
        report = _base_report(project, source_id, config, resolved_batch, resolved_packet_ids if "resolved_packet_ids" in locals() else [], {}, output_files)
        report["status"] = "failed"
        report["blockers"] = [str(exc)]
        if not isinstance(exc, FileExistsError):
            _write_reports(report, report_dir)
        return report


def render_packet_batch_draft_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Packet Batch Draft Report",
        "",
        f"- Status: `{report.get('status', '')}`",
        f"- Source ID: `{report.get('source_id', '')}`",
        f"- Source title: {report.get('source_title', '')}",
        f"- Batch name: {report.get('batch_name', '')}",
        f"- Packet IDs: `{', '.join(report.get('packet_ids', []))}`",
        f"- Mutated queues: `{report.get('mutated_queues')}`",
        f"- Mutated workbook: `{report.get('mutated_workbook')}`",
        f"- Human review required: `{report.get('human_review_required')}`",
        "",
        "## Command Invocation",
        "",
        "```bash",
        report.get("command_invocation", ""),
        "```",
        "",
        "## Packet Files Used",
        *_bullets([f"`{path}`" for path in report.get("packet_files", [])]),
        "",
        "## Packet Integrity Checks",
    ]
    for packet_id, check in report.get("checks", {}).get("packet_integrity", {}).items():
        lines.append(f"- `{packet_id}`: `{check.get('status')}` - {', '.join(check.get('messages', [])) or 'schema-locked packet verified'}")
    lines.extend(
        [
            "",
            "## Exact Schemas Found/Used",
            *_bullets([f"`{item}`" for item in IMPORT_TYPES]),
            "",
            "## Output CSV Paths",
        ]
    )
    outputs = report.get("output_files", {})
    for import_type in IMPORT_TYPES:
        lines.append(f"- {import_type}: `{outputs.get(import_type, '')}`")
    lines.extend(
        [
            f"- zip: `{outputs.get('zip', '')}`",
            "",
            "## Row Counts",
        ]
    )
    for key, value in report.get("row_counts", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Next ID Calculation Summary"])
    for key, value in report.get("next_id_summary", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Scope-Control Summary",
            "",
            "Included:",
            *_bullets(report.get("scope", {}).get("included", [])),
            "",
            "Excluded:",
            *_bullets(report.get("scope", {}).get("excluded", [])),
            "",
            "## Claims Intentionally Excluded",
            *_bullets(report.get("claims_intentionally_excluded", [])),
            "",
            "## Shape Diagnosis Results",
        ]
    )
    for import_type, result in report.get("checks", {}).get("shape_diagnosis", {}).items():
        lines.append(f"- {import_type}: `{result.get('overall_status', 'not_run')}`")
    lines.extend(["", "## Clean-Import Results"])
    for import_type, result in report.get("checks", {}).get("clean_import", {}).items():
        lines.append(f"- {import_type}: `{result.get('status', 'not_run')}`")
    lines.extend(["", "## Validate-Import Results"])
    for import_type, result in report.get("checks", {}).get("validate_import", {}).items():
        lines.append(f"- {import_type}: `{result.get('status', 'not_run')}` (return_code={result.get('return_code', '')})")
    lines.extend(
        [
            "",
            "## Extraction-QA Results",
            "",
            f"- Status: `{report.get('checks', {}).get('extraction_qa', {}).get('status', 'not_run')}`",
            "- Blockers:",
            *_bullets(report.get("checks", {}).get("extraction_qa", {}).get("blockers", [])),
            "- Warnings:",
            *_bullets(report.get("checks", {}).get("extraction_qa", {}).get("warnings", [])),
            "",
            "## Append-Import --Dry-Run Results",
        ]
    )
    for import_type, result in report.get("checks", {}).get("append_import_dry_run", {}).items():
        lines.append(f"- {import_type}: `{result.get('status', 'not_run')}` (return_code={result.get('return_code', '')})")
    lines.extend(
        [
            "",
            "## No-Mutation Statement",
            "",
            "No central queues or workbook files were mutated. No proposals were approved, rejected, or deferred. No workbook export, verification with mark-exported, promotion, rollback, commit, or push was performed.",
            "",
            "## Exact Next Safe Human Commands",
            "",
            "```bash",
            *report.get("next_safe_human_commands", []),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_mvp_packet_ids(source_id: str, packet_ids: list[str], packet_cycle_group: str | None) -> list[str]:
    if source_id != MVP_SOURCE_ID:
        raise ValueError("MVP packet-batch-draft currently supports only SRC0018.")
    if packet_cycle_group:
        if packet_cycle_group != MVP_GROUP_NAME:
            raise ValueError(f"Unsupported packet-cycle group for MVP: {packet_cycle_group}")
        if packet_ids and packet_ids != MVP_PACKET_IDS:
            raise ValueError("Do not mix packet-cycle group with non-MVP packet IDs.")
        return list(MVP_PACKET_IDS)
    if not packet_ids:
        raise ValueError("At least one --packet-id or the MVP --packet-cycle-group is required.")
    if packet_ids != MVP_PACKET_IDS:
        raise ValueError("MVP refuses to process anything except SRC0018-PKT-002, SRC0018-PKT-003, and SRC0018-PKT-004 in order.")
    return list(packet_ids)


def _output_files(generated_dir: Path, manual_dir: Path, report_dir: Path) -> dict[str, Any]:
    names = {
        "extracted_claims": f"{MVP_SLUG}_extracted_claims.csv",
        "criteria_matrix": f"{MVP_SLUG}_criteria_matrix.csv",
        "proposed_updates": f"{MVP_SLUG}_proposed_updates.csv",
    }
    return {
        "generated": {key: generated_dir / name for key, name in names.items()},
        "manual": {key: manual_dir / name for key, name in names.items()},
        "markdown_report": report_dir / "packet_batch_draft_report.md",
        "json_report": report_dir / "packet_batch_draft_report.json",
        "zip": report_dir / "SRC0018_intro_apologetics_batch_artifacts.zip",
    }


def _check_no_existing_outputs(output_files: dict[str, Any], *, overwrite: bool) -> None:
    if overwrite:
        return
    paths = [*output_files["generated"].values(), *output_files["manual"].values(), output_files["markdown_report"], output_files["json_report"], output_files["zip"]]
    existing = [str(path) for path in paths if Path(path).exists()]
    if existing:
        raise FileExistsError("Output files already exist. Pass --overwrite to regenerate: " + ", ".join(existing))


def _locate_packets(project: Path, source_id: str, packet_ids: list[str]) -> dict[str, Path]:
    prompt_dir = project / "reports" / "prompt_packets"
    packet_files = {}
    for packet_id in packet_ids:
        number = int(packet_id.rsplit("-", 1)[1].removeprefix("PKT-"))
        candidates = sorted(prompt_dir.glob(f"{source_id}_schema_locked_packet_{number:02d}_*.md"), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        for candidate in candidates:
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if f"- Packet ID: {packet_id}" in text:
                packet_files[packet_id] = candidate
                break
        if packet_id not in packet_files:
            raise FileNotFoundError(f"Could not locate schema-locked packet file for {packet_id}")
    return packet_files


def _check_packet_integrity(source_id: str, packet_files: dict[str, Path]) -> dict[str, dict[str, Any]]:
    checks = {}
    for packet_id, path in packet_files.items():
        text = path.read_text(encoding="utf-8", errors="replace")
        messages = []
        required = {
            "source_id": f"- Source ID: {source_id}" in text,
            "packet_id": f"- Packet ID: {packet_id}" in text,
            "schema_locked": "Schema-Locked Extraction Prompt Packet" in text and "strict local CSV validator" in text,
            "extracted_claims_schema": "### extracted_claims" in text and ",".join(QUEUE_SCHEMAS["extracted_claims"]) in text,
            "criteria_matrix_schema": "### criteria_matrix" in text and ",".join(QUEUE_SCHEMAS["criteria_matrix"]) in text,
            "proposed_updates_schema": "### proposed_updates" in text and ",".join(QUEUE_SCHEMAS["proposed_updates"]) in text,
            "source_text": "## Source Text" in text,
        }
        for name, passed in required.items():
            if not passed:
                messages.append(f"{name} check failed")
        checks[packet_id] = {"status": "pass" if not messages else "fail", "file": str(path), "messages": messages}
    return checks


def _next_id_summary(project: Path, config: dict[str, Any], source_id: str, output_files: dict[str, Any]) -> dict[str, Any]:
    del output_files
    claim_numbers = _used_numbers(project, config, source_id, "claim_id", f"{source_id}-C")
    proposal_numbers = _used_numbers(project, config, source_id, "proposal_id", f"{source_id}-P")
    next_claim = max(claim_numbers or [0]) + 1
    next_proposal = max(proposal_numbers or [0]) + 1
    return {
        "claim_prefix": f"{source_id}-C",
        "proposal_prefix": f"{source_id}-P",
        "highest_existing_claim_number": max(claim_numbers or [0]),
        "highest_existing_proposal_number": max(proposal_numbers or [0]),
        "next_claim_id": f"{source_id}-C{next_claim:03d}",
        "next_proposal_id": f"{source_id}-P{next_proposal:03d}",
        "claim_count_considered": len(claim_numbers),
        "proposal_count_considered": len(proposal_numbers),
    }


def _used_numbers(project: Path, config: dict[str, Any], source_id: str, field: str, prefix: str) -> list[int]:
    numbers: list[int] = []
    for queue_name in ["extracted_claims", "criteria_matrix", "proposed_updates", "approved_updates", "rejected_updates", "deferred_updates"]:
        for row in read_queue(project, config, queue_name):
            numbers.extend(_number_from_row(row, source_id, field, prefix))
    manual_dir = manual_imports_dir(project, config)
    for path in manual_dir.rglob("*.csv"):
        for row in read_csv_rows(path):
            numbers.extend(_number_from_row(row, source_id, field, prefix))
    return numbers


def _number_from_row(row: dict[str, str], source_id: str, field: str, prefix: str) -> list[int]:
    values = []
    if row.get("source_id") == source_id:
        values.append(row.get(field, ""))
    if field != "claim_id" and row.get("claim_id", "").startswith(f"{source_id}-C"):
        values.append(row.get(field, ""))
    numbers = []
    for value in values:
        if value.startswith(prefix) and value.removeprefix(prefix).isdigit():
            numbers.append(int(value.removeprefix(prefix)))
    return numbers


def _draft_rows(source_id: str, next_ids: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    claim_start = int(str(next_ids["next_claim_id"]).rsplit("C", 1)[1])
    proposal_start = int(str(next_ids["next_proposal_id"]).rsplit("P", 1)[1])
    claim_ids = [f"{source_id}-C{claim_start + index:03d}" for index in range(9)]
    proposal_ids = [f"{source_id}-P{proposal_start + index:03d}" for index in range(6)]
    claims = [
        _claim(claim_ids[0], source_id, "Craig defines apologetics as the branch of Christian theology that seeks to provide a rational justification for the truth claims of the Christian faith.", "definition", "Definition of apologetics. Packet IDs: SRC0018-PKT-002."),
        _claim(claim_ids[1], source_id, "Craig treats apologetics as primarily a theoretical discipline with practical applications, not primarily as training in debating, question-answering, or evangelism technique.", "interpretive_claim", "Theoretical/practical distinction. Packet IDs: SRC0018-PKT-002."),
        _claim(claim_ids[2], source_id, "Craig says apologetics asks what rational warrant can be given for the Christian faith, so practical response tactics are logically secondary to the theoretical issue.", "argument", "Purpose of apologetics. Packet IDs: SRC0018-PKT-002."),
        _claim(claim_ids[3], source_id, "Craig presents Reasonable Faith as a seminary-level textbook that offers his personal positive apologetic for the Christian faith rather than a history of apologetics or survey of evangelical apologetic systems.", "interpretive_claim", "Book scope-control. Packet IDs: SRC0018-PKT-002."),
        _claim(claim_ids[4], source_id, "Craig structures the book around selected theological loci in an order governed by the logic of building a positive case for Christianity.", "interpretive_claim", "Book structure and scope. Packet IDs: SRC0018-PKT-002."),
        _claim(claim_ids[5], source_id, "Craig argues that apologetics matters for shaping culture because the gospel is heard against a cultural background that can make Christianity seem either viable or absurd.", "argument", "Apologetics and culture. Packet IDs: SRC0018-PKT-002, SRC0018-PKT-003."),
        _claim(claim_ids[6], source_id, "Craig argues that apologetics helps create and sustain a cultural milieu in which the gospel can be heard as an intellectually viable option for thinking people.", "argument", "Cultural role of apologetics. Packet IDs: SRC0018-PKT-003."),
        _claim(claim_ids[7], source_id, "Craig argues that apologetics strengthens believers by giving intellectual substance, answers to objections, confidence that Christian faith is logical, and stability grounded in objective truth.", "argument", "Strengthening believers. Packet IDs: SRC0018-PKT-003, SRC0018-PKT-004."),
        _claim(claim_ids[8], source_id, "Craig argues that apologetics contributes to evangelism by giving believers confidence and by reaching the minority of unbelievers who respond to rational argument and evidence.", "argument", "Evangelizing unbelievers. Packet IDs: SRC0018-PKT-004."),
    ]
    criteria = [
        _criteria(claim_ids[0], source_id, "5", "4", "5", "3", "3", "3", "0", "1", "2", "1", "1", "2", "Definition anchors the batch scope."),
        _criteria(claim_ids[1], source_id, "4", "4", "4", "3", "3", "3", "1", "1", "2", "1", "1", "2", "Useful scope distinction for extraction and later review."),
        _criteria(claim_ids[2], source_id, "4", "4", "4", "3", "3", "3", "1", "1", "2", "1", "1", "2", "Clarifies theoretical warrant rather than tactics."),
        _criteria(claim_ids[3], source_id, "4", "4", "4", "2", "3", "4", "0", "1", "1", "1", "1", "1", "Book scope-control claim."),
        _criteria(claim_ids[4], source_id, "4", "4", "4", "2", "3", "4", "0", "1", "1", "1", "1", "1", "Book structure and scope-control claim."),
        _criteria(claim_ids[5], source_id, "5", "4", "4", "4", "4", "4", "1", "2", "3", "2", "2", "3", "Core culture-shaping argument."),
        _criteria(claim_ids[6], source_id, "5", "4", "4", "4", "4", "4", "1", "2", "3", "2", "2", "3", "Core apologetics/culture claim."),
        _criteria(claim_ids[7], source_id, "5", "4", "4", "4", "4", "4", "1", "2", "4", "2", "3", "4", "Core believer-strengthening claim."),
        _criteria(claim_ids[8], source_id, "5", "4", "4", "4", "4", "4", "1", "2", "4", "2", "3", "4", "Core evangelism claim."),
    ]
    proposals = [
        _proposal(proposal_ids[0], claim_ids[0], source_id, claims[0]["claim_text"], "Apologetics definition", "3", "Definition is central to interpreting the rest of the source."),
        _proposal(proposal_ids[1], claim_ids[3], source_id, claims[3]["claim_text"], "Source scope-control", "2", "Useful for constraining later extraction from the book."),
        _proposal(proposal_ids[2], claim_ids[5], source_id, claims[5]["claim_text"], "Apologetics and culture", "3", "Craig gives a reasoned account of why apologetics matters beyond immediate conversion."),
        _proposal(proposal_ids[3], claim_ids[6], source_id, claims[6]["claim_text"], "Apologetics and culture", "3", "This is a concise workbook-worthy version of the cultural milieu argument."),
        _proposal(proposal_ids[4], claim_ids[7], source_id, claims[7]["claim_text"], "Apologetics and discipleship", "3", "Craig connects apologetics with believer perseverance and intellectual maturity."),
        _proposal(proposal_ids[5], claim_ids[8], source_id, claims[8]["claim_text"], "Apologetics and evangelism", "3", "Craig defends a limited but real evangelistic role for apologetics."),
    ]
    return {"extracted_claims": claims, "criteria_matrix": criteria, "proposed_updates": proposals}


def _claim(claim_id: str, source_id: str, text: str, claim_type: str, context: str) -> dict[str, str]:
    return {
        "claim_id": claim_id,
        "source_id": source_id,
        "claim_text": text,
        "claim_type": claim_type,
        "argument_summary": text,
        "source_context": context,
        "quoted_excerpt": "",
        "related_hypotheses": "EC; PC; CT; N",
        "supports_hypotheses": "CT",
        "undermines_hypotheses": "N",
        "possible_defeater_for": "",
        "uncertainty_notes": "First-pass draft from selected introduction packets only; human review required before append.",
        "status": "proposed",
    }


def _criteria(claim_id: str, source_id: str, *values: str) -> dict[str, str]:
    fields = QUEUE_SCHEMAS["criteria_matrix"][2:]
    return {"claim_id": claim_id, "source_id": source_id, **dict(zip(fields, values, strict=True))}


def _proposal(proposal_id: str, claim_id: str, source_id: str, evidence: str, category: str, weight: str, rationale: str) -> dict[str, str]:
    return {
        "proposal_id": proposal_id,
        "claim_id": claim_id,
        "source_id": source_id,
        "evidence_argument": evidence,
        "category": category,
        "source_book": "William Lane Craig, Reasonable Faith: Christian Truth and Apologetics",
        "suggested_weight_0_5": weight,
        "EC_MI5": "Roughly even chance",
        "PC_MI5": "",
        "PT_MI5": "",
        "CT_MI5": "Likely / probable",
        "MT_MI5": "",
        "IS_MI5": "",
        "MS_MI5": "",
        "HC_MI5": "",
        "N_MI5": "Unlikely",
        "notes": "First-pass batch draft from SRC0018-PKT-002/SRC0018-PKT-003/SRC0018-PKT-004; human review required.",
        "suggestion_rationale": rationale,
        "uncertainty_notes": "Introductory methodological claim; do not treat as later chapter evidence without separate extraction.",
        "review_status": "proposed",
    }


def _write_csv(path: Path, import_type: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[import_type])
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[import_type]})


def _run_validation_and_cleaning(
    project: Path,
    config_path: str | Path,
    files: dict[str, Path],
    cleaned_dir: Path,
    logs_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], list[dict[str, Any]]]:
    validation = {}
    clean = {}
    final_files = {}
    commands = []
    for import_type, path in files.items():
        result = run_cli_command(["validate-import", "--type", import_type, "--file", str(path)], project_dir=project, config_path=config_path)
        commands.append(_command_summary(result, logs_dir, f"validate_{import_type}"))
        validation[import_type] = {"status": "pass" if result.return_code == 0 else "fail", "return_code": result.return_code, "file": str(path)}
        final_files[import_type] = path
        if result.return_code != 0:
            cleaned_path = cleaned_dir / f"{path.stem}_cleaned.csv"
            clean_result = run_cli_command(["clean-import", "--type", import_type, "--file", str(path), "--output", str(cleaned_path)], project_dir=project, config_path=config_path)
            commands.append(_command_summary(clean_result, logs_dir, f"clean_{import_type}"))
            clean[import_type] = {"status": "pass" if clean_result.return_code == 0 else "fail", "return_code": clean_result.return_code, "file": str(cleaned_path)}
            if clean_result.return_code == 0:
                cleaned_validate = run_cli_command(["validate-import", "--type", import_type, "--file", str(cleaned_path)], project_dir=project, config_path=config_path)
                commands.append(_command_summary(cleaned_validate, logs_dir, f"validate_cleaned_{import_type}"))
                clean[import_type]["validation_status"] = "pass" if cleaned_validate.return_code == 0 else "fail"
                clean[import_type]["validation_return_code"] = cleaned_validate.return_code
                if cleaned_validate.return_code == 0:
                    final_files[import_type] = cleaned_path
                    validation[import_type] = {"status": "pass", "return_code": 0, "file": str(cleaned_path), "original_failed": True}
        else:
            clean[import_type] = {"status": "not_needed", "file": ""}
    return validation, clean, final_files, commands


def _run_append_dry_runs(project: Path, config_path: str | Path, final_files: dict[str, Path], logs_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dry_run = {}
    commands = []
    for import_type, path in final_files.items():
        result = run_cli_command(["append-import", "--type", import_type, "--file", str(path), "--dry-run"], project_dir=project, config_path=config_path)
        commands.append(_command_summary(result, logs_dir, f"append_dry_run_{import_type}"))
        dry_run[import_type] = {"status": "pass" if result.return_code == 0 else "fail", "return_code": result.return_code, "file": str(path)}
    return dry_run, commands


def _command_summary(result: CliResult | dict[str, Any], logs_dir: Path | None = None, label: str | None = None) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    log_path = ""
    if logs_dir and label:
        log_path = str(logs_dir / f"{label}.log")
        Path(log_path).write_text(
            "\n".join(["$ " + " ".join(result.command), "", result.stdout, result.stderr]),
            encoding="utf-8",
        )
    return {
        "command": " ".join(result.command),
        "return_code": result.return_code,
        "risk": result.policy.risk.value,
        "stdout_preview": result.stdout[:1000],
        "stderr_preview": result.stderr[:1000],
        "log_path": log_path,
    }


def _overall_status(validation: dict[str, Any], extraction_qa: dict[str, Any], dry_run: dict[str, Any]) -> str:
    if not all(item.get("status") == "pass" for item in validation.values()):
        return "failed"
    if extraction_qa.get("status") not in {"pass", "needs_cleanup"}:
        return "failed"
    if not all(item.get("status") == "pass" for item in dry_run.values()):
        return "failed"
    return "passed"


def _base_report(
    project: Path,
    source_id: str,
    config: dict[str, Any],
    batch_name: str,
    packet_ids: list[str],
    packet_files: dict[str, Path],
    output_files: dict[str, Any],
) -> dict[str, Any]:
    source = _source_row(project, config, source_id)
    source_title = _display_source_title(source)
    return {
        "title": "Packet Batch Draft Report",
        "flow": "packet-batch-draft",
        "status": "failed",
        "source_id": source_id,
        "source_title": source_title,
        "batch_name": batch_name,
        "packet_ids": packet_ids,
        "packet_files": [str(packet_files[packet_id]) for packet_id in packet_ids if packet_id in packet_files],
        "output_files": {
            "extracted_claims": str(output_files.get("manual", {}).get("extracted_claims", "")),
            "criteria_matrix": str(output_files.get("manual", {}).get("criteria_matrix", "")),
            "proposed_updates": str(output_files.get("manual", {}).get("proposed_updates", "")),
            "zip": str(output_files.get("zip", "")),
        },
        "row_counts": {"extracted_claims": 0, "criteria_matrix": 0, "proposed_updates": 0},
        "next_id_summary": {},
        "scope": {
            "included": [
                "Craig's definition of apologetics",
                "why Craig thinks apologetics matters",
                "apologetics shaping culture",
                "apologetics strengthening believers",
                "apologetics evangelizing unbelievers",
                "offensive/positive and defensive/negative apologetics if present in selected packets",
                "scope-control claims about what the book is trying to do",
            ],
            "excluded": [
                "later existence-of-God arguments",
                "miracles",
                "resurrection",
                "historical Jesus",
                "later chapter claims",
                "claims from other sources",
                "anything not grounded in SRC0018-PKT-002 through SRC0018-PKT-004",
            ],
        },
        "claims_intentionally_excluded": [
            "Detailed existence-of-God arguments are deferred to later packet batches.",
            "Miracle, resurrection, and historical-Jesus claims are deferred to later packet batches.",
            "Preface references to later chapters are treated only as scope-control, not extracted as full arguments.",
        ],
        "checks": {
            "packet_integrity": {},
            "shape_diagnosis": {},
            "clean_import": {},
            "validate_import": {},
            "extraction_qa": {},
            "append_import_dry_run": {},
        },
        "mutated_queues": False,
        "mutated_workbook": False,
        "committed": False,
        "pushed": False,
        "human_review_required": True,
        "blockers": [],
        "warnings": [],
        "command_invocation": _command_invocation(source_id, batch_name, packet_ids),
        "next_safe_human_commands": [
            f"sed -n '1,80p' {output_files.get('manual', {}).get('extracted_claims', '')}",
            f"python -m belief_dashboard.cli validate-import --type extracted_claims --file {output_files.get('manual', {}).get('extracted_claims', '')}",
            f"python -m belief_dashboard.cli validate-import --type criteria_matrix --file {output_files.get('manual', {}).get('criteria_matrix', '')}",
            f"python -m belief_dashboard.cli validate-import --type proposed_updates --file {output_files.get('manual', {}).get('proposed_updates', '')}",
            "After human review only: run native append-import manually with --dry-run first, then real append only if approved.",
        ],
        "commands_run": [],
    }


def _source_row(project: Path, config: dict[str, Any], source_id: str) -> dict[str, str]:
    for row in read_queue(project, config, "source_dossiers"):
        if row.get("source_id") == source_id:
            return row
    return {}


def _display_source_title(row: dict[str, str]) -> str:
    title = row.get("title", "Reasonable Faith: Christian Truth and Apologetics")
    author = row.get("author_or_speaker", "William Lane Craig")
    return f"{author}, {title}" if author and author not in title else title


def _command_invocation(source_id: str, batch_name: str, packet_ids: list[str]) -> str:
    packets = " \\\n  ".join(f"--packet-id {packet_id}" for packet_id in packet_ids)
    return "\n".join(
        [
            "python -m belief_dashboard_agentflows.cli packet-batch-draft \\",
            f"  --source-id {source_id} \\",
            f"  --batch-name \"{batch_name}\" \\",
            f"  {packets}",
        ]
    )


def _write_reports(report: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "packet_batch_draft_report.md"
    json_path = report_dir / "packet_batch_draft_report.json"
    markdown_path.write_text(render_packet_batch_draft_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _write_zip(report: dict[str, Any], output_files: dict[str, Any], logs_dir: Path, markdown_path: Path, json_path: Path) -> Path:
    zip_path = output_files["zip"]
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in output_files["generated"].values():
            archive.write(path, arcname=f"generated/{path.name}")
        archive.write(markdown_path, arcname=markdown_path.name)
        archive.write(json_path, arcname=json_path.name)
        for log_path in sorted(logs_dir.glob("*.log")):
            archive.write(log_path, arcname=f"logs/{log_path.name}")
        references = zip_path.parent / "report_references.txt"
        references.write_text(
            "\n".join(
                [
                    "Packet files are referenced, not embedded:",
                    *report.get("packet_files", []),
                    "",
                    "Extraction QA, validation, and dry-run snippets are summarized in packet_batch_draft_report.md/json.",
                ]
            ),
            encoding="utf-8",
        )
        archive.write(references, arcname="report_references.txt")
    return zip_path


def _failed_check_messages(checks: dict[str, dict[str, Any]]) -> list[str]:
    messages = []
    for packet_id, check in checks.items():
        if check.get("status") != "pass":
            messages.append(f"{packet_id}: {', '.join(check.get('messages', []))}")
    return messages


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
