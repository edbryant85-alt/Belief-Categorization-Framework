from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from belief_dashboard.utils import timestamp_for_filename
from belief_dashboard_agentflows.cli_runner import CliResult, run_cli_command
from belief_dashboard_agentflows.config_reader import read_config
from belief_dashboard_agentflows.queue_reader import read_queue, reports_dir
from belief_dashboard_agentflows.reports.json import write_json_report
from belief_dashboard_agentflows.reports.markdown import write_markdown_report


def run_export_preflight(
    *,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    output_workbook: str | Path | None = None,
    save: bool = False,
) -> dict[str, Any]:
    config = read_config(project_dir, config_path)
    commands = [
        run_cli_command(["validate-queues"], project_dir=project_dir, config_path=config_path),
        run_cli_command(["doctor"], project_dir=project_dir, config_path=config_path),
        run_cli_command(["operator-preflight", "--mode", "before-export"], project_dir=project_dir, config_path=config_path),
        run_cli_command(["preview-workbook-export"], project_dir=project_dir, config_path=config_path),
    ]
    if output_workbook is not None:
        commands.append(
            run_cli_command(
                ["verify-workbook-export", "--workbook", str(output_workbook)],
                project_dir=project_dir,
                config_path=config_path,
            )
        )

    approved = read_queue(project_dir, config, "approved_updates")
    export_status_counts = Counter((row.get("export_status") or "not_exported") for row in approved)
    blockers = _blockers(commands)
    warnings = _warnings(commands)
    status = "ready" if not blockers else "not_ready"
    report = {
        "title": "Export Preflight Report",
        "flow": "export-preflight",
        "status": status,
        "approved_row_count": len(approved),
        "export_status_counts": dict(export_status_counts),
        "blockers": blockers,
        "warnings": warnings,
        "recommended_next_command": _next_command(status),
        "commands_run": [_command_summary(command) for command in commands],
        "summaries": [
            f"Approved rows: {len(approved)}",
            "Export statuses: "
            + (", ".join(f"{key}={value}" for key, value in sorted(export_status_counts.items())) or "none"),
        ],
    }
    if save:
        _write_reports(project_dir, report)
    return report


def _blockers(commands: list[CliResult]) -> list[str]:
    blockers = []
    for result in commands:
        if result.return_code != 0:
            blockers.append(f"Command failed: {' '.join(result.command)}")
    return blockers


def _warnings(commands: list[CliResult]) -> list[str]:
    warnings = []
    for result in commands:
        output = f"{result.stdout}\n{result.stderr}".lower()
        if "warning" in output:
            warnings.append(f"Command reported warnings: {' '.join(result.command)}")
    return warnings


def _next_command(status: str) -> str:
    if status == "ready":
        return "Run apply-approved-to-workbook --dry-run before any real export."
    return "Resolve blockers, then rerun export-preflight."


def _command_summary(result: CliResult) -> dict[str, Any]:
    return {
        "command": " ".join(result.command),
        "return_code": result.return_code,
        "risk": result.policy.risk.value,
        "stdout_preview": result.stdout[:1000],
        "stderr_preview": result.stderr[:1000],
    }


def _write_reports(project_dir: str | Path, report: dict[str, Any]) -> None:
    base = reports_dir(project_dir) / "export_preflight"
    stamp = timestamp_for_filename()
    write_markdown_report(base / f"export_preflight_{stamp}.md", report)
    write_json_report(base / f"export_preflight_{stamp}.json", report)
