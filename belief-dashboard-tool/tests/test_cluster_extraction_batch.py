from __future__ import annotations

import csv
from pathlib import Path

import yaml

from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.cluster_extraction_batch import (
    run_cluster_extraction_batch,
    select_cluster_candidates,
)
from belief_dashboard_agentflows.policies import CommandRisk, resolve_command_policy


def test_candidate_selection_respects_cluster_membership() -> None:
    members = [_member("SRC0001", priority="5"), _member("SRC0002", priority="1")]

    selected, skipped = select_cluster_candidates(
        members,
        include_source_ids=[],
        limit=None,
        include_already_imported=False,
        imported_source_ids=set(),
        reviewed_source_ids=set(),
    )

    assert [row["source_id"] for row in selected] == ["SRC0001", "SRC0002"]
    assert skipped == []


def test_candidate_selection_respects_limit() -> None:
    members = [_member("SRC0001", priority="1"), _member("SRC0002", priority="5"), _member("SRC0003", priority="3")]

    selected, skipped = select_cluster_candidates(
        members,
        include_source_ids=[],
        limit=2,
        include_already_imported=False,
        imported_source_ids=set(),
        reviewed_source_ids=set(),
    )

    assert [row["source_id"] for row in selected] == ["SRC0002", "SRC0003"]
    assert skipped[0]["source_id"] == "SRC0001"
    assert skipped[0]["reason"] == "beyond limit"


def test_already_imported_sources_are_skipped_by_default() -> None:
    members = [_member("SRC0001"), _member("SRC0002")]

    selected, skipped = select_cluster_candidates(
        members,
        include_source_ids=[],
        limit=None,
        include_already_imported=False,
        imported_source_ids={"SRC0001"},
        reviewed_source_ids=set(),
    )

    assert [row["source_id"] for row in selected] == ["SRC0002"]
    assert skipped[0]["source_id"] == "SRC0001"
    assert skipped[0]["reason"] == "already imported"


def test_explicit_source_id_can_include_already_imported_source() -> None:
    members = [_member("SRC0001"), _member("SRC0002")]

    selected, skipped = select_cluster_candidates(
        members,
        include_source_ids=["SRC0001"],
        limit=None,
        include_already_imported=False,
        imported_source_ids={"SRC0001"},
        reviewed_source_ids=set(),
    )

    assert [row["source_id"] for row in selected] == ["SRC0001"]
    assert skipped[0]["source_id"] == "SRC0002"


def test_prepare_mode_creates_workspace_without_appending(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)
    queue_file = tmp_path / "queues" / "extracted_claims.csv"
    before = queue_file.read_text(encoding="utf-8")

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        limit=1,
        mode="prepare",
        save=False,
    )

    source = report["sources"][0]
    assert source["workspace_generation_status"] == "pass"
    assert source["workspace_exists"] is True
    assert (tmp_path / "manual_imports" / "templates" / "SRC0001_extracted_claims_template.csv").exists()
    assert queue_file.read_text(encoding="utf-8") == before
    assert not any(command["command"].startswith("append-import") for command in report["commands_run"])


def test_report_mode_does_not_mutate_files(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)
    before = _file_inventory(tmp_path)

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        mode="report",
        save=False,
    )

    assert report["mode"] == "report"
    assert _file_inventory(tmp_path) == before


def test_dry_run_mode_never_calls_real_append(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)
    _write_valid_imports(tmp_path, "SRC0001")

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        source_ids=["SRC0001"],
        mode="dry-run",
        save=False,
    )

    append_commands = [command["command"] for command in report["commands_run"] if command["command"].startswith("append-import")]
    assert append_commands
    assert all("--dry-run" in command for command in append_commands)


def test_missing_csvs_are_reported_clearly(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        source_ids=["SRC0001"],
        mode="report",
        save=False,
    )

    source = report["sources"][0]
    assert source["all_import_csvs_exist"] is False
    assert source["shape_diagnosis_status"] == "missing"


def test_wrong_shape_csvs_are_reported_clearly(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)
    bad = tmp_path / "manual_imports" / "SRC0001_extracted_claims.csv"
    bad.write_text("claim_id,source_id\nSRC0001-C001,SRC0001\n", encoding="utf-8")

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        source_ids=["SRC0001"],
        mode="report",
        save=False,
    )

    source = report["sources"][0]
    assert source["shape_diagnosis_status"] == "fail"
    assert source["shape_diagnosis"]["extracted_claims"]["overall_status"] == "fail"


