from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.artifacts import list_artifact_categories
from belief_dashboard.operator_preflight import build_operator_preflight
from belief_dashboard.queues import validate_queues
from belief_dashboard.utils import resolve_project_path, timestamp_for_filename, timestamp_iso
from belief_dashboard.workbook import inspect_workbook

REQUIRED_README_COMMANDS = [
    "inspect-workbook",
    "validate-queues",
    "operator-preflight",
    "product-readiness",
]


def build_product_readiness(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    sample_demo_dir: str | Path | None = None,
) -> dict[str, Any]:
    base_path = Path(base_dir)
    sample_root = resolve_project_path(config.get("paths", {}).get("sample_dir", "data/sample"), base_dir=base_path)
    configured_demo_dir = config.get("product_readiness", {}).get("sample_demo_dir")
    demo_dir = resolve_project_path(sample_demo_dir or configured_demo_dir or sample_root / "end_to_end_demo", base_dir=base_path)

    result: dict[str, Any] = {
        "operation": "product_readiness",
        "timestamp": timestamp_iso(),
        "overall_status": "pass",
        "checks": [],
        "warnings": [],
        "errors": [],
        "test_command": "python -m pytest",
    }

    _add_check(result, "config_loaded", "pass", "Configuration loaded successfully.")
    _check_main_workbook(config, base_path, result)
    _check_queue_files(config, base_path, result)
    _check_queue_validation(config, base_path, result)
    _check_sample_demo_assets(demo_dir, result)
    _check_artifact_directories(config, base_path, result)
    _check_output_and_backup_directories(config, base_path, result)
    _check_operator_preflight(config, base_path, result)
    _check_readme_mentions(base_path, result)
    _check_repo_artifacts(config, base_path, result)

    result["overall_status"] = _status_for(result["errors"], result["warnings"])
    return result


