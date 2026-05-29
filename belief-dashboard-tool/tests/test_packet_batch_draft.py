from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.packet_batch_draft import (
    MVP_PACKET_IDS,
    run_packet_batch_draft,
)


def test_command_rejects_missing_packet_ids(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    with pytest.raises(ValueError, match="At least one --packet-id"):
        run_packet_batch_draft(source_id="SRC0018", project_dir=tmp_path, config_path=config_path)


def test_command_rejects_packet_ids_not_belonging_to_source_id(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    with pytest.raises(ValueError, match="supports only SRC0018"):
        run_packet_batch_draft(
            source_id="SRC9999",
            packet_ids=["SRC9999-PKT-002", "SRC9999-PKT-003", "SRC9999-PKT-004"],
            project_dir=tmp_path,
            config_path=config_path,
        )


def test_command_refuses_non_mvp_packet_set(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    with pytest.raises(ValueError, match="MVP refuses"):
        run_packet_batch_draft(
            source_id="SRC0018",
            packet_ids=["SRC0018-PKT-002", "SRC0018-PKT-003", "SRC0018-PKT-005"],
            project_dir=tmp_path,
            config_path=config_path,
        )


def test_packet_cycle_group_resolves_to_first_batch(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)

    report = run_packet_batch_draft(
        source_id="SRC0018",
        packet_cycle_group="Introduction / What Good Is Apologetics",
        project_dir=tmp_path,
        config_path=config_path,
    )

    assert report["packet_ids"] == MVP_PACKET_IDS


def test_command_fails_safely_if_outputs_exist_without_overwrite(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)
    first = run_packet_batch_draft(source_id="SRC0018", packet_ids=MVP_PACKET_IDS, project_dir=tmp_path, config_path=config_path)
    assert first["status"] == "passed"

    second = run_packet_batch_draft(source_id="SRC0018", packet_ids=MVP_PACKET_IDS, project_dir=tmp_path, config_path=config_path)

    assert second["status"] == "failed"
    assert "Output files already exist" in second["blockers"][0]


def test_command_writes_merged_csvs_with_exact_headers_reports_and_zip(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)

    report = run_packet_batch_draft(source_id="SRC0018", packet_ids=MVP_PACKET_IDS, project_dir=tmp_path, config_path=config_path)

    assert report["status"] == "passed"
    assert report["row_counts"] == {"extracted_claims": 9, "criteria_matrix": 9, "proposed_updates": 6}
    for import_type in ["extracted_claims", "criteria_matrix", "proposed_updates"]:
        path = Path(report["output_files"][import_type])
        assert path.exists()
        with path.open("r", encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == QUEUE_SCHEMAS[import_type]
    assert (tmp_path / "reports" / "agentflow_runs" / "SRC0018_intro_apologetics_batch" / "packet_batch_draft_report.md").exists()
    json_path = tmp_path / "reports" / "agentflow_runs" / "SRC0018_intro_apologetics_batch" / "packet_batch_draft_report.json"
    assert json.loads(json_path.read_text(encoding="utf-8"))["human_review_required"] is True
    zip_path = Path(report["output_files"]["zip"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        assert "generated/SRC0018_intro_apologetics_extracted_claims.csv" in archive.namelist()


def test_command_calculates_next_ids_without_collisions(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)
    _append_queue_row(tmp_path / "queues" / "extracted_claims.csv", "extracted_claims", {"claim_id": "SRC0018-C004", "source_id": "SRC0018", "claim_text": "Existing claim."})
    _append_queue_row(tmp_path / "queues" / "proposed_updates.csv", "proposed_updates", {"proposal_id": "SRC0018-P003", "claim_id": "SRC0018-C004", "source_id": "SRC0018", "evidence_argument": "Existing.", "category": "Existing", "source_book": "Existing"})
    manual = tmp_path / "manual_imports" / "old_SRC0018_extracted_claims.csv"
    _write_csv(manual, "extracted_claims", [{"claim_id": "SRC0018-C007", "source_id": "SRC0018", "claim_text": "Old manual draft."}])

    report = run_packet_batch_draft(source_id="SRC0018", packet_ids=MVP_PACKET_IDS, project_dir=tmp_path, config_path=config_path)

    assert report["next_id_summary"]["next_claim_id"] == "SRC0018-C008"
    assert report["next_id_summary"]["next_proposal_id"] == "SRC0018-P004"
    rows = _read_rows(Path(report["output_files"]["extracted_claims"]))
    assert rows[0]["claim_id"] == "SRC0018-C008"


def test_command_never_runs_unsafe_native_commands(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)

    report = run_packet_batch_draft(source_id="SRC0018", packet_ids=MVP_PACKET_IDS, project_dir=tmp_path, config_path=config_path)

    commands = [command["command"] for command in report["commands_run"]]
    assert commands
    assert all("append-import" not in command or "--dry-run" in command for command in commands)
    forbidden = ["promote-output-workbook", "apply-approved-to-workbook", "approve-proposal", "reject-proposal", "defer-proposal", "--mark-exported"]
    assert not any(any(token in command for token in forbidden) for command in commands)


def test_agentflow_cli_packet_batch_draft_smoke(tmp_path: Path, capsys) -> None:
    config_path = _setup_project(tmp_path)
    _write_packets(tmp_path)

    exit_code = agentflow_main(
        [
            "packet-batch-draft",
            "--project-dir",
            str(tmp_path),
            "--config",
            str(config_path),
            "--source-id",
            "SRC0018",
            "--packet-id",
            "SRC0018-PKT-002",
            "--packet-id",
            "SRC0018-PKT-003",
            "--packet-id",
            "SRC0018-PKT-004",
        ]
    )

    assert exit_code == 0
    assert "Packet Batch Draft Report" in capsys.readouterr().out


def _setup_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["manual_imports"]["input_dir"] = str(tmp_path / "manual_imports")
    config["manual_imports"]["reports_dir"] = str(tmp_path / "reports" / "manual_imports")
    config["paths"]["reports_dir"] = str(tmp_path / "reports" / "workbook_inspection")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "missing.xlsx")
    config["prompt_packets"]["output_dir"] = str(tmp_path / "reports" / "prompt_packets")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    init_queues(tmp_path / "queues", config)
    (tmp_path / "manual_imports").mkdir(parents=True, exist_ok=True)
    _append_queue_row(
        tmp_path / "queues" / "source_dossiers.csv",
        "source_dossiers",
        {
            "source_id": "SRC0018",
            "source_type": "book",
            "title": "Reasonable Faith: Christian Truth and Apologetics",
            "author_or_speaker": "William Lane Craig",
            "processing_status": "registered",
        },
    )
    return config_path


def _write_packets(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "reports" / "prompt_packets"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for number in [2, 3, 4]:
        packet_id = f"SRC0018-PKT-{number:03d}"
        path = prompt_dir / f"SRC0018_schema_locked_packet_{number:02d}_fixture_2026-05-29_184837.md"
        path.write_text(_packet_text(packet_id), encoding="utf-8")


def _packet_text(packet_id: str) -> str:
    return "\n".join(
        [
            "# Schema-Locked Extraction Prompt Packet for SRC0018",
            "Your output will be parsed by a strict local CSV validator.",
            "Do not create simplified schemas. Use only the exact headers below.",
            "## Source Metadata",
            "- Source ID: SRC0018",
            "## Packet Metadata",
            f"- Packet ID: {packet_id}",
            "## Exact Schemas",
            "### extracted_claims",
            ",".join(QUEUE_SCHEMAS["extracted_claims"]),
            "### criteria_matrix",
            ",".join(QUEUE_SCHEMAS["criteria_matrix"]),
            "### proposed_updates",
            ",".join(QUEUE_SCHEMAS["proposed_updates"]),
            "## Source Text",
            "Apologetics is introduced as a rational justification for Christian truth claims.",
        ]
    )


def _write_csv(path: Path, queue_name: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[queue_name])
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[queue_name]})


def _append_queue_row(path: Path, queue_name: str, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[queue_name])
        writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[queue_name]})


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
