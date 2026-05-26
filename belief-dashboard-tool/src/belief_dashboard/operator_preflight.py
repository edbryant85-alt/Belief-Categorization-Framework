from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.artifacts import find_verified_outputs, latest_artifact, list_artifact_categories
from belief_dashboard.command_guides import compose_promote_command, compose_rollback_command, next_safe_commands
from belief_dashboard.manual_imports import queue_summary
from belief_dashboard.queues import validate_queues
from belief_dashboard.utils import resolve_project_path, timestamp_for_filename, timestamp_iso
from belief_dashboard.workbook import inspect_workbook


PREFLIGHT_MODES = {
    "general",
    "before-export",
    "before-verification",
    "before-promotion",
    "before-rollback",
}


def build_operator_preflight(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    mode: str = "general",
    workbook: str | Path | None = None,
    output_workbook: str | Path | None = None,
    verification_report: str | Path | None = None,
    archive: str | Path | None = None,
) -> dict[str, Any]:
    if mode not in PREFLIGHT_MODES:
        raise ValueError(f"Unknown preflight mode: {mode}")
    base_path = Path(base_dir)
    workbook_path = _main_workbook_path(config, base_path, workbook)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_path)
    result: dict[str, Any] = {
        "operation": "operator_preflight",
        "mode": mode,
        "timestamp": timestamp_iso(),
        "overall_status": "pass",
        "workbook": {},
        "queue_validation": {},
        "queue_summary": {},
        "artifacts": {},
        "latest": {},
        "verified_outputs": {"rows": [], "count": 0},
        "command_guides": {},
        "recommended_next_commands": [],
        "warnings": [],
        "errors": [],
        "no_high_stakes_command_executed": True,
    }

    _collect_workbook(result, workbook_path, config)
    _collect_queues(result, queue_dir, config)
    _collect_artifacts(result, config, base_path)
    _collect_latest(result, config, base_path, output_workbook=output_workbook, verification_report=verification_report)
    _collect_verified_outputs(result, config, base_path)
    _collect_command_guides(result, config, base_path, mode=mode, archive=archive)
    _apply_mode_rules(result, mode)
    result["recommended_next_commands"] = _recommendations_for(result, mode, config)
    result["overall_status"] = _status_for(result["errors"], result["warnings"])
    return result


def render_operator_preflight(result: dict[str, Any]) -> str:
    lines = [
        f"Operator preflight status: {result['overall_status']}",
        f"Mode: {result['mode']}",
        "No high-stakes command was executed.",
        "",
        "Key findings:",
    ]
    workbook = result.get("workbook", {})
    if workbook:
        lines.append(f"- Workbook: {workbook.get('overall_status', '')} ({workbook.get('path', '')})")
    queue_validation = result.get("queue_validation", {})
    if queue_validation:
        lines.append(f"- Queue validation: {queue_validation.get('overall_status', '')}")
    queue_counts = result.get("queue_summary", {}).get("approved_updates_export_tracking", {})
    if queue_counts:
        lines.append(
            "- Approved updates: "
            f"{queue_counts.get('total', 0)} total, {queue_counts.get('not_exported', 0)} not exported"
        )
    latest = result.get("latest", {})
    for label, key in [
        ("Latest output workbook", "output_workbook"),
        ("Latest verification report", "export_verification"),
        ("Latest promoted archive", "promoted_archive"),
    ]:
        value = latest.get(key, {})
        if value.get("path"):
            lines.append(f"- {label}: {value['path']}")
    lines.extend(["", "Blocking issues:", *_bullet_list(result.get("errors", []))])
    lines.extend(["", "Warnings:", *_bullet_list(result.get("warnings", []))])
    lines.append("")
    lines.append("Recommended next commands:")
    for item in result.get("recommended_next_commands", []):
        lines.append(f"- {item}")
    if not result.get("recommended_next_commands"):
        lines.append("- None")
    return "\n".join(lines)


