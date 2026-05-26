from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.artifacts import find_verified_outputs, latest_artifact
from belief_dashboard.utils import resolve_project_path, timestamp_for_filename, timestamp_iso


class CommandGuideError(ValueError):
    pass


def compose_promote_command(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    workbook: str | Path | None = None,
    verification_report: str | Path | None = None,
    latest: bool = False,
    include_dry_run: bool | None = None,
) -> dict[str, Any]:
    result = _base_result("promote_output_workbook")
    selected_workbook = resolve_project_path(workbook, base_dir=base_dir) if workbook else None
    selected_report = resolve_project_path(verification_report, base_dir=base_dir) if verification_report else None

    if latest:
        latest_selection = find_verified_outputs(config, base_dir, status="pass", latest=True)
        if latest_selection["rows"]:
            row = latest_selection["rows"][0]
            selected_workbook = Path(row["output_workbook_path"])
            selected_report = Path(row["verification_report_path"])
        else:
            result["errors"].append("No passing verified output workbook was found.")
    elif not selected_workbook or not selected_report:
        result["errors"].append("Provide --workbook and --verification-report, or use --latest.")

    if selected_workbook:
        result["workbook"] = str(selected_workbook)
        if not selected_workbook.exists():
            result["errors"].append(f"Workbook not found: {selected_workbook}")
    if selected_report:
        result["verification_report"] = str(selected_report)
        if not selected_report.exists():
            result["errors"].append(f"Verification report not found: {selected_report}")

    if selected_workbook and selected_report and selected_report.exists():
        report_data = _load_json(selected_report)
        report_workbook = str(report_data.get("output_workbook_path", "")) if report_data else ""
        if not report_data:
            result["errors"].append(f"Verification report is not valid JSON object: {selected_report}")
        elif not report_workbook:
            result["errors"].append(f"Verification report does not name an output_workbook_path: {selected_report}")
        elif _normalized_path(report_workbook, base_dir) != _normalized_path(selected_workbook, base_dir):
            result["errors"].append("Verification report does not refer to the selected workbook.")
        status = str(report_data.get("overall_status", "")) if report_data else ""
        if status and status != "pass":
            result["warnings"].append(f"Verification report status is {status}, not pass.")

    include = _include_dry_run(config, include_dry_run)
    if selected_workbook and selected_report:
        result["dry_run_command"] = _promote_command(selected_workbook, selected_report, dry_run=True, config=config) if include else ""
        result["real_command"] = _promote_command(selected_workbook, selected_report, dry_run=False, config=config)
    return result


def compose_rollback_command(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    archive: str | Path | None = None,
    latest: bool = False,
    include_dry_run: bool | None = None,
) -> dict[str, Any]:
    result = _base_result("rollback_workbook")
    selected_archive = resolve_project_path(archive, base_dir=base_dir) if archive else None

    if latest:
        latest_archive = latest_artifact("promoted_archives", config, base_dir)
        if latest_archive["exists"]:
            selected_archive = Path(latest_archive["path"])
        else:
            result["errors"].append("No promoted archive workbook was found.")
    elif not selected_archive:
        result["errors"].append("Provide --archive, or use --latest.")

    if selected_archive:
        result["archive"] = str(selected_archive)
        if not selected_archive.exists():
            result["errors"].append(f"Archive not found: {selected_archive}")

    include = _include_dry_run(config, include_dry_run)
    if selected_archive:
        result["dry_run_command"] = _rollback_command(selected_archive, dry_run=True, config=config) if include else ""
        result["real_command"] = _rollback_command(selected_archive, dry_run=False, config=config)
    return result


