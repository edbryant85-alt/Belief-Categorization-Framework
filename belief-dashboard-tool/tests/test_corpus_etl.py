from __future__ import annotations

import json
from pathlib import Path

from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.corpus_etl import run_corpus_etl
from belief_dashboard_agentflows.policies import CommandRisk, resolve_command_policy


def test_local_archive_root_scan_detects_supported_candidates(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    for name in ["note.md", "transcript.txt", "watch_history.json", "items.jsonl", "table.csv"]:
        (archive / name).write_text("sample", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="scan")

    assert report["status"] == "passed"
    assert report["counts"]["candidate_files"] == 5
    assert {row["file_extension"] for row in report["candidate_sources"]} == {".md", ".txt", ".json", ".jsonl", ".csv"}


def test_prophecy_exclusion_is_aggressive(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "prophecy_test.md").write_text("excluded", encoding="utf-8")
    prophetic_dir = archive / "prophetic_notes"
    prophetic_dir.mkdir()
    (prophetic_dir / "sermon.txt").write_text("excluded", encoding="utf-8")
    (archive / "ordinary.md").write_text("included", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="prophecy")

    assert report["counts"]["candidate_files"] == 1
    assert report["counts"]["prophecy_excluded"] == 2
    assert all("prophe" not in row["relative_path"].lower() for row in report["candidate_sources"])


def test_allowed_file_type_filtering_counts_unsupported(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("supported", encoding="utf-8")
    (archive / "image.png").write_bytes(b"\x89PNG")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="types")

    assert report["counts"]["supported_text_files"] == 1
    assert report["counts"]["unsupported_files"] == 1


def test_large_file_metadata_only_behavior(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "large.txt").write_text("x" * 2048, encoding="utf-8")

    report = run_corpus_etl(
        archive_root=archive,
        corpus="youtube",
        mode="inventory",
        project_dir=tmp_path,
        run_id="large",
        large_file_threshold_mb=0,
        hash_threshold_mb=0,
    )

    candidate = report["candidate_sources"][0]
    assert candidate["content_status"] == "metadata_only_large_file"
    assert candidate["is_large_file"] is True
    assert candidate["hash_status"] == "skipped_large_file"


def test_candidate_manifest_writing_has_expected_headers(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="plan", project_dir=tmp_path, run_id="manifest")
    manifest = Path(report["output_files"]["candidate_sources_csv"])

    assert manifest.exists()
    headers = manifest.read_text(encoding="utf-8").splitlines()[0]
    assert "candidate_id" in headers
    assert "registered_match_status" in headers
    assert "recommended_next_action" in headers


def test_markdown_report_contains_safety_summary(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="markdown")
    markdown = Path(report["output_files"]["markdown_report"]).read_text(encoding="utf-8")

    assert "## Safety Summary" in markdown
    assert "no queues mutated" in markdown


def test_json_report_records_all_mutations_false(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="json")
    payload = json.loads(Path(report["output_files"]["json_report"]).read_text(encoding="utf-8"))

    assert payload["mutations"]
    assert all(value is False for value in payload["mutations"].values())


def test_review_pack_writes_human_review_inbox(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "sermon_intro.md").write_text("sample", encoding="utf-8")

    report = run_corpus_etl(archive_root=archive, corpus="mosaic", mode="review-pack", project_dir=tmp_path, run_id="review")

    inbox = Path(report["output_files"]["human_review_inbox"])
    assert inbox.exists()
    assert "Sources Needing Registration" in inbox.read_text(encoding="utf-8")


def test_background_safe_refuses_future_modes_without_mutation(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")

    report = run_corpus_etl(
        archive_root=archive,
        corpus="youtube",
        mode="append-approved",
        background_safe=True,
        project_dir=tmp_path,
        run_id="refuse",
    )

    assert report["status"] == "failed"
    assert "refuses" in report["refusal_reason"]
    assert all(value is False for value in report["mutations"].values())


def test_future_drive_provider_optional_unavailable_report(tmp_path: Path) -> None:
    report = run_corpus_etl(drive_folder_id="fake-folder", corpus="youtube", mode="inventory", project_dir=tmp_path, run_id="drive")

    assert report["status"] == "unavailable"
    assert Path(report["output_files"]["markdown_report"]).exists()
    assert report["mutations"]["raw_archive_copied"] is False


def test_command_policy_classification() -> None:
    spec = resolve_command_policy(["corpus-etl", "--corpus", "youtube", "--mode", "inventory"])

    assert spec.risk == CommandRisk.INTERMEDIATE_WRITE
    assert not spec.requires_human_confirmation


def test_no_queue_mutation(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")
    queues = tmp_path / "data" / "queues"
    queues.mkdir(parents=True)
    queue_file = queues / "source_dossiers.csv"
    queue_file.write_text("source_id,title,original_file_path\nSRC0001,Existing,source.md\n", encoding="utf-8")
    before = queue_file.read_text(encoding="utf-8")

    run_corpus_etl(archive_root=archive, corpus="youtube", mode="prepare", project_dir=tmp_path, run_id="queue")

    assert queue_file.read_text(encoding="utf-8") == before


def test_no_import_mutation(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")
    imports = tmp_path / "data" / "manual_imports" / "SRC0001_extracted_claims.csv"
    imports.parent.mkdir(parents=True)
    imports.write_text("claim_id,source_id,claim_text\nSRC0001-C001,SRC0001,Existing\n", encoding="utf-8")
    before = imports.read_text(encoding="utf-8")

    run_corpus_etl(archive_root=archive, corpus="youtube", mode="prepare", project_dir=tmp_path, run_id="imports")

    assert imports.read_text(encoding="utf-8") == before


def test_cli_inventory_smoke(tmp_path: Path, capsys) -> None:
    archive = _archive(tmp_path)
    (archive / "source.md").write_text("sample", encoding="utf-8")

    assert agentflow_main(["corpus-etl", "--archive-root", str(archive), "--corpus", "youtube", "--mode", "inventory", "--project-dir", str(tmp_path), "--run-id", "cli"]) == 0
    output = capsys.readouterr().out
    assert "Corpus ETL Report" in output


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    return archive
