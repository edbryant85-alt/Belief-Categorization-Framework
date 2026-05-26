from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.command_guides import next_safe_commands, quote_path
from belief_dashboard.manual_imports import queue_summary
from belief_dashboard.operator_preflight import PREFLIGHT_MODES, build_operator_preflight
from belief_dashboard.product_readiness import build_product_readiness
from belief_dashboard.queues import validate_queues
from belief_dashboard.utils import resolve_project_path, timestamp_for_filename, timestamp_iso
from belief_dashboard.workbook import inspect_workbook


DOCTOR_MODES = PREFLIGHT_MODES
SEVERITIES = ["blocker", "error", "warning", "info"]
DOCUMENTATION = {
    "readme": "README.md",
    "workflow": "docs/OPERATOR_WORKFLOW.md",
    "safety": "docs/SAFETY_MODEL.md",
    "troubleshooting": "docs/TROUBLESHOOTING.md",
}

EXPLANATION_GUIDES: dict[str, dict[str, list[str]]] = {
    "main_workbook_missing": {
        "likely_causes": [
            "The workbook was not copied into data/workbooks/.",
            "The workbook filename does not match config.yaml.",
            "The command is being run from the wrong working directory.",
            "The configured workbook path points to the wrong location.",
        ],
        "safest_next_steps": [
            "Confirm you are in belief-dashboard-tool/.",
            "Confirm the workbook file exists at the configured path.",
            "If missing, copy the real workbook into data/workbooks/.",
            "Run python -m belief_dashboard.cli inspect-workbook.",
            "Run python -m belief_dashboard.cli doctor.",
        ],
        "safe_repair_commands": [
            "python -m belief_dashboard.cli inspect-workbook",
            "python -m belief_dashboard.cli product-readiness",
        ],
        "verification_commands": ["python -m belief_dashboard.cli doctor"],
        "what_not_to_do": [
            "Do not create a blank workbook as a substitute.",
            "Do not run export or promotion commands until inspection passes.",
            "Do not edit generated output workbooks manually and promote them without verification.",
        ],
        "documentation_references": [DOCUMENTATION["readme"], DOCUMENTATION["workflow"], DOCUMENTATION["safety"]],
    },
    "queues_missing": {
        "likely_causes": [
            "The queue directory has not been initialized yet.",
            "Queue CSV files were moved, deleted, or not copied with the project.",
            "The queues.base_dir setting points to a different location.",
            "The command is being run from the wrong working directory.",
        ],
        "safest_next_steps": [
            "Confirm you are in belief-dashboard-tool/.",
            "Run python -m belief_dashboard.cli init-queues to create missing queue templates.",
            "Run python -m belief_dashboard.cli validate-queues.",
            "Run python -m belief_dashboard.cli doctor.",
        ],
        "safe_repair_commands": [
            "python -m belief_dashboard.cli init-queues",
            "python -m belief_dashboard.cli validate-queues",
        ],
        "verification_commands": ["python -m belief_dashboard.cli validate-queues", "python -m belief_dashboard.cli doctor"],
        "what_not_to_do": [
            "Do not manually invent queue headers if init-queues can create them.",
            "Do not append imports before queues validate.",
            "Do not use --force unless you intentionally want to overwrite queue templates.",
        ],
        "documentation_references": [DOCUMENTATION["readme"], DOCUMENTATION["workflow"], DOCUMENTATION["safety"]],
    },
    "queue_validation_failed": {
        "likely_causes": [
            "A queue CSV header is missing, renamed, or out of order.",
            "A row contains an invalid MI5 label.",
            "A review status or claim type is not one of the allowed values.",
            "A score or weight is outside the 0 to 5 range.",
        ],
        "safest_next_steps": [
            "Run python -m belief_dashboard.cli validate-queues.",
            "Open the latest report under reports/queue_validation/.",
            "Fix malformed headers, invalid labels, invalid statuses, or invalid score ranges.",
            "Rerun python -m belief_dashboard.cli validate-queues.",
            "Rerun python -m belief_dashboard.cli doctor.",
        ],
        "safe_repair_commands": ["python -m belief_dashboard.cli validate-queues"],
        "verification_commands": ["python -m belief_dashboard.cli validate-queues", "python -m belief_dashboard.cli doctor"],
        "what_not_to_do": [
            "Do not export approved updates while queues fail validation.",
            "Do not append imports until queue validation passes.",
            "Do not reorder headers by hand unless you are matching the documented schema exactly.",
        ],
        "documentation_references": [DOCUMENTATION["workflow"], "reports/queue_validation/", DOCUMENTATION["troubleshooting"]],
    },
    "no_output_workbook": {
        "likely_causes": [
            "No approved export has been run yet.",
            "Only dry-run export checks have been run.",
            "Output workbooks were deleted or moved.",
            "The configured outputs directory points to a different location.",
        ],
        "safest_next_steps": [
            "Run python -m belief_dashboard.cli preview-workbook-export.",
            "Run python -m belief_dashboard.cli apply-approved-to-workbook --dry-run.",
            "If the dry run passes and you intend to create an output copy, run python -m belief_dashboard.cli apply-approved-to-workbook.",
            "Run python -m belief_dashboard.cli latest-output-workbook.",
            "Run python -m belief_dashboard.cli doctor --mode before-verification.",
        ],
        "safe_repair_commands": [
            "python -m belief_dashboard.cli preview-workbook-export",
            "python -m belief_dashboard.cli apply-approved-to-workbook --dry-run",
            "python -m belief_dashboard.cli apply-approved-to-workbook",
        ],
        "verification_commands": [
            "python -m belief_dashboard.cli latest-output-workbook",
            "python -m belief_dashboard.cli doctor --mode before-verification",
        ],
        "what_not_to_do": [
            "Do not run verification without an output workbook.",
            "Do not promote the main workbook directly.",
            "Do not manually copy files into data/outputs/ and treat them as verified.",
        ],
        "documentation_references": [DOCUMENTATION["workflow"], DOCUMENTATION["safety"], DOCUMENTATION["troubleshooting"]],
    },
    "no_passing_verification": {
        "likely_causes": [
            "The output workbook has not been verified yet.",
            "The latest verification report failed or warned.",
            "The verification report does not point to the selected output workbook.",
            "The verified output workbook was moved or modified after verification.",
        ],
        "safest_next_steps": [
            "Run python -m belief_dashboard.cli find-verified-output.",
            "If none exist, run python -m belief_dashboard.cli latest-output-workbook.",
            "Verify the output workbook with python -m belief_dashboard.cli verify-workbook-export --workbook \"data/outputs/output_file.xlsx\".",
            "Rerun python -m belief_dashboard.cli doctor --mode before-promotion.",
        ],
        "safe_repair_commands": [
            "python -m belief_dashboard.cli find-verified-output",
            "python -m belief_dashboard.cli latest-output-workbook",
            'python -m belief_dashboard.cli verify-workbook-export --workbook "data/outputs/output_file.xlsx"',
        ],
        "verification_commands": [
            "python -m belief_dashboard.cli find-verified-output",
            "python -m belief_dashboard.cli doctor --mode before-promotion",
        ],
        "what_not_to_do": [
            "Do not promote an output workbook until verification passes.",
            "Do not bypass verification by copying output files manually over the main workbook.",
            "Do not use a verification report for a different output workbook.",
        ],
        "documentation_references": [DOCUMENTATION["workflow"], DOCUMENTATION["safety"], DOCUMENTATION["troubleshooting"]],
    },
    "no_promoted_archive": {
        "likely_causes": [
            "No workbook promotion has happened yet.",
            "Promoted archives were moved or deleted.",
            "The promoted archive directory setting points to a different location.",
            "The operator is trying to roll back before any promoted baseline exists.",
        ],
        "safest_next_steps": [
            "Run python -m belief_dashboard.cli list-promoted-archives.",
            "Run python -m belief_dashboard.cli promotion-history.",
            "If no archive exists, use an external backup process rather than this rollback command.",
            "Rerun python -m belief_dashboard.cli doctor --mode before-rollback.",
        ],
        "safe_repair_commands": [
            "python -m belief_dashboard.cli list-promoted-archives",
            "python -m belief_dashboard.cli promotion-history",
        ],
        "verification_commands": [
            "python -m belief_dashboard.cli list-promoted-archives",
            "python -m belief_dashboard.cli doctor --mode before-rollback",
        ],
        "what_not_to_do": [
            "Do not attempt rollback without an archive.",
            "Do not manually replace the main workbook unless you have an external backup and understand the risk.",
            "Do not assume data/backups/ contains promoted archives unless list-promoted-archives finds them.",
        ],
        "documentation_references": [DOCUMENTATION["workflow"], DOCUMENTATION["safety"], DOCUMENTATION["troubleshooting"]],
    },
}

