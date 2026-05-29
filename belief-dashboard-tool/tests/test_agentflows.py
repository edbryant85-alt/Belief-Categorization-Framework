from __future__ import annotations

import csv
from pathlib import Path

import yaml

from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.export_preflight import run_export_preflight
from belief_dashboard_agentflows.flows.extraction_qa import run_extraction_qa
from belief_dashboard_agentflows.flows.proposal_review_assistant import build_proposal_review_cards


def test_extraction_qa_valid_sample_passes(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_manual_imports(tmp_path, "SRC0001")

    report = run_extraction_qa("SRC0001", project_dir=tmp_path, config_path=config_path)

    assert report["status"] == "pass"
    assert not report["blockers"]
    assert all(command["risk"] in {"read_only"} for command in report["commands_run"])


def test_extraction_qa_missing_claim_reference_blocks(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_manual_imports(tmp_path, "SRC0001", proposal_claim_id="SRC0001-C999")

    report = run_extraction_qa("SRC0001", project_dir=tmp_path, config_path=config_path)

    assert report["status"] == "blocked"
    assert any("missing claim_id" in blocker for blocker in report["blockers"])


def test_proposal_review_cards_join_queue_metadata(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _append_queue_row(tmp_path / "queues" / "extracted_claims.csv", "extracted_claims", _claim_row("SRC0001"))
    _append_queue_row(tmp_path / "queues" / "criteria_matrix.csv", "criteria_matrix", _criteria_row("SRC0001"))
    _append_queue_row(tmp_path / "queues" / "proposed_updates.csv", "proposed_updates", _proposal_row("SRC0001"))

    report = build_proposal_review_cards(project_dir=tmp_path, config_path=config_path, source_id="SRC0001")

    assert report["status"] == "pass"
    assert len(report["cards"]) == 1
    card = report["cards"][0]
    assert card["proposal_id"] == "SRC0001-P001"
    assert card["claim_text"] == "A source-grounded claim."
    assert "relevance_0_5=4" in card["criteria_summary"]
    assert "EC: Likely / probable" in card["hypothesis_impact"]


def test_export_preflight_uses_read_only_commands_by_default(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    report = run_export_preflight(project_dir=tmp_path, config_path=config_path)

    assert all(command["risk"] == "read_only" for command in report["commands_run"])
    assert report["approved_row_count"] == 0


def test_flows_without_confirmation_do_not_modify_queues(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    _write_manual_imports(tmp_path, "SRC0001")
    queue_file = tmp_path / "queues" / "proposed_updates.csv"
    before = queue_file.read_text(encoding="utf-8")

    run_extraction_qa("SRC0001", project_dir=tmp_path, config_path=config_path)
    build_proposal_review_cards(project_dir=tmp_path, config_path=config_path)

    assert queue_file.read_text(encoding="utf-8") == before


def test_agentflow_cli_golden_path_smoke(tmp_path: Path, capsys) -> None:
    config_path = _setup_project(tmp_path)
    _write_manual_imports(tmp_path, "SRC0001")

    assert agentflow_main(["extraction-qa", "--project-dir", str(tmp_path), "--config", str(config_path), "--source-id", "SRC0001"]) == 0
    assert agentflow_main(["proposal-review-assistant", "--project-dir", str(tmp_path), "--config", str(config_path), "--source-id", "SRC0001"]) == 0
    assert agentflow_main(["export-preflight", "--project-dir", str(tmp_path), "--config", str(config_path)]) in {0, 1}

    output = capsys.readouterr().out
    assert "Extraction QA Report" in output
    assert "Proposal Review Assistant Report" in output
    assert "Export Preflight Report" in output


def test_confirmation_flags_are_reserved_and_report_only(tmp_path: Path, capsys) -> None:
    config_path = _setup_project(tmp_path)
    _write_manual_imports(tmp_path, "SRC0001")

    exit_code = agentflow_main(
        [
            "extraction-qa",
            "--project-dir",
            str(tmp_path),
            "--config",
            str(config_path),
            "--source-id",
            "SRC0001",
            "--confirm-guarded-write",
        ]
    )

    assert exit_code == 2
    assert "report-only" in capsys.readouterr().out


def _setup_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["manual_imports"]["input_dir"] = str(tmp_path / "manual_imports")
    config["manual_imports"]["reports_dir"] = str(tmp_path / "reports" / "manual_imports")
    config["paths"]["reports_dir"] = str(tmp_path / "reports" / "workbook_inspection")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "missing.xlsx")
    for section in ["doctor", "operator_preflight", "workbook_export"]:
        if section in config and "reports_dir" in config[section]:
            config[section]["reports_dir"] = str(tmp_path / "reports" / section)
    config["workbook_export"]["output_preview_dir"] = str(tmp_path / "reports" / "workbook_export_preview")
    config["workbook_export"]["final_reports_dir"] = str(tmp_path / "reports" / "workbook_exports")
    config["workbook_export"]["backups_dir"] = str(tmp_path / "backups")
    config["workbook_export"]["outputs_dir"] = str(tmp_path / "outputs")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    init_queues(tmp_path / "queues", config)
    (tmp_path / "manual_imports").mkdir(parents=True, exist_ok=True)
    _append_queue_row(tmp_path / "queues" / "source_dossiers.csv", "source_dossiers", {"source_id": "SRC0001", "title": "Example Source", "processing_status": "registered"})
    return config_path


def _write_manual_imports(tmp_path: Path, source_id: str, *, proposal_claim_id: str | None = None) -> None:
    manual = tmp_path / "manual_imports"
    _write_csv(manual / f"{source_id}_extracted_claims.csv", "extracted_claims", [_claim_row(source_id)])
    _write_csv(manual / f"{source_id}_criteria_matrix.csv", "criteria_matrix", [_criteria_row(source_id)])
    proposal = _proposal_row(source_id)
    if proposal_claim_id:
        proposal["claim_id"] = proposal_claim_id
    _write_csv(manual / f"{source_id}_proposed_updates.csv", "proposed_updates", [proposal])


def _claim_row(source_id: str) -> dict[str, str]:
    return {
        "claim_id": f"{source_id}-C001",
        "source_id": source_id,
        "claim_text": "A source-grounded claim.",
        "claim_type": "argument",
        "status": "proposed",
    }


def _criteria_row(source_id: str) -> dict[str, str]:
    return {
        "claim_id": f"{source_id}-C001",
        "source_id": source_id,
        "relevance_0_5": "4",
        "reliability_0_5": "4",
        "clarity_0_5": "4",
        "argument_strength_0_5": "3",
        "explanatory_power_0_5": "3",
        "scope_0_5": "3",
        "defeater_strength_0_5": "1",
        "uncertainty_0_5": "2",
    }


def _proposal_row(source_id: str) -> dict[str, str]:
    return {
        "proposal_id": f"{source_id}-P001",
        "claim_id": f"{source_id}-C001",
        "source_id": source_id,
        "evidence_argument": "A source-grounded claim affects the hypothesis.",
        "category": "Example",
        "source_book": "Example Source",
        "suggested_weight_0_5": "3",
        "EC_MI5": "Likely / probable",
        "notes": "Source-grounded.",
        "suggestion_rationale": "The claim is relevant but modest.",
        "uncertainty_notes": "Moderate uncertainty.",
        "review_status": "proposed",
    }


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