def test_generated_markdown_report_includes_source_status(tmp_path: Path) -> None:
    config_path = _setup_cluster_project(tmp_path)

    report = run_cluster_extraction_batch(
        cluster_id="CLUST-TEST-001",
        project_dir=tmp_path,
        config_path=config_path,
        source_ids=["SRC0001"],
        mode="report",
        save=True,
    )

    markdown = Path(report["markdown_report_path"]).read_text(encoding="utf-8")
    assert "Cluster Extraction Batch Report" in markdown
    assert "SRC0001" in markdown
    assert "Recommended next action" in markdown


def test_cluster_extraction_batch_policy_is_read_only() -> None:
    spec = resolve_command_policy(["cluster-extraction-batch", "--cluster-id", "CLUST-TEST-001"])

    assert spec.risk == CommandRisk.READ_ONLY


def test_cluster_extraction_batch_cli_smoke(tmp_path: Path, capsys) -> None:
    config_path = _setup_cluster_project(tmp_path)

    exit_code = agentflow_main(
        [
            "cluster-extraction-batch",
            "--project-dir",
            str(tmp_path),
            "--config",
            str(config_path),
            "--cluster-id",
            "CLUST-TEST-001",
            "--limit",
            "1",
            "--mode",
            "report",
        ]
    )

    assert exit_code == 0
    assert "Cluster Extraction Batch Report" in capsys.readouterr().out


def _setup_cluster_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["manual_imports"]["input_dir"] = str(tmp_path / "manual_imports")
    config["manual_imports"]["reports_dir"] = str(tmp_path / "reports" / "manual_imports")
    config["prompt_packets"]["output_dir"] = str(tmp_path / "reports" / "prompt_packets")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    init_queues(tmp_path / "queues", config)
    (tmp_path / "manual_imports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    _write_source(tmp_path, "SRC0001")
    _write_source(tmp_path, "SRC0002")
    _append_queue_row(
        tmp_path / "queues" / "evidence_clusters.csv",
        "evidence_clusters",
        {"cluster_id": "CLUST-TEST-001", "cluster_title": "Test Cluster", "core_question": "What follows?"},
    )
    _append_queue_row(tmp_path / "queues" / "source_dossiers.csv", "source_dossiers", _source_row("SRC0001"))
    _append_queue_row(tmp_path / "queues" / "source_dossiers.csv", "source_dossiers", _source_row("SRC0002"))
    _append_queue_row(tmp_path / "queues" / "source_cluster_members.csv", "source_cluster_members", _member("SRC0001", priority="5"))
    _append_queue_row(tmp_path / "queues" / "source_cluster_members.csv", "source_cluster_members", _member("SRC0002", priority="1"))
    return config_path


def _member(source_id: str, *, priority: str = "3") -> dict[str, str]:
    return {
        "cluster_id": "CLUST-TEST-001",
        "source_id": source_id,
        "source_role": "core_argument",
        "relevance_0_5": "4",
        "priority_0_5": priority,
        "status": "active",
    }


def _source_row(source_id: str) -> dict[str, str]:
    return {
        "source_id": source_id,
        "source_type": "article",
        "title": f"Source {source_id}",
        "original_file_path": f"raw/{source_id}.md",
        "processing_status": "registered",
    }


def _write_source(tmp_path: Path, source_id: str) -> None:
    (tmp_path / "raw" / f"{source_id}.md").write_text(f"# Source {source_id}\n\nA source-grounded claim.", encoding="utf-8")


def _write_valid_imports(tmp_path: Path, source_id: str) -> None:
    _write_csv(tmp_path / "manual_imports" / f"{source_id}_extracted_claims.csv", "extracted_claims", [_claim_row(source_id)])
    _write_csv(tmp_path / "manual_imports" / f"{source_id}_criteria_matrix.csv", "criteria_matrix", [_criteria_row(source_id)])
    _write_csv(tmp_path / "manual_imports" / f"{source_id}_proposed_updates.csv", "proposed_updates", [_proposal_row(source_id)])


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
        "source_book": f"Source {source_id}",
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


def _file_inventory(tmp_path: Path) -> list[str]:
    return sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*") if path.is_file())
