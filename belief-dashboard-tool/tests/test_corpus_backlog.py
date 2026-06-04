from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.corpus_backlog import CORPUS_REGISTRY, run_corpus_backlog


def test_corpus_registry_includes_expected_corpora() -> None:
    assert {"mosaic", "youtube", "reasonable_faith", "general_theology"} <= set(CORPUS_REGISTRY)


def test_prophecy_files_are_excluded_when_out_of_scope(tmp_path: Path) -> None:
    _setup_backlog_project(tmp_path)
    prophecy = tmp_path / "data/raw_sources/clusters/christian_apologetics/prophecy_notes.md"
    prophecy.parent.mkdir(parents=True, exist_ok=True)
    prophecy.write_text("future project", encoding="utf-8")
    theology = tmp_path / "data/raw_sources/clusters/christian_apologetics/apologetics_notes.md"
    theology.write_text("current project", encoding="utf-8")

    report = run_corpus_backlog(
        corpora=["general_theology"],
        mode="inventory",
        background_safe=True,
        project_dir=tmp_path,
    )

    candidate_paths = {item["path"] for item in report["unregistered_candidates"]}
    assert "data/raw_sources/clusters/christian_apologetics/apologetics_notes.md" in candidate_paths
    assert "data/raw_sources/clusters/christian_apologetics/prophecy_notes.md" not in candidate_paths
    assert report["excluded_corpora"] == ["prophecy"]


def test_inventory_mode_creates_markdown_and_json_reports(tmp_path: Path) -> None:
    _setup_backlog_project(tmp_path)

    report = run_corpus_backlog(
        corpora=["mosaic"],
        mode="inventory",
        background_safe=True,
        project_dir=tmp_path,
    )

    markdown_path = Path(report["report_paths"]["markdown"])
    json_path = Path(report["report_paths"]["json"])
    assert markdown_path.exists()
    assert json_path.exists()
    assert "## Registered Sources" in markdown_path.read_text(encoding="utf-8")
    assert "## Unregistered Candidates" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "passed"


def test_reasonable_faith_state_detected_from_src0018(tmp_path: Path) -> None:
    _setup_backlog_project(tmp_path)

    report = run_corpus_backlog(
        corpora=["reasonable_faith"],
        mode="plan",
        background_safe=True,
        project_dir=tmp_path,
    )

    sources = report["registered_sources"]
    assert any(source["source_id"] == "SRC0018" for source in sources)
    assert report["packet_plans"][0]["source_id"] == "SRC0018"
    assert report["packet_plans"][0]["packet_count"] == 116


def test_generated_batch_artifacts_and_review_inbox_are_detected(tmp_path: Path) -> None:
    _setup_backlog_project(tmp_path)

    report = run_corpus_backlog(
        corpora=["reasonable_faith"],
        mode="report",
        background_safe=True,
        project_dir=tmp_path,
    )

    batch_paths = {batch["path"] for batch in report["generated_batches"]}
    assert "data/manual_imports/generated_batches/SRC0018_intro_apologetics" in batch_paths
    assert any(item["recommended_action"] == "human_review" for item in report["human_review_inbox"])
    assert any(item["recommended_action"] == "repair" for item in report["human_review_inbox"])


def test_runner_does_not_mutate_central_queues(tmp_path: Path) -> None:
    _setup_backlog_project(tmp_path)
    queue_file = tmp_path / "data/queues/source_dossiers.csv"
    before = queue_file.read_text(encoding="utf-8")

    run_corpus_backlog(
        corpora=["youtube"],
        mode="inventory",
        background_safe=True,
        project_dir=tmp_path,
    )

    assert queue_file.read_text(encoding="utf-8") == before


def test_cli_requires_background_safe_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup_backlog_project(tmp_path)

    exit_code = agentflow_main(
        [
            "corpus-backlog-runner",
            "--project-dir",
            str(tmp_path),
            "--corpus",
            "mosaic",
            "--mode",
            "inventory",
        ]
    )

    assert exit_code == 2
    assert "--background-safe" in capsys.readouterr().out


def _setup_backlog_project(tmp_path: Path) -> None:
    queues = tmp_path / "data/queues"
    queues.mkdir(parents=True, exist_ok=True)
    _write_csv(
        queues / "source_dossiers.csv",
        ["source_id", "source_type", "title", "author_or_speaker", "original_file_path", "context", "processing_status"],
        [
            {
                "source_id": "SRC0018",
                "source_type": "book",
                "title": "Reasonable Faith: Christian Truth and Apologetics",
                "author_or_speaker": "William Lane Craig",
                "original_file_path": "data/raw_sources/books/reasonable_faith.md",
                "context": "apologetics",
                "processing_status": "registered",
            },
            {
                "source_id": "SRC0002",
                "source_type": "youtube_transcript",
                "title": "Registered YouTube Transcript",
                "author_or_speaker": "Example Speaker",
                "original_file_path": "data/raw_sources/youtube_test_batch/registered_transcript.md",
                "context": "youtube",
                "processing_status": "registered",
            },
        ],
    )
    _write_csv(queues / "evidence_clusters.csv", ["cluster_id", "cluster_title", "status"], [])
    _write_csv(queues / "source_cluster_members.csv", ["cluster_id", "source_id"], [])
    _write_csv(queues / "proposed_updates.csv", ["proposal_id", "review_status"], [])

    youtube = tmp_path / "data/raw_sources/youtube_test_batch"
    youtube.mkdir(parents=True, exist_ok=True)
    (youtube / "registered_transcript.md").write_text("registered", encoding="utf-8")
    (youtube / "new_transcript.md").write_text("unregistered", encoding="utf-8")

    mosaic = tmp_path / "data/external/mosaic/manual_import/batch_001"
    mosaic.mkdir(parents=True, exist_ok=True)
    (mosaic / "mosaic_batch1_extracted_claims.csv").write_text("claim_id\n", encoding="utf-8")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/mosaic_sermon_workflow.md").write_text("# Mosaic", encoding="utf-8")

    batch = tmp_path / "data/manual_imports/generated_batches/SRC0018_intro_apologetics"
    batch.mkdir(parents=True, exist_ok=True)
    for suffix in ["extracted_claims", "criteria_matrix", "proposed_updates"]:
        (batch / f"SRC0018_intro_apologetics_{suffix}.csv").write_text("id\n", encoding="utf-8")

    repair_batch = tmp_path / "data/manual_imports/generated_batches/SRC0018_needs_repair"
    repair_batch.mkdir(parents=True, exist_ok=True)
    (repair_batch / "SRC0018_needs_repair_extracted_claims.csv").write_text("id\n", encoding="utf-8")

    plan_dir = tmp_path / "reports/source_packet_cycles"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "SRC0018_packet_cycle_plan_test.json").write_text(
        json.dumps({"source_id": "SRC0018", "source_title": "Reasonable Faith", "packet_count": 116}),
        encoding="utf-8",
    )

    logs = tmp_path / "reports/agentflow_runs/SRC0018_intro_apologetics/logs"
    logs.mkdir(parents=True, exist_ok=True)
    for name in ["validate_extracted_claims.log", "validate_criteria_matrix.log", "validate_proposed_updates.log"]:
        (logs / name).write_text("passed", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