FINDING_ID_ALIASES = {
    "missing_main_workbook": "main_workbook_missing",
    "missing_queues": "queues_missing",
    "queue_validation_failure": "queue_validation_failed",
    "no_verified_output": "no_verified_output_general",
}


@dataclass(frozen=True)
class DoctorFinding:
    id: str
    severity: str
    title: str
    plain_language_explanation: str
    why_it_matters: str
    safe_repair_command: str
    documentation_reference: str
    related_file_or_directory: str
    can_auto_fix: bool = False


def build_doctor_report(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    mode: str = "general",
    verbose: bool = False,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    if mode not in DOCTOR_MODES:
        raise ValueError(f"Unknown doctor mode: {mode}")

    base_path = Path(base_dir)
    timestamp = timestamp_iso(checked_at)
    findings: list[DoctorFinding] = []
    doctor_config = config.get("doctor", {})

    workbook_path = resolve_project_path(config["workbook"]["default_path"], base_dir=base_path)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_path)

    inspection: dict[str, Any] | None = None
    queue_validation: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    preflight: dict[str, Any] | None = None
    readiness: dict[str, Any] | None = None

    if doctor_config.get("include_workbook_inspection", True):
        inspection = _without_user_warnings(inspect_workbook, workbook_path, config)
        findings.extend(_workbook_findings(inspection, mode))

    if doctor_config.get("include_queue_validation", True):
        queue_validation = validate_queues(queue_dir, config)
        findings.extend(_queue_findings(queue_validation, mode))

    if doctor_config.get("include_queue_summary", True):
        try:
            summary = queue_summary(queue_dir, config)
            findings.extend(_queue_summary_findings(summary, mode))
        except FileNotFoundError:
            summary = None

    if doctor_config.get("include_operator_preflight", True):
        preflight = _without_user_warnings(build_operator_preflight, config, base_path, mode=mode)
        findings.extend(_mode_specific_findings(preflight, mode, config))

    if doctor_config.get("include_product_readiness", True):
        try:
            readiness = _without_user_warnings(build_product_readiness, config, base_path)
            findings.extend(_product_readiness_findings(readiness))
        except Exception as exc:
            findings.append(
                DoctorFinding(
                    id="product_readiness_unavailable",
                    severity="warning",
                    title="Product readiness could not complete.",
                    plain_language_explanation=f"The doctor could not collect the product-readiness summary: {exc}",
                    why_it_matters="Product readiness is a broad setup check. Doctor can still inspect the core workbook, queues, and artifacts.",
                    safe_repair_command="python -m belief_dashboard.cli product-readiness",
                    documentation_reference=DOCUMENTATION["workflow"],
                    related_file_or_directory=str(base_path),
                )
            )

    unique_findings = _dedupe_findings(findings)
    counts = _severity_counts(unique_findings)
    status = _overall_status(counts)
    next_commands = _next_safest_commands(config, base_path, mode, unique_findings)
    docs = _documentation_references(unique_findings)
    if not docs:
        docs = [DOCUMENTATION["readme"], DOCUMENTATION["workflow"]]

    return {
        "operation": "doctor",
        "timestamp": timestamp,
        "mode": mode,
        "verbose": verbose,
        "overall_status": status,
        "summary_counts_by_severity": counts,
        "blockers": counts["blocker"],
        "errors": counts["error"],
        "warnings": counts["warning"],
        "info": counts["info"],
        "findings": [asdict(finding) for finding in unique_findings],
        "all_findings_count": len(unique_findings),
        "next_safest_commands": next_commands,
        "documentation_references": docs,
        "context": {
            "workbook": inspection,
            "queue_validation": queue_validation,
            "queue_summary": summary,
            "operator_preflight": _preflight_summary(preflight),
            "product_readiness": _readiness_summary(readiness),
        },
        "no_high_stakes_command_executed": True,
    }