def write_operator_preflight_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    mode = str(result["mode"]).upper().replace("-", "_")
    markdown_path = reports_path / f"operator_preflight_{mode}_{stamp}.md"
    json_path = reports_path / f"operator_preflight_{mode}_{stamp}.json"
    markdown_path.write_text(_render_markdown_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _collect_workbook(result: dict[str, Any], workbook_path: Path, config: dict[str, Any]) -> None:
    inspection = inspect_workbook(workbook_path, config)
    result["workbook"] = {
        "path": str(workbook_path),
        "exists": inspection["workbook_file_exists"],
        "overall_status": inspection["overall_status"],
        "populated_evidence_rows": inspection["evidence_log"]["populated_evidence_rows"],
        "missing_expected_sheets": inspection["expected_sheets"]["missing"],
        "missing_required_columns": inspection["evidence_log"]["required_columns"]["missing"],
        "missing_hypothesis_mi5_columns": inspection["evidence_log"]["hypothesis_mi5_columns"]["missing"],
    }


def _collect_queues(result: dict[str, Any], queue_dir: Path, config: dict[str, Any]) -> None:
    validation = validate_queues(queue_dir, config)
    result["queue_validation"] = {
        "queue_base_dir": validation["queue_base_dir"],
        "overall_status": validation["overall_status"],
        "errors_count": len(validation["errors"]),
        "warnings_count": len(validation["warnings"]),
        "errors": validation["errors"],
        "warnings": validation["warnings"],
    }
    try:
        result["queue_summary"] = queue_summary(queue_dir, config)
    except FileNotFoundError as exc:
        result["queue_summary"] = {"queue_dir": str(queue_dir), "error": str(exc)}


def _collect_artifacts(result: dict[str, Any], config: dict[str, Any], base_dir: Path) -> None:
    artifact_summary = list_artifact_categories(config, base_dir)
    result["artifacts"] = {
        "count": artifact_summary["count"],
        "rows": artifact_summary["rows"],
    }


def _collect_latest(
    result: dict[str, Any],
    config: dict[str, Any],
    base_dir: Path,
    *,
    output_workbook: str | Path | None,
    verification_report: str | Path | None,
) -> None:
    result["latest"] = {
        "output_workbook": _explicit_or_latest(output_workbook, "output_workbooks", config, base_dir),
        "workbook_export_preview": latest_artifact("workbook_export_preview", config, base_dir),
        "workbook_export": latest_artifact("workbook_exports", config, base_dir),
        "export_verification": _explicit_or_latest(verification_report, "export_verification", config, base_dir),
        "workbook_promotion": latest_artifact("workbook_promotion", config, base_dir),
        "workbook_recovery": latest_artifact("workbook_recovery", config, base_dir),
        "promoted_archive": latest_artifact("promoted_archives", config, base_dir),
    }


def _collect_verified_outputs(result: dict[str, Any], config: dict[str, Any], base_dir: Path) -> None:
    result["verified_outputs"] = find_verified_outputs(config, base_dir, status="pass", latest=False)


def _collect_command_guides(
    result: dict[str, Any],
    config: dict[str, Any],
    base_dir: Path,
    *,
    mode: str,
    archive: str | Path | None,
) -> None:
    guides: dict[str, Any] = {"next_safe_commands": next_safe_commands(config, base_dir)}
    verified = result["verified_outputs"]["rows"]
    if mode in {"general", "before-promotion"}:
        if verified:
            row = verified[0]
            guides["promote"] = compose_promote_command(
                config,
                base_dir,
                workbook=row["output_workbook_path"],
                verification_report=row["verification_report_path"],
            )
        else:
            guides["promote"] = compose_promote_command(config, base_dir, latest=True)
    if mode in {"general", "before-rollback"}:
        guides["rollback"] = compose_rollback_command(config, base_dir, archive=archive, latest=archive is None)
    result["command_guides"] = guides


def _apply_mode_rules(result: dict[str, Any], mode: str) -> None:
    workbook = result["workbook"]
    queue_validation = result["queue_validation"]
    queue_summary_data = result.get("queue_summary", {})
    latest = result["latest"]
    verified = result["verified_outputs"]["rows"]

    if mode == "general":
        _warn_missing_latest(result, "output_workbook", "No output workbook found yet.")
        _warn_missing_latest(result, "export_verification", "No export verification report found yet.")
        return

    if mode == "before-export":
        if workbook.get("overall_status") == "fail":
            result["errors"].append("Workbook inspection failed; do not export yet.")
        if queue_validation.get("overall_status") == "fail":
            result["errors"].append("Queue validation failed; do not export yet.")
        approved = queue_summary_data.get("approved_updates_export_tracking", {})
        if approved and int(approved.get("not_exported", 0)) == 0:
            result["warnings"].append("No approved updates are currently waiting for export.")
        if not latest["workbook_export_preview"].get("exists"):
            result["warnings"].append("No recent workbook export preview report was found.")
        return

    if mode == "before-verification":
        output = latest["output_workbook"]
        if not output.get("exists"):
            result["errors"].append("No output workbook is available to verify.")
        elif _verification_for_output(result["verified_outputs"]["rows"], output.get("path", "")):
            result["warnings"].append("A passing verification report already exists for the latest output workbook.")
        if not latest["workbook_export"].get("exists"):
            result["warnings"].append("No workbook export report was found for context.")
        return

    if mode == "before-promotion":
        if not verified:
            result["errors"].append("No passing verification report is available for promotion.")
        else:
            row = verified[0]
            if not row.get("output_workbook_exists"):
                result["errors"].append("Verified output workbook no longer exists.")
            if row.get("modified_after_verification"):
                result["warnings"].append("Verified output workbook appears modified after verification.")
        guide_errors = result["command_guides"].get("promote", {}).get("errors", [])
        result["errors"].extend(guide_errors)
        return

    if mode == "before-rollback":
        archive = latest["promoted_archive"]
        if not archive.get("exists"):
            result["errors"].append("No promoted archive is available for rollback.")
        guide_errors = result["command_guides"].get("rollback", {}).get("errors", [])
        result["errors"].extend(guide_errors)


def _recommendations_for(result: dict[str, Any], mode: str, config: dict[str, Any]) -> list[str]:
    if mode == "before-export":
        return [
            "python -m belief_dashboard.cli preview-workbook-export",
            "python -m belief_dashboard.cli apply-approved-to-workbook --dry-run",
        ]
    if mode == "before-verification":
        output = result["latest"]["output_workbook"]
        if output.get("path"):
            return [f"python -m belief_dashboard.cli verify-workbook-export --workbook {_quote(output['path'], config)}"]
        return ["python -m belief_dashboard.cli latest-output-workbook"]
    if mode == "before-promotion":
        guide = result["command_guides"].get("promote", {})
        return _guide_commands(guide) or ["python -m belief_dashboard.cli find-verified-output"]
    if mode == "before-rollback":
        guide = result["command_guides"].get("rollback", {})
        return _guide_commands(guide) or ["python -m belief_dashboard.cli list-promoted-archives"]
    next_steps = result["command_guides"].get("next_safe_commands", {}).get("steps", [])
    return [step["command"] for step in next_steps[:5]]


def _main_workbook_path(config: dict[str, Any], base_dir: Path, workbook: str | Path | None) -> Path:
    if workbook:
        return resolve_project_path(workbook, base_dir=base_dir)
    return resolve_project_path(config["workbook"]["default_path"], base_dir=base_dir)


def _explicit_or_latest(path_value: str | Path | None, artifact_type: str, config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    if path_value:
        path = resolve_project_path(path_value, base_dir=base_dir)
        return {
            "artifact_type": artifact_type,
            "path": str(path),
            "modified_timestamp": path.stat().st_mtime if path.exists() else "",
            "size": path.stat().st_size if path.exists() else 0,
            "parsed_status": "",
            "exists": path.exists(),
        }
    return latest_artifact(artifact_type, config, base_dir)


def _warn_missing_latest(result: dict[str, Any], key: str, message: str) -> None:
    if not result["latest"][key].get("exists"):
        result["warnings"].append(message)


def _verification_for_output(rows: list[dict[str, Any]], workbook_path: str) -> bool:
    return any(row.get("output_workbook_path") == workbook_path for row in rows)


def _guide_commands(guide: dict[str, Any]) -> list[str]:
    commands = []
    if guide.get("dry_run_command"):
        commands.append(guide["dry_run_command"])
    if guide.get("real_command"):
        commands.append(guide["real_command"])
    return commands


def _status_for(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "fail"
    if warnings:
        return "warning"
    return "pass"


def _quote(path: str | Path, config: dict[str, Any]) -> str:
    if not config.get("command_composition", {}).get("quote_paths", True):
        return str(path)
    return f'"{str(path).replace(chr(34), chr(92) + chr(34))}"'


def _render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# Operator Preflight: {str(result['mode']).replace('-', ' ').title()}",
        "",
        f"- Timestamp: `{result['timestamp']}`",
        f"- Mode: `{result['mode']}`",
        f"- Overall status: `{result['overall_status']}`",
        "- No high-stakes command was executed: `True`",
        "",
        "## Console Summary",
        "",
        "```text",
        render_operator_preflight(result),
        "```",
        "",
        "## Latest Artifacts",
    ]
    for key, value in result.get("latest", {}).items():
        lines.append(f"- `{key}`: `{value.get('path', '')}`")
    lines.extend(["", "## Verified Output Candidates"])
    for row in result.get("verified_outputs", {}).get("rows", []):
        lines.append(f"- `{row.get('output_workbook_path', '')}` via `{row.get('verification_report_path', '')}`")
    if not result.get("verified_outputs", {}).get("rows"):
        lines.append("- None")
    lines.extend(["", "## Recommended Next Commands"])
    lines.extend(_bullet_list(result.get("recommended_next_commands", [])))
    lines.extend(["", "## Warnings", *_bullet_list(result.get("warnings", []))])
    lines.extend(["", "## Errors", *_bullet_list(result.get("errors", [])), ""])
    return "\n".join(lines)


def _bullet_list(values: list[str]) -> list[str]:
    if not values:
        return ["- None"]
    return [f"- {value}" for value in values]
