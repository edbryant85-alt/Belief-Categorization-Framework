from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import yaml

from belief_dashboard.cli import main
from belief_dashboard.command_guides import compose_promote_command, compose_rollback_command, next_safe_commands
from belief_dashboard.config import load_config


def test_compose_promote_command_builds_dry_run_and_real_commands_from_explicit_paths(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    workbook = tmp_path / "outputs" / "output.xlsx"
    report = tmp_path / "reports" / "export_verification" / "verification.json"
    _write_file(workbook, b"workbook")
    _write_json(report, {"overall_status": "pass", "output_workbook_path": str(workbook)})

    result = compose_promote_command(config, tmp_path, workbook=workbook, verification_report=report)

    assert result["errors"] == []
    assert result["dry_run_command"].endswith("--dry-run")
    assert "promote-output-workbook" in result["real_command"]
    assert str(workbook) in result["real_command"]
    assert str(report) in result["real_command"]


def test_compose_promote_command_latest_selects_latest_passing_verified_output(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    older = tmp_path / "outputs" / "older.xlsx"
    newer = tmp_path / "outputs" / "newer.xlsx"
    _write_file(older, b"older")
    _write_file(newer, b"newer")
    _write_json(
        tmp_path / "reports" / "export_verification" / "older.json",
        {"overall_status": "pass", "output_workbook_path": str(older), "verification_timestamp": "2026-05-26T10:00:00"},
    )
    newer_report = tmp_path / "reports" / "export_verification" / "newer.json"
    _write_json(
        newer_report,
        {"overall_status": "pass", "output_workbook_path": str(newer), "verification_timestamp": "2026-05-26T11:00:00"},
    )

    result = compose_promote_command(config, tmp_path, latest=True)

    assert result["errors"] == []
    assert result["workbook"] == str(newer)
    assert result["verification_report"] == str(newer_report)


def test_compose_promote_command_fails_if_verification_report_does_not_match_workbook(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    selected = tmp_path / "outputs" / "selected.xlsx"
    other = tmp_path / "outputs" / "other.xlsx"
    report = tmp_path / "reports" / "export_verification" / "verification.json"
    _write_file(selected, b"selected")
    _write_file(other, b"other")
    _write_json(report, {"overall_status": "pass", "output_workbook_path": str(other)})

    result = compose_promote_command(config, tmp_path, workbook=selected, verification_report=report)

    assert "Verification report does not refer to the selected workbook." in result["errors"]


def test_compose_promote_command_format_json_returns_structured_data(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)
    workbook = tmp_path / "outputs" / "output.xlsx"
    report = tmp_path / "reports" / "export_verification" / "verification.json"
    _write_file(workbook, b"workbook")
    _write_json(report, {"overall_status": "pass", "output_workbook_path": str(workbook)})

    exit_code = main(
        [
            "compose-promote-command",
            "--config",
            str(config_path),
            "--workbook",
            str(workbook),
            "--verification-report",
            str(report),
            "--format",
            "json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "promote_output_workbook"
    assert output["dry_run_command"]
    assert output["real_command"]


def test_compose_rollback_command_builds_dry_run_and_real_commands_from_explicit_archive(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    archive = tmp_path / "backups" / "promoted_archives" / "archive.xlsx"
    _write_file(archive, b"archive")

    result = compose_rollback_command(config, tmp_path, archive=archive)

    assert result["errors"] == []
    assert result["dry_run_command"].endswith("--dry-run")
    assert "rollback-workbook" in result["real_command"]
    assert str(archive) in result["real_command"]


def test_compose_rollback_command_latest_selects_latest_promoted_archive(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    older = tmp_path / "backups" / "promoted_archives" / "older.xlsx"
    newer = tmp_path / "backups" / "promoted_archives" / "newer.xlsx"
    _write_file(older, b"older")
    _write_file(newer, b"newer")
    _touch(older, datetime(2026, 5, 26, 10, 0, 0))
    _touch(newer, datetime(2026, 5, 26, 11, 0, 0))

    result = compose_rollback_command(config, tmp_path, latest=True)

    assert result["errors"] == []
    assert result["archive"] == str(newer)


def test_compose_rollback_command_format_json_returns_structured_data(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)
    archive = tmp_path / "backups" / "promoted_archives" / "archive.xlsx"
    _write_file(archive, b"archive")

    exit_code = main(["compose-rollback-command", "--config", str(config_path), "--archive", str(archive), "--format", "json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "rollback_workbook"
    assert output["dry_run_command"]
    assert output["real_command"]


def test_commands_quote_paths_safely_when_paths_contain_spaces(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)
    workbook = tmp_path / "outputs" / "output file.xlsx"
    report = tmp_path / "reports" / "export_verification" / "verification report.json"
    _write_file(workbook, b"workbook")
    _write_json(report, {"overall_status": "pass", "output_workbook_path": str(workbook)})

    result = compose_promote_command(config, tmp_path, workbook=workbook, verification_report=report)

    assert f'--workbook "{workbook}"' in result["real_command"]
    assert f'--verification-report "{report}"' in result["real_command"]


def test_next_safe_commands_returns_conservative_checklist(tmp_path: Path) -> None:
    config = _guide_config(tmp_path)

    result = next_safe_commands(config, tmp_path)

    commands = [step["command"] for step in result["steps"]]
    assert result["operation"] == "next_safe_commands"
    assert any("validate-queues" in command for command in commands)
    assert any("preview-workbook-export" in command for command in commands)
    assert any("compose-promote-command --latest" in command for command in commands)
    assert result["no_high_stakes_command_executed"] is True


def test_save_writes_markdown_and_json_guide_reports(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)
    archive = tmp_path / "backups" / "promoted_archives" / "archive.xlsx"
    _write_file(archive, b"archive")

    exit_code = main(["compose-rollback-command", "--config", str(config_path), "--archive", str(archive), "--save"])

    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "command_guides"
    assert exit_code == 0
    assert "Markdown report:" in output
    assert "JSON report:" in output
    assert list(reports_dir.glob("command_guide_ROLLBACK_*.md"))
    assert list(reports_dir.glob("command_guide_ROLLBACK_*.json"))


def test_command_composition_commands_do_not_mutate_workbooks(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    workbook = tmp_path / "outputs" / "output.xlsx"
    report = tmp_path / "reports" / "export_verification" / "verification.json"
    archive = tmp_path / "backups" / "promoted_archives" / "archive.xlsx"
    _write_file(workbook, b"workbook")
    _write_file(archive, b"archive")
    _write_json(report, {"overall_status": "pass", "output_workbook_path": str(workbook)})
    before = {_path: _sha256(_path) for _path in [workbook, archive]}

    assert main(["compose-promote-command", "--config", str(config_path), "--workbook", str(workbook), "--verification-report", str(report)]) == 0
    assert main(["compose-rollback-command", "--config", str(config_path), "--archive", str(archive)]) == 0

    assert {_path: _sha256(_path) for _path in [workbook, archive]} == before


def test_command_composition_commands_do_not_mutate_queue_files(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    queue_file = tmp_path / "queues" / "approved_updates.csv"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text("proposal_id,review_status\nPROP0001,approved\n", encoding="utf-8")
    before = _sha256(queue_file)

    assert main(["next-safe-commands", "--config", str(config_path)]) == 0

    assert _sha256(queue_file) == before


def _guide_config(tmp_path: Path) -> dict:
    config = load_config("config.yaml")
    config["artifact_navigation"] = {
        "reports_dir": str(tmp_path / "reports" / "artifact_navigation"),
        "reports": {
            "workbook_inspection": str(tmp_path / "reports" / "workbook_inspection"),
            "queue_validation": str(tmp_path / "reports" / "queue_validation"),
            "prompt_packets": str(tmp_path / "reports" / "prompt_packets"),
            "manual_imports": str(tmp_path / "reports" / "manual_imports"),
            "reviews": str(tmp_path / "reports" / "reviews"),
            "workbook_export_preview": str(tmp_path / "reports" / "workbook_export_preview"),
            "workbook_exports": str(tmp_path / "reports" / "workbook_exports"),
            "export_verification": str(tmp_path / "reports" / "export_verification"),
            "workbook_promotion": str(tmp_path / "reports" / "workbook_promotion"),
            "workbook_recovery": str(tmp_path / "reports" / "workbook_recovery"),
        },
        "workbooks": {
            "main": str(tmp_path / "workbooks" / "main.xlsx"),
            "outputs": str(tmp_path / "outputs"),
            "backups": str(tmp_path / "backups"),
            "promoted_archives": str(tmp_path / "backups" / "promoted_archives"),
            "rollback_archives": str(tmp_path / "backups" / "rollback_archives"),
        },
        "default_limit": 10,
    }
    config["command_composition"] = {
        "reports_dir": str(tmp_path / "reports" / "command_guides"),
        "default_include_dry_run_first": True,
        "quote_paths": True,
    }
    for directory in config["artifact_navigation"]["reports"].values():
        Path(directory).mkdir(parents=True, exist_ok=True)
    for directory in [
        config["artifact_navigation"]["reports_dir"],
        config["artifact_navigation"]["workbooks"]["outputs"],
        config["artifact_navigation"]["workbooks"]["promoted_archives"],
        config["artifact_navigation"]["workbooks"]["rollback_archives"],
        config["command_composition"]["reports_dir"],
    ]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    Path(config["artifact_navigation"]["workbooks"]["main"]).parent.mkdir(parents=True, exist_ok=True)
    return config


def _write_config(tmp_path: Path) -> Path:
    config = _guide_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _touch(path: Path, value: datetime) -> None:
    timestamp = value.timestamp()
    path.touch()
    os.utime(path, (timestamp, timestamp))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