def render_doctor_report(result: dict[str, Any]) -> str:
    lines = [
        f"Doctor status: {result['overall_status']}",
        f"Mode: {result['mode']}",
        "",
        f"Blockers: {result['blockers']}",
        f"Errors: {result['errors']}",
        f"Warnings: {result['warnings']}",
        "",
        "Findings:",
    ]
    findings = [
        finding
        for finding in result.get("findings", [])
        if result.get("verbose") or finding.get("severity") != "info"
    ]
    if not findings:
        lines.append("- None")
    for finding in findings[:8]:
        lines.extend(
            [
                f"[{finding['severity'].upper()}] {finding['title']}",
                f"Explanation: {finding['plain_language_explanation']}",
                f"Why it matters: {finding['why_it_matters']}",
                f"Safe next command: {finding['safe_repair_command']}",
                f"Documentation: {finding['documentation_reference']}",
                "",
            ]
        )
    if len(findings) > 8:
        lines.append(f"...and {len(findings) - 8} more findings. Use --verbose or --format json for details.")
        lines.append("")
    lines.append("Next safest commands:")
    commands = result.get("next_safest_commands", [])
    if not commands:
        lines.append("None")
    for index, command in enumerate(commands, start=1):
        lines.append(f"{index}. {command}")
    lines.extend(["", "Relevant documentation files:"])
    for reference in result.get("documentation_references", []):
        lines.append(f"- {reference}")
    lines.append("")
    lines.append("No high-stakes command was executed.")
    return "\n".join(lines)


