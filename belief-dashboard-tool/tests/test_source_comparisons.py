from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import yaml
from openpyxl import Workbook

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.source_comparisons import build_source_map


def test_compare_sources_source_id_flags_work(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["compare-sources", "--config", str(config_path), "--source-id", "SRC0001", "--source-id", "SRC0002"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# Source Comparison: SRC0001 vs SRC0002" in output
    assert "High-Level Comparison" in output


def test_compare_sources_comma_sources_work(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SRC0001 vs SRC0002" in output


def test_compare_sources_missing_or_insufficient_source_ids_fails(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["compare-sources", "--config", str(config_path), "--source-id", "SRC0001"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Supply at least two source IDs" in output


def test_compare_sources_unknown_source_id_fails(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC9999"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Unknown source ID(s): SRC9999" in output


def test_compare_sources_hypothesis_and_topic_filters(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--hypothesis", "EC"]) == 0
    hypothesis_output = capsys.readouterr().out
    assert "EC - Evangelical / Classical Christianity" in hypothesis_output
    assert "N - Naturalism" not in hypothesis_output

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--topic", "sample"]) == 0
    topic_output = capsys.readouterr().out
    assert "sample support for EC" in topic_output or "Potential tension on EC" in topic_output


def test_compare_sources_conflicts_shared_objections_criteria_and_study_items(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--long"]) == 0

    output = capsys.readouterr().out
    assert "Potential tension on EC" in output
    assert "Shared hypotheses: EC" in output
    assert "objection/defeater" in output
    assert "high defeater strength" in output
    assert "Study / Reflection Priorities" in output


def test_compare_sources_json_discord_and_save(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "compare_sources"
    assert result["conflict_map"]
    assert result["trace_appendix"]

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--discord"]) == 0
    discord = capsys.readouterr().out
    assert discord.startswith("Source Comparison - SRC0001 vs SRC0002")
    assert "Trace:" in discord
    assert "## Trace Appendix" not in discord

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002", "--save"]) == 0
    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "source_comparisons"
    assert "Markdown report:" in output
    assert list(reports_dir.glob("source_comparison_SRC0001_SRC0002_*.md"))
    assert list(reports_dir.glob("source_comparison_SRC0001_SRC0002_*.json"))


def test_source_map_hypothesis_and_topic_work(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-map", "--config", str(config_path), "--hypothesis", "EC"]) == 0
    hypothesis_output = capsys.readouterr().out
    assert "# Source Map: EC" in hypothesis_output
    assert "Source Ranking" in hypothesis_output

    assert main(["source-map", "--config", str(config_path), "--topic", "sample"]) == 0
    topic_output = capsys.readouterr().out
    assert "# Source Map: TOPIC sample" in topic_output
    assert "SRC0001" in topic_output


def test_source_map_requires_hypothesis_or_topic(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-map", "--config", str(config_path)])

    assert exit_code == 1
    assert "Supply --hypothesis HYPOTHESIS_ID" in capsys.readouterr().out


def test_source_map_ranking_and_groups_are_deterministic(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    first = build_source_map(config, tmp_path, hypothesis="EC")
    second = build_source_map(config, tmp_path, hypothesis="EC")

    assert [row["source_id"] for row in first["source_ranking"]] == [row["source_id"] for row in second["source_ranking"]]
    assert first["source_ranking"][0]["source_id"] == "SRC0001"
    assert {row["source_id"] for row in first["support_sources"]} >= {"SRC0001"}
    assert {row["source_id"] for row in first["challenge_sources"]} >= {"SRC0002"}
    assert {row["source_id"] for row in first["mixed_sources"]} >= {"SRC0003"}


def test_source_map_conflict_json_discord_and_save(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-map", "--config", str(config_path), "--hypothesis", "EC", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "source_map"
    assert result["conflict_map"]
    assert result["trace_appendix"]

    assert main(["source-map", "--config", str(config_path), "--hypothesis", "EC", "--discord"]) == 0
    discord = capsys.readouterr().out
    assert discord.startswith("Source Map - EC")
    assert "Top support source:" in discord
    assert "Top challenge source:" in discord

    assert main(["source-map", "--config", str(config_path), "--hypothesis", "EC", "--save"]) == 0
    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "source_comparisons"
    assert "Markdown report:" in output
    assert list(reports_dir.glob("source_map_EC_*.md"))
    assert list(reports_dir.glob("source_map_EC_*.json"))


def test_source_comparison_commands_do_not_modify_workbook_or_queues(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    queue_dir = Path(config["queues"]["base_dir"])
    workbook_before = _sha256(workbook)
    queues_before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["compare-sources", "--config", str(config_path), "--sources", "SRC0001,SRC0002"]) == 0
    assert main(["source-map", "--config", str(config_path), "--hypothesis", "EC"]) == 0

    assert _sha256(workbook) == workbook_before
    assert {path.name: _sha256(path) for path in queue_dir.glob("*.csv")} == queues_before


def _ready_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["source_comparisons"]["reports_dir"] = str(tmp_path / "reports" / "source_comparisons")
    Path(config["source_comparisons"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
    _create_sample_workbook(Path(config["workbook"]["default_path"]))
    init_queues(tmp_path / "queues", config)
    _seed_rows(tmp_path / "queues")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _seed_rows(queue_dir: Path) -> None:
    _append_rows(
        queue_dir / "source_dossiers.csv",
        QUEUE_SCHEMAS["source_dossiers"],
        [
            {"source_id": "SRC0001", "source_type": "book", "title": "Support Source", "author_or_speaker": "Author A", "date_added": "2026-05-26", "short_summary": "sample moral realism support", "relevant_hypotheses": "EC,CT", "processing_status": "reviewed"},
            {"source_id": "SRC0002", "source_type": "article", "title": "Challenge Source", "author_or_speaker": "Author B", "date_added": "2026-05-26", "short_summary": "sample challenge", "relevant_hypotheses": "EC,N", "processing_status": "reviewed"},
            {"source_id": "SRC0003", "source_type": "lecture", "title": "Mixed Source", "author_or_speaker": "Author C", "date_added": "2026-05-26", "short_summary": "mixed sample", "relevant_hypotheses": "EC", "processing_status": "reviewed"},
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "claim_text": "A sample support for EC.", "claim_type": "evidence", "source_context": "sample chapter", "related_hypotheses": "EC", "uncertainty_notes": "uncertainty about scope"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "claim_text": "A sample objection to EC.", "claim_type": "objection", "source_context": "sample essay", "related_hypotheses": "EC", "uncertainty_notes": "open question"},
            {"claim_id": "CLM0003", "source_id": "SRC0003", "claim_text": "A mixed sample claim for EC.", "claim_type": "argument", "source_context": "sample lecture", "related_hypotheses": "EC"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "claim_text": "A mixed sample challenge to EC.", "claim_type": "objection", "source_context": "sample lecture", "related_hypotheses": "EC"},
        ],
    )
    _append_rows(
        queue_dir / "criteria_matrix.csv",
        QUEUE_SCHEMAS["criteria_matrix"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "relevance_0_5": "5", "reliability_0_5": "4", "argument_strength_0_5": "4", "explanatory_power_0_5": "4", "uncertainty_0_5": "4", "existential_salience_0_5": "5", "moral_stakes_0_5": "4", "emotional_salience_0_5": "4", "notes": "sample criteria"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "relevance_0_5": "5", "defeater_strength_0_5": "5", "uncertainty_0_5": "5", "clarity_0_5": "2", "notes": "sample objection criteria"},
            {"claim_id": "CLM0003", "source_id": "SRC0003", "relevance_0_5": "4", "uncertainty_0_5": "4"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "defeater_strength_0_5": "4", "uncertainty_0_5": "4"},
        ],
    )
    _append_rows(
        queue_dir / "proposed_updates.csv",
        QUEUE_SCHEMAS["proposed_updates"],
        [
            {"proposal_id": "PROP0001", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "sample support for EC", "category": "Philosophical argument", "review_status": "approved"},
            {"proposal_id": "PROP0002", "claim_id": "CLM0002", "source_id": "SRC0002", "evidence_argument": "sample challenge to EC", "category": "Philosophical argument", "review_status": "approved"},
            {"proposal_id": "PROP0003", "claim_id": "CLM0003", "source_id": "SRC0003", "evidence_argument": "sample mixed support", "category": "Historical argument", "review_status": "approved"},
        ],
    )
    _append_rows(
        queue_dir / "approved_updates.csv",
        QUEUE_SCHEMAS["approved_updates"],
        [
            {"proposal_id": "PROP0001", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "sample support for EC", "category": "Philosophical argument", "source_book": "Book A", "approved_weight_0_5": "5", "EC_MI5": "Highly likely", "CT_MI5": "Likely / probable", "approved_date": "2026-05-24", "export_status": "exported"},
            {"proposal_id": "PROP0005", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "second sample support for EC", "category": "Philosophical argument", "source_book": "Book A", "approved_weight_0_5": "4", "EC_MI5": "Likely / probable", "approved_date": "2026-05-23"},
            {"proposal_id": "PROP0002", "claim_id": "CLM0002", "source_id": "SRC0002", "evidence_argument": "sample challenge to EC", "category": "Philosophical argument", "source_book": "Article B", "approved_weight_0_5": "4", "EC_MI5": "Highly unlikely", "N_MI5": "Likely / probable", "notes": "defeater", "approved_date": "2026-05-25"},
            {"proposal_id": "PROP0003", "claim_id": "CLM0003", "source_id": "SRC0003", "evidence_argument": "sample mixed support", "category": "Historical argument", "approved_weight_0_5": "3", "EC_MI5": "Likely / probable", "approved_date": "2026-05-22"},
            {"proposal_id": "PROP0004", "claim_id": "CLM0004", "source_id": "SRC0003", "evidence_argument": "sample mixed challenge", "category": "Historical argument", "approved_weight_0_5": "3", "EC_MI5": "Unlikely", "approved_date": "2026-05-21"},
        ],
    )
    _append_rows(
        queue_dir / "rejected_updates.csv",
        QUEUE_SCHEMAS["rejected_updates"],
        [{"proposal_id": "PROP0006", "claim_id": "CLM0002", "source_id": "SRC0002", "evidence_argument": "rejected sample", "rejection_reason": "duplicate"}],
    )
    _append_rows(
        queue_dir / "deferred_updates.csv",
        QUEUE_SCHEMAS["deferred_updates"],
        [{"proposal_id": "PROP0007", "claim_id": "CLM0002", "source_id": "SRC0002", "evidence_argument": "deferred sample", "deferral_reason": "needs review"}],
    )


def _append_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        for values in rows:
            row = {header: "" for header in headers}
            row.update(values)
            writer.writerow(row)


def _create_sample_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.save(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