def next_safe_commands(config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    warnings = _queue_state_warnings(config, base_dir)
    steps = [
        {
            "step": 1,
            "label": "Inspect workbook",
            "command": "python -m belief_dashboard.cli inspect-workbook",
            "notes": "Read-only workbook structure check.",
        },
        {
            "step": 2,
            "label": "Validate queues",
            "command": "python -m belief_dashboard.cli validate-queues",
            "notes": "Checks queue files before any export planning.",
        },
        {
            "step": 3,
            "label": "Preview workbook export",
            "command": "python -m belief_dashboard.cli preview-workbook-export",
            "notes": "Plans workbook changes without writing Excel.",
        },
        {
            "step": 4,
            "label": "Dry-run workbook export",
            "command": "python -m belief_dashboard.cli apply-approved-to-workbook --dry-run",
            "notes": "Runs guarded export checks without writing workbook files.",
        },
    ]
    latest_output = latest_artifact("output_workbooks", config, base_dir)
    if latest_output["exists"]:
        verify_command = "python -m belief_dashboard.cli verify-workbook-export --workbook " + quote_path(
            latest_output["path"],
            config,
        )
        verify_notes = "Uses the latest output workbook artifact."
    else:
        verify_command = "python -m belief_dashboard.cli latest-output-workbook"
        verify_notes = "No output workbook was found; find or create one before verification."
    steps.append({"step": 5, "label": "Verify latest output", "command": verify_command, "notes": verify_notes})
    steps.extend(
        [
            {
                "step": 6,
                "label": "Find verified output",
                "command": "python -m belief_dashboard.cli find-verified-output",
                "notes": "Lists output workbooks with passing verification reports.",
            },
            {
                "step": 7,
                "label": "Compose promotion command",
                "command": "python -m belief_dashboard.cli compose-promote-command --latest",
                "notes": "Prints promotion commands, but does not run them.",
            },
            {
                "step": 8,
                "label": "Current workbook status",
                "command": "python -m belief_dashboard.cli current-workbook-status",
                "notes": "Read-only status summary after guarded operations.",
            },
        ]
    )
    return {
        "operation": "next_safe_commands",
        "timestamp": timestamp_iso(),
        "steps": steps,
        "warnings": warnings,
        "errors": [],
        "no_high_stakes_command_executed": True,
    }


def render_command_guide(result: dict[str, Any]) -> str:
    if result.get("operation") == "next_safe_commands":
        lines = ["Suggested next safe commands:", ""]
        for step in result.get("steps", []):
            lines.extend(
                [
                    f"{step['step']}. {step['label']}:",
                    f"   {step['command']}",
                    f"   {step['notes']}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    lines = [
        f"Operation: {result.get('operation', '')}",
        "No high-stakes command was executed.",
    ]
    if result.get("workbook"):
        lines.append(f"Workbook: {result['workbook']}")
    if result.get("verification_report"):
        lines.append(f"Verification report: {result['verification_report']}")
    if result.get("archive"):
        lines.append(f"Archive: {result['archive']}")
    if result.get("dry_run_command"):
        lines.extend(["", "Dry-run command:", result["dry_run_command"]])
    if result.get("real_command"):
        lines.extend(["", "Real command:", result["real_command"]])
    if result.get("warnings"):
        lines.extend(["", "Warnings:", *_bullet_list(result["warnings"])])
    if result.get("errors"):
        lines.extend(["", "Errors:", *_bullet_list(result["errors"])])
    return "\n".join(lines)


def write_command_guide_report(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    guide_name: str,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"command_guide_{guide_name}_{stamp}.md"
    json_path = reports_path / f"command_guide_{guide_name}_{stamp}.json"
    report = dict(result)
    report["saved_report_timestamp"] = timestamp_iso(written_at)
    report["no_high_stakes_command_executed"] = True
    markdown_path.write_text(_render_markdown_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def quote_path(path: str | Path, config: dict[str, Any]) -> str:
    if not config.get("command_composition", {}).get("quote_paths", True):
        return str(path)
    value = str(path)
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def _promote_command(workbook: Path, verification_report: Path, *, dry_run: bool, config: dict[str, Any]) -> str:
    command = (
        "python -m belief_dashboard.cli promote-output-workbook"
        f" --workbook {quote_path(workbook, config)}"
        f" --verification-report {quote_path(verification_report, config)}"
    )
    return f"{command} --dry-run" if dry_run else command


def _rollback_command(archive: Path, *, dry_run: bool, config: dict[str, Any]) -> str:
    command = f"python -m belief_dashboard.cli rollback-workbook --archive {quote_path(archive, config)}"
    return f"{command} --dry-run" if dry_run else command


def _base_result(operation: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "timestamp": timestamp_iso(),
        "workbook": "",
        "verification_report": "",
        "archive": "",
        "dry_run_command": "",
        "real_command": "",
        "warnings": [],
        "errors": [],
        "no_high_stakes_command_executed": True,
    }


def _include_dry_run(config: dict[str, Any], include_dry_run: bool | None) -> bool:
    if include_dry_run is not None:
        return include_dry_run
    return bool(config.get("command_composition", {}).get("default_include_dry_run_first", True))


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _queue_state_warnings(config: dict[str, Any], base_dir: str | Path) -> list[str]:
    queue_config = config.get("queues", {})
    queue_dir = resolve_project_path(queue_config.get("base_dir", "data/queues"), base_dir=base_dir)
    warnings = []
    if not queue_dir.exists():
        warnings.append(f"Queue directory was not found: {queue_dir}")
        return warnings
    approved_name = queue_config.get("files", {}).get("approved_updates", "approved_updates.csv")
    approved_path = queue_dir / approved_name
    if not approved_path.exists():
        warnings.append(f"Approved updates queue was not found: {approved_path}")
    return warnings


def _normalized_path(path: str | Path, base_dir: str | Path) -> Path:
    return resolve_project_path(path, base_dir=base_dir).resolve()


def _render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"# Command Guide: {str(result.get('operation', '')).replace('_', ' ').title()}",
        "",
        f"- Timestamp: `{result.get('saved_report_timestamp', result.get('timestamp', ''))}`",
        "- No high-stakes command was executed: `True`",
        "",
        "## Guide",
        "",
        render_command_guide(result),
        "",
    ]
    return "\n".join(lines)


def _bullet_list(values: list[str]) -> list[str]:
    if not values:
        return ["- None"]
    return [f"- {value}" for value in values]