def write_doctor_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    mode = str(result["mode"]).upper().replace("-", "_")
    markdown_path = reports_path / f"doctor_{mode}_{stamp}.md"
    json_path = reports_path / f"doctor_{mode}_{stamp}.json"
    markdown_path.write_text(_render_markdown_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def build_doctor_explanation(
    config: dict[str, Any],
    base_dir: str | Path,
    finding_id: str,
    *,
    mode: str = "general",
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    report = build_doctor_report(config, base_dir, mode=mode, verbose=True, checked_at=checked_at)
    requested = finding_id
    normalized = _normalize_finding_id(finding_id)
    detected_ids = [finding["id"] for finding in report.get("findings", [])]
    finding = next(
        (item for item in report.get("findings", []) if _normalize_finding_id(item["id"]) == normalized),
        None,
    )
    if finding is None:
        return {
            "operation": "doctor_explain",
            "timestamp": report["timestamp"],
            "requested_finding_id": requested,
            "finding_id": "",
            "mode": mode,
            "status": "not_detected",
            "message": f"Finding '{requested}' was not currently detected in mode '{mode}'.",
            "currently_detected_finding_ids": detected_ids,
            "suggested_command": f"python -m belief_dashboard.cli doctor --mode {mode}",
            "warnings": [
                "The requested finding may be fixed already, may only appear in another mode, or may use a different finding ID."
            ],
            "errors": [],
            "no_high_stakes_command_executed": True,
        }

    guide = EXPLANATION_GUIDES.get(finding["id"], _default_explanation_guide(finding))
    docs = _dedupe_strings([*guide["documentation_references"], *_split_documentation(finding["documentation_reference"])])
    return {
        "operation": "doctor_explain",
        "timestamp": report["timestamp"],
        "requested_finding_id": requested,
        "finding_id": finding["id"],
        "mode": mode,
        "severity": finding["severity"],
        "title": finding["title"],
        "plain_language_explanation": finding["plain_language_explanation"],
        "why_it_matters": finding["why_it_matters"],
        "likely_causes": guide["likely_causes"],
        "safest_next_steps": guide["safest_next_steps"],
        "safe_repair_commands": guide["safe_repair_commands"],
        "verification_commands": guide["verification_commands"],
        "documentation_references": docs,
        "what_not_to_do": guide["what_not_to_do"],
        "related_files_or_directories": [finding["related_file_or_directory"]] if finding.get("related_file_or_directory") else [],
        "can_auto_fix": finding["can_auto_fix"],
        "auto_fix_available": False,
        "status": "detected",
        "warnings": [
            "This explanation recommends commands but does not run them.",
            "No auto-fix is implemented for this finding.",
        ],
        "errors": [],
        "currently_detected_finding_ids": detected_ids,
        "suggested_command": f"python -m belief_dashboard.cli doctor --mode {mode}",
        "no_high_stakes_command_executed": True,
    }


def render_doctor_explanation(explanation: dict[str, Any]) -> str:
    if explanation.get("status") != "detected":
        lines = [
            f"Finding not currently detected: {explanation.get('requested_finding_id', '')}",
            f"Mode checked: {explanation.get('mode', '')}",
            "",
            explanation.get("message", ""),
            "",
            "Currently detected finding IDs:",
        ]
        detected = explanation.get("currently_detected_finding_ids", [])
        lines.extend(_bullet_list(detected))
        lines.extend(["", "Suggested command:", explanation.get("suggested_command", ""), "", "No high-stakes command was executed."])
        return "\n".join(lines)

    lines = [
        f"Finding: {explanation['finding_id']}",
        f"Severity: {explanation['severity']}",
        f"Mode: {explanation['mode']}",
        "",
        "What this means:",
        explanation["plain_language_explanation"],
        "",
        "Why it matters:",
        explanation["why_it_matters"],
        "",
        "Likely causes:",
    ]
    for cause in explanation.get("likely_causes", []):
        lines.append(f"- {cause}")
    lines.extend(["", "Safest next steps:"])
    for index, step in enumerate(explanation.get("safest_next_steps", []), start=1):
        lines.append(f"{index}. {step}")
    lines.extend(["", "Safe repair commands:"])
    lines.extend(_bullet_list(explanation.get("safe_repair_commands", [])))
    lines.extend(["", "Verification commands:"])
    lines.extend(_bullet_list(explanation.get("verification_commands", [])))
    lines.extend(["", "Documentation:"])
    lines.extend(_bullet_list(explanation.get("documentation_references", [])))
    lines.extend(["", "Do not:"])
    lines.extend(_bullet_list(explanation.get("what_not_to_do", [])))
    lines.extend(["", "No high-stakes command was executed."])
    return "\n".join(lines)


def write_doctor_explanation_reports(
    explanation: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    finding_id = str(explanation.get("finding_id") or explanation.get("requested_finding_id") or "UNKNOWN")
    filename_id = _filename_finding_id(finding_id)
    markdown_path = reports_path / f"doctor_explain_{filename_id}_{stamp}.md"
    json_path = reports_path / f"doctor_explain_{filename_id}_{stamp}.json"
    markdown_path.write_text(_render_explanation_markdown(explanation), encoding="utf-8")
    json_path.write_text(json.dumps(explanation, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _workbook_findings(inspection: dict[str, Any], mode: str) -> list[DoctorFinding]:
    path = inspection["workbook_path"]
    if not inspection["workbook_file_exists"]:
        return [
            DoctorFinding(
                id="main_workbook_missing",
                severity="blocker",
                title="Main workbook is missing.",
                plain_language_explanation="The tool cannot inspect, export, verify, or promote workbook changes because the main workbook file is missing.",
                why_it_matters="Every workbook workflow starts from the configured main workbook path.",
                safe_repair_command=f"Place the workbook at `{path}`, then run `python -m belief_dashboard.cli inspect-workbook`.",
                documentation_reference=f"{DOCUMENTATION['readme']} or {DOCUMENTATION['workflow']}",
                related_file_or_directory=path,
            )
        ]
    if inspection["overall_status"] == "fail":
        return [
            DoctorFinding(
                id="workbook_inspection_failed",
                severity="blocker" if mode == "before-export" else "error",
                title="Workbook inspection is failing.",
                plain_language_explanation="The workbook exists, but its sheets or Evidence Log columns do not match the configured structure.",
                why_it_matters="Exports depend on predictable sheet names, header rows, and workbook columns.",
                safe_repair_command="python -m belief_dashboard.cli inspect-workbook",
                documentation_reference=DOCUMENTATION["workflow"],
                related_file_or_directory=path,
            )
        ]
    return []


def _queue_findings(validation: dict[str, Any], mode: str) -> list[DoctorFinding]:
    missing = [
        file_result["path"]
        for file_result in validation.get("required_files", {}).values()
        if not file_result.get("exists")
    ]
    if missing:
        return [
            DoctorFinding(
                id="queues_missing",
                severity="blocker",
                title="Required queue files are missing.",
                plain_language_explanation="The queue folder is incomplete, so the tool cannot safely track source dossiers, claims, proposals, approvals, and review history.",
                why_it_matters="Later commands rely on these CSV files having known names and headers.",
                safe_repair_command="python -m belief_dashboard.cli init-queues && python -m belief_dashboard.cli validate-queues",
                documentation_reference=f"{DOCUMENTATION['readme']} or {DOCUMENTATION['workflow']}",
                related_file_or_directory=validation["queue_base_dir"],
            )
        ]
    if validation["overall_status"] == "fail":
        return [
            DoctorFinding(
                id="queue_validation_failed",
                severity="error",
                title="Queue validation is failing.",
                plain_language_explanation="One or more queue CSV files exists but does not match the expected headers or allowed values.",
                why_it_matters="Invalid queue rows can block export planning or cause reviewed updates to be interpreted incorrectly.",
                safe_repair_command="python -m belief_dashboard.cli validate-queues",
                documentation_reference="reports/queue_validation/ and docs/OPERATOR_WORKFLOW.md",
                related_file_or_directory=validation["queue_base_dir"],
            )
        ]
    if validation["overall_status"] == "warning":
        return [
            DoctorFinding(
                id="queue_validation_warnings",
                severity="warning",
                title="Queue validation has warnings.",
                plain_language_explanation="The queue files are usable, but validation found conditions worth reviewing.",
                why_it_matters="Warnings can become blockers later if they affect export or review decisions.",
                safe_repair_command="python -m belief_dashboard.cli validate-queues",
                documentation_reference="reports/queue_validation/",
                related_file_or_directory=validation["queue_base_dir"],
            )
        ]
    return []


def _queue_summary_findings(summary: dict[str, Any], mode: str) -> list[DoctorFinding]:
    approved = summary.get("approved_updates_export_tracking", {})
    not_exported = int(approved.get("not_exported", 0) or 0)
    if not_exported <= 0:
        return []
    severity = "warning" if mode == "before-export" else "info"
    return [
        DoctorFinding(
            id="approved_rows_not_exported",
            severity=severity,
            title="Approved rows are waiting for export.",
            plain_language_explanation=f"There are {not_exported} approved update row(s) that have not been marked exported.",
            why_it_matters="These approved rows may be ready to preview and write to a timestamped output workbook copy.",
            safe_repair_command="python -m belief_dashboard.cli preview-workbook-export && python -m belief_dashboard.cli apply-approved-to-workbook --dry-run",
            documentation_reference=DOCUMENTATION["workflow"],
            related_file_or_directory=summary["queue_dir"],
        )
    ]


def _mode_specific_findings(preflight: dict[str, Any], mode: str, config: dict[str, Any]) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    latest = preflight.get("latest", {})
    if mode == "general":
        if not latest.get("export_verification", {}).get("exists"):
            findings.append(
                DoctorFinding(
                    id="no_verified_output_general",
                    severity="warning",
                    title="No verified output workbook found.",
                    plain_language_explanation="The doctor did not find a passing verification report for an output workbook.",
                    why_it_matters="Promotion requires successful export verification.",
                    safe_repair_command="python -m belief_dashboard.cli find-verified-output",
                    documentation_reference=DOCUMENTATION["workflow"],
                    related_file_or_directory=str(latest.get("export_verification", {}).get("path", "")),
                )
            )
        return findings
    if mode == "before-export":
        for error in preflight.get("errors", []):
            if "Workbook inspection failed" in error or "Queue validation failed" in error:
                findings.append(
                    DoctorFinding(
                        id="before_export_not_ready",
                        severity="blocker",
                        title="Export preflight is not ready.",
                        plain_language_explanation="The workbook or queues are not passing the read-only checks required before export.",
                        why_it_matters="Export should only run after workbook inspection and queue validation pass.",
                        safe_repair_command="python -m belief_dashboard.cli inspect-workbook && python -m belief_dashboard.cli validate-queues",
                        documentation_reference=DOCUMENTATION["workflow"],
                        related_file_or_directory=str(preflight.get("workbook", {}).get("path", "")),
                    )
                )
                break
    if mode == "before-verification" and not latest.get("output_workbook", {}).get("exists"):
        findings.append(
            DoctorFinding(
                id="no_output_workbook",
                severity="blocker",
                title="No output workbook is available to verify.",
                plain_language_explanation="Verification needs a timestamped output workbook, but none was found under the configured outputs folder.",
                why_it_matters="Verification compares an output workbook against approved queue rows before promotion is allowed.",
                safe_repair_command="python -m belief_dashboard.cli latest-output-workbook",
                documentation_reference=DOCUMENTATION["workflow"],
                related_file_or_directory=str(latest.get("output_workbook", {}).get("path", "")),
            )
        )
    if mode == "before-promotion" and not preflight.get("verified_outputs", {}).get("rows", []):
        findings.append(
            DoctorFinding(
                id="no_passing_verification",
                severity="blocker",
                title="No passing verification report is available for promotion.",
                plain_language_explanation="Promotion is blocked because the doctor did not find an output workbook with a passing verification report.",
                why_it_matters="The guarded promotion command requires proof that the output workbook was verified successfully.",
                safe_repair_command='python -m belief_dashboard.cli find-verified-output or python -m belief_dashboard.cli verify-workbook-export --workbook "data/outputs/output_file.xlsx"',
                documentation_reference=DOCUMENTATION["workflow"],
                related_file_or_directory=str(latest.get("export_verification", {}).get("path", "")),
            )
        )
    if mode == "before-rollback" and not latest.get("promoted_archive", {}).get("exists"):
        findings.append(
            DoctorFinding(
                id="no_promoted_archive",
                severity="blocker",
                title="No promoted archive is available for rollback.",
                plain_language_explanation="Rollback is not available because no promoted archive exists yet.",
                why_it_matters="Rollback restores a previous promoted archive, so there must be an archive to restore.",
                safe_repair_command="python -m belief_dashboard.cli list-promoted-archives",
                documentation_reference=DOCUMENTATION["workflow"],
                related_file_or_directory=str(latest.get("promoted_archive", {}).get("path", "")),
            )
        )
    return findings


def _product_readiness_findings(readiness: dict[str, Any]) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    for warning in readiness.get("warnings", []):
        if "README" in warning:
            findings.append(
                DoctorFinding(
                    id="documentation_coverage_warning",
                    severity="warning",
                    title="Documentation may not mention all expected commands.",
                    plain_language_explanation=warning,
                    why_it_matters="Operators need nearby documentation when troubleshooting command-line workflows.",
                    safe_repair_command="python -m belief_dashboard.cli product-readiness",
                    documentation_reference=DOCUMENTATION["readme"],
                    related_file_or_directory=DOCUMENTATION["readme"],
                )
            )
    return findings


def _next_safest_commands(
    config: dict[str, Any],
    base_dir: Path,
    mode: str,
    findings: list[DoctorFinding],
) -> list[str]:
    blocker_ids = {finding.id for finding in findings if finding.severity in {"blocker", "error"}}
    if "main_workbook_missing" in blocker_ids:
        return ["python -m belief_dashboard.cli inspect-workbook"]
    if "queues_missing" in blocker_ids:
        return ["python -m belief_dashboard.cli init-queues", "python -m belief_dashboard.cli validate-queues"]
    if "queue_validation_failed" in blocker_ids:
        return ["python -m belief_dashboard.cli validate-queues"]
    if mode == "before-verification":
        latest = _without_user_warnings(build_operator_preflight, config, base_dir, mode=mode)["latest"]["output_workbook"]
        if latest.get("path"):
            return [f"python -m belief_dashboard.cli verify-workbook-export --workbook {quote_path(latest['path'], config)}"]
        return ["python -m belief_dashboard.cli latest-output-workbook"]
    if mode == "before-promotion":
        return ["python -m belief_dashboard.cli find-verified-output"]
    if mode == "before-rollback":
        return ["python -m belief_dashboard.cli list-promoted-archives"]
    if mode == "before-export":
        return [
            "python -m belief_dashboard.cli preview-workbook-export",
            "python -m belief_dashboard.cli apply-approved-to-workbook --dry-run",
        ]
    guide = next_safe_commands(config, base_dir)
    return [step["command"] for step in guide.get("steps", [])[:3]]


def _dedupe_findings(findings: list[DoctorFinding]) -> list[DoctorFinding]:
    seen: set[str] = set()
    unique: list[DoctorFinding] = []
    for finding in sorted(findings, key=lambda item: (SEVERITIES.index(item.severity), item.id)):
        if finding.id in seen:
            continue
        seen.add(finding.id)
        unique.append(finding)
    return unique


def _normalize_finding_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return FINDING_ID_ALIASES.get(normalized, normalized)


def _filename_finding_id(value: str) -> str:
    return _normalize_finding_id(value).upper()


def _default_explanation_guide(finding: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "likely_causes": [
            "The current project state does not satisfy one of the expected workflow checks.",
            "A required file, report, or directory may be missing or in a different configured location.",
            "A previous workflow step may not have been run yet.",
        ],
        "safest_next_steps": [
            "Read the finding explanation and related path.",
            f"Run {finding['safe_repair_command']}.",
            "Rerun python -m belief_dashboard.cli doctor.",
        ],
        "safe_repair_commands": [finding["safe_repair_command"]],
        "verification_commands": ["python -m belief_dashboard.cli doctor"],
        "documentation_references": _split_documentation(finding["documentation_reference"]),
        "what_not_to_do": [
            "Do not run export, verification, promotion, or rollback commands unless the relevant preflight checks pass.",
            "Do not manually overwrite workbook or queue files to bypass the workflow.",
        ],
    }


def _split_documentation(value: str) -> list[str]:
    parts: list[str] = []
    for separator in [" or ", " and ", ","]:
        if separator in value:
            for item in value.split(separator):
                stripped = item.strip()
                if stripped:
                    parts.append(stripped)
            return parts
    return [value] if value else []


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _without_user_warnings(function: Any, *args: Any, **kwargs: Any) -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return function(*args, **kwargs)


def _severity_counts(findings: list[DoctorFinding]) -> dict[str, int]:
    return {severity: sum(1 for finding in findings if finding.severity == severity) for severity in SEVERITIES}


def _overall_status(counts: dict[str, int]) -> str:
    if counts["blocker"] or counts["error"]:
        return "fail"
    if counts["warning"]:
        return "warning"
    return "pass"


def _documentation_references(findings: list[DoctorFinding]) -> list[str]:
    references: list[str] = []
    for finding in findings:
        for item in str(finding.documentation_reference).split(" or "):
            reference = item.strip()
            if reference and reference not in references:
                references.append(reference)
    return references


def _preflight_summary(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if not preflight:
        return {}
    return {
        "overall_status": preflight.get("overall_status", ""),
        "warnings": preflight.get("warnings", []),
        "errors": preflight.get("errors", []),
        "recommended_next_commands": preflight.get("recommended_next_commands", []),
    }


def _readiness_summary(readiness: dict[str, Any] | None) -> dict[str, Any]:
    if not readiness:
        return {}
    return {
        "overall_status": readiness.get("overall_status", ""),
        "warnings": readiness.get("warnings", []),
        "errors": readiness.get("errors", []),
    }


def _render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# Doctor Report: {str(result['mode']).replace('-', ' ').title()}",
        "",
        f"- Timestamp: `{result['timestamp']}`",
        f"- Mode: `{result['mode']}`",
        f"- Overall status: `{result['overall_status']}`",
        f"- Blockers: `{result['blockers']}`",
        f"- Errors: `{result['errors']}`",
        f"- Warnings: `{result['warnings']}`",
        f"- Info: `{result['info']}`",
        "- No high-stakes command was executed: `True`",
        "",
        "## Findings",
    ]
    if not result.get("findings"):
        lines.append("- None")
    for finding in result.get("findings", []):
        lines.extend(
            [
                f"### [{finding['severity'].upper()}] {finding['title']}",
                "",
                f"- ID: `{finding['id']}`",
                f"- Explanation: {finding['plain_language_explanation']}",
                f"- Why it matters: {finding['why_it_matters']}",
                f"- Safe repair command: `{finding['safe_repair_command']}`",
                f"- Documentation: `{finding['documentation_reference']}`",
                f"- Related file or directory: `{finding['related_file_or_directory']}`",
                f"- Can auto-fix: `{finding['can_auto_fix']}`",
                "",
            ]
        )
    lines.extend(["## Safe Repair Commands", *_bullet_list(_finding_commands(result))])
    lines.extend(["", "## Next Safest Commands", *_bullet_list(result.get("next_safest_commands", []))])
    lines.extend(["", "## Documentation References", *_bullet_list(result.get("documentation_references", []))])
    lines.extend(["", "## Safety Note", "No high-stakes command was executed.", ""])
    return "\n".join(lines)


def _finding_commands(result: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for finding in result.get("findings", []):
        command = finding.get("safe_repair_command", "")
        if command and command not in commands:
            commands.append(command)
    return commands


def _render_explanation_markdown(explanation: dict[str, Any]) -> str:
    lines = [
        "# Doctor Explanation",
        "",
        f"- Timestamp: `{explanation['timestamp']}`",
        f"- Mode: `{explanation['mode']}`",
        f"- Finding ID: `{explanation.get('finding_id') or explanation.get('requested_finding_id', '')}`",
        f"- Status: `{explanation['status']}`",
        "- No high-stakes command was executed: `True`",
        "",
    ]
    if explanation.get("status") != "detected":
        lines.extend(
            [
                "## Message",
                explanation.get("message", ""),
                "",
                "## Currently Detected Finding IDs",
                *_bullet_list(explanation.get("currently_detected_finding_ids", [])),
                "",
                "## Suggested Command",
                f"- `{explanation.get('suggested_command', '')}`",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            f"- Severity: `{explanation['severity']}`",
            f"- Title: {explanation['title']}",
            "",
            "## Expanded Explanation",
            explanation["plain_language_explanation"],
            "",
            "## Why It Matters",
            explanation["why_it_matters"],
            "",
            "## Likely Causes",
            *_bullet_list(explanation.get("likely_causes", [])),
            "",
            "## Safest Next Steps",
        ]
    )
    for index, step in enumerate(explanation.get("safest_next_steps", []), start=1):
        lines.append(f"{index}. {step}")
    lines.extend(["", "## Safe Repair Commands", *_bullet_list(explanation.get("safe_repair_commands", []))])
    lines.extend(["", "## Verification Commands", *_bullet_list(explanation.get("verification_commands", []))])
    lines.extend(["", "## Documentation References", *_bullet_list(explanation.get("documentation_references", []))])
    lines.extend(["", "## What Not To Do", *_bullet_list(explanation.get("what_not_to_do", []))])
    lines.extend(["", "## Related Files Or Directories", *_bullet_list(explanation.get("related_files_or_directories", []))])
    lines.extend(["", "## Safety Note", "No high-stakes command was executed.", ""])
    return "\n".join(lines)


def _bullet_list(values: list[str]) -> list[str]:
    if not values:
        return ["- None"]
    return [f"- {value}" for value in values]