def write_product_readiness_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"product_readiness_{stamp}.md"
    json_path = reports_path / f"product_readiness_{stamp}.json"
    markdown_path.write_text(render_product_readiness(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_product_readiness(result: dict[str, Any]) -> str:
    lines = [
        "# Product Readiness Report",
        "",
        f"- Timestamp: `{result['timestamp']}`",
        f"- Overall status: `{result['overall_status']}`",
        "",
        "## Checks",
    ]
    for check in result["checks"]:
        lines.append(f"- `{check['name']}`: `{check['status']}` — {check['message']}")
        if check.get("details"):
            lines.append(f"  - Details: {check['details']}")
    lines.extend(["", "## Warnings", *_bullet_list(result["warnings"]), "", "## Errors", *_bullet_list(result["errors"]), "", "## Test Command", f"- `{result['test_command']}`", ""])
    return "\n".join(lines)


def _add_check(result: dict[str, Any], name: str, status: str, message: str, *, details: str = "") -> None:
    result["checks"].append({"name": name, "status": status, "message": message, "details": details})


def _check_main_workbook(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    workbook_path = resolve_project_path(config["workbook"]["default_path"], base_dir=base_dir)
    if workbook_path.exists():
        _add_check(result, "main_workbook_exists", "pass", "Main workbook exists.", details=str(workbook_path))
    else:
        result["errors"].append(f"Main workbook does not exist: {workbook_path}")
        _add_check(result, "main_workbook_exists", "fail", "Main workbook missing.", details=str(workbook_path))


def _check_queue_files(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    if not queue_dir.exists():
        result["errors"].append(f"Queue base directory does not exist: {queue_dir}")
        _add_check(result, "queue_base_dir_exists", "fail", "Queue directory missing.", details=str(queue_dir))
        return
    missing = []
    for filename in config["queues"]["files"].values():
        path = queue_dir / filename
        if not path.exists():
            missing.append(str(path))
    if missing:
        result["errors"].append(f"Missing queue files: {', '.join(missing)}")
        _add_check(result, "queue_files_exist", "fail", "Some queue files are missing.", details="; ".join(missing))
    else:
        _add_check(result, "queue_files_exist", "pass", "All configured queue files are present.", details=str(queue_dir))


def _check_queue_validation(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    if not queue_dir.exists():
        return
    validation = validate_queues(queue_dir, config)
    status = validation["overall_status"]
    if status == "pass":
        _add_check(result, "queue_validation", "pass", "Queue validation passed.")
    elif status == "warning":
        result["warnings"].append("Queue validation completed with warnings.")
        _add_check(result, "queue_validation", "warning", "Queue validation has warnings.")
    else:
        result["errors"].append("Queue validation failed.")
        _add_check(result, "queue_validation", "fail", "Queue validation failed.")


def _check_sample_demo_assets(demo_dir: Path, result: dict[str, Any]) -> None:
    required = [
        "demo_workbook.xlsx",
        "sample_source.md",
        "extracted_claims.csv",
        "criteria_matrix.csv",
        "proposed_updates.csv",
        "README.md",
    ]
    if not demo_dir.exists():
        result["errors"].append(f"Sample demo directory not found: {demo_dir}")
        _add_check(result, "sample_demo_dir", "fail", "Sample demo assets missing.", details=str(demo_dir))
        return
    missing = [name for name in required if not (demo_dir / name).exists()]
    if missing:
        result["errors"].append(f"Missing sample demo assets: {', '.join(missing)}")
        _add_check(result, "sample_demo_assets", "fail", "Some demo assets are missing.", details=", ".join(missing))
    else:
        _add_check(result, "sample_demo_assets", "pass", "All sample demo assets are present.", details=str(demo_dir))


def _check_artifact_directories(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    artifact_dirs = []
    discovery = config.get("artifact_navigation", {})
    if discovery.get("reports_dir"):
        artifact_dirs.append(resolve_project_path(discovery["reports_dir"], base_dir=base_dir))
    artifact_dirs.extend(resolve_project_path(path, base_dir=base_dir) for path in discovery.get("reports", {}).values())
    missing = [str(path) for path in artifact_dirs if not path.exists()]
    if missing:
        result["warnings"].append(f"Artifact report directories are missing: {', '.join(missing)}")
        _add_check(result, "artifact_directories", "warning", "Artifact directories are missing or empty.", details="; ".join(missing))
    else:
        _add_check(result, "artifact_directories", "pass", "Artifact directories exist.")


def _check_output_and_backup_directories(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    output_dirs = []
    output_dirs.append(resolve_project_path(config.get("workbook_export", {}).get("outputs_dir", "data/outputs"), base_dir=base_dir))
    output_dirs.append(resolve_project_path(config.get("workbook_export", {}).get("backups_dir", "data/backups"), base_dir=base_dir))
    output_dirs.append(resolve_project_path(config.get("workbook_promotion", {}).get("archive_dir", "data/backups/promoted_archives"), base_dir=base_dir))
    output_dirs.append(resolve_project_path(config.get("workbook_recovery", {}).get("rollback_archive_dir", "data/backups/rollback_archives"), base_dir=base_dir))
    missing = [str(path) for path in output_dirs if not path.exists()]
    if missing:
        result["warnings"].append(f"Output/backups directories are missing: {', '.join(missing)}")
        _add_check(result, "output_backup_directories", "warning", "Some output or backup directories are missing.", details="; ".join(missing))
    else:
        _add_check(result, "output_backup_directories", "pass", "Output and backup directories exist.")


def _check_operator_preflight(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    try:
        preflight = build_operator_preflight(config, base_dir, mode="general")
    except Exception as exc:
        result["errors"].append(f"Operator preflight failed: {exc}")
        _add_check(result, "operator_preflight", "fail", "Operator preflight execution failed.")
        return
    if preflight["overall_status"] == "pass":
        _add_check(result, "operator_preflight", "pass", "Operator preflight passed.")
    elif preflight["overall_status"] == "warning":
        result["warnings"].append("Operator preflight returned warnings.")
        _add_check(result, "operator_preflight", "warning", "Operator preflight returned warnings.")
    else:
        result["errors"].append("Operator preflight failed.")
        _add_check(result, "operator_preflight", "fail", "Operator preflight failed.")


def _check_readme_mentions(base_dir: Path, result: dict[str, Any]) -> None:
    root_readme = base_dir.parent / "README.md"
    tool_readme = base_dir / "README.md"
    found = False
    missing_commands = []
    combined = ""
    if root_readme.exists():
        combined += root_readme.read_text(encoding="utf-8") + "\n"
    if tool_readme.exists():
        combined += tool_readme.read_text(encoding="utf-8") + "\n"
    for command in REQUIRED_README_COMMANDS:
        if command not in combined:
            missing_commands.append(command)
    if missing_commands:
        result["warnings"].append(f"README files do not mention: {', '.join(missing_commands)}")
        _add_check(result, "readme_mentions", "warning", "README command coverage incomplete.", details=", ".join(missing_commands))
    else:
        _add_check(result, "readme_mentions", "pass", "README appears to mention current commands.")


def _check_repo_artifacts(config: dict[str, Any], base_dir: Path, result: dict[str, Any]) -> None:
    artifact_summary = list_artifact_categories(config, base_dir)
    _add_check(result, "artifact_discovery", "pass", f"Found {artifact_summary['count']} artifact categories.")


def _status_for(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "fail"
    if warnings:
        return "warning"
    return "pass"


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
