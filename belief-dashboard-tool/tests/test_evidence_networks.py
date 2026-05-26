from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import yaml
from openpyxl import Workbook

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.evidence_networks import build_evidence_clusters, build_source_network
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_evidence_clusters_works_and_includes_cluster_ids(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["evidence-clusters", "--config", str(config_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# Evidence Clusters" in output
    assert "HYP_EC" in output
    assert "CAT_Philosophical_argument" in output
    assert "No workbook or queue data was modified" in output


def test_evidence_clusters_filters_hypothesis_topic_and_category(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["evidence-clusters", "--config", str(config_path), "--hypothesis", "EC"]) == 0
    hypothesis_output = capsys.readouterr().out
    assert "HYP_EC" in hypothesis_output
    assert "HYP_N" not in hypothesis_output

    assert main(["evidence-clusters", "--config", str(config_path), "--topic", "sample"]) == 0
    topic_output = capsys.readouterr().out
    assert "Evidence Clusters" in topic_output
    assert "sample" in topic_output

    assert main(["evidence-clusters", "--config", str(config_path), "--category", "Philosophical argument"]) == 0
    category_output = capsys.readouterr().out
    assert "CAT_Philosophical_argument" in category_output


def test_evidence_cluster_type_filters(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    cases = [
        ("defeaters", "DEF_EC"),
        ("conflicts", "CONFLICT_EC"),
        ("salience", "SALIENCE_001"),
        ("uncertainty", "UNCERTAINTY_001"),
    ]
    for cluster_type, expected in cases:
        assert main(["evidence-clusters", "--config", str(config_path), "--cluster-type", cluster_type]) == 0
        output = capsys.readouterr().out
        assert expected in output


def test_cluster_ids_are_deterministic_and_conflicts_are_detected(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    first = build_evidence_clusters(config, tmp_path)
    second = build_evidence_clusters(config, tmp_path)

    assert [item["cluster_id"] for item in first["trace_appendix"]] == [item["cluster_id"] for item in second["trace_appendix"]]
    assert first["conflict_clusters"]
    assert first["conflict_clusters"][0]["cluster_id"] == "CONFLICT_EC"


def test_salience_is_separate_and_json_discord_save_work(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["evidence-clusters", "--config", str(config_path), "--cluster-type", "salience", "--long"]) == 0
    salience_output = capsys.readouterr().out
    assert "Salience is separate from evidential weight" in salience_output

    assert main(["evidence-clusters", "--config", str(config_path), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "evidence_clusters"
    assert result["cluster_summary"]["cluster_count"] > 0
    assert result["trace_appendix"]

    assert main(["evidence-clusters", "--config", str(config_path), "--discord"]) == 0
    discord = capsys.readouterr().out
    assert discord.startswith("Evidence Clusters")
    assert "Top clusters:" in discord

    assert main(["evidence-clusters", "--config", str(config_path), "--hypothesis", "EC", "--save"]) == 0
    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "evidence_networks"
    assert "Markdown report:" in output
    assert list(reports_dir.glob("evidence_clusters_EC_*.md"))
    assert list(reports_dir.glob("evidence_clusters_EC_*.json"))


def test_source_network_works_and_filters(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-network", "--config", str(config_path)]) == 0
    output = capsys.readouterr().out
    assert "# Source Network" in output
    assert "Source Centrality Summary" in output

    assert main(["source-network", "--config", str(config_path), "--hypothesis", "EC"]) == 0
    hypothesis_output = capsys.readouterr().out
    assert "EC" in hypothesis_output

    assert main(["source-network", "--config", str(config_path), "--topic", "sample"]) == 0
    topic_output = capsys.readouterr().out
    assert "sample" in topic_output


def test_source_network_centrality_maps_conflicts_and_priorities(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    first = build_source_network(config, tmp_path)
    second = build_source_network(config, tmp_path)

    assert [item["source_id"] for item in first["source_centrality_summary"]] == [item["source_id"] for item in second["source_centrality_summary"]]
    assert first["source_centrality_summary"][0]["source_id"] == "SRC0001"
    assert first["source_to_hypothesis_map"]
    assert first["apparent_source_conflicts"]
    assert first["source_study_priorities"]


def test_source_network_json_discord_and_save(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-network", "--config", str(config_path), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "source_network"
    assert result["source_centrality_summary"]
    assert result["trace_appendix"]

    assert main(["source-network", "--config", str(config_path), "--discord"]) == 0
    discord = capsys.readouterr().out
    assert discord.startswith("Source Network")
    assert "Most central sources:" in discord

    assert main(["source-network", "--config", str(config_path), "--hypothesis", "EC", "--save"]) == 0
    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "evidence_networks"
    assert "Markdown report:" in output
    assert list(reports_dir.glob("source_network_EC_*.md"))
    assert list(reports_dir.glob("source_network_EC_*.json"))


def test_evidence_network_commands_do_not_modify_workbooks_or_queues(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    queue_dir = Path(config["queues"]["base_dir"])
    workbook_before = _sha256(workbook)
    queues_before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["evidence-clusters", "--config", str(config_path)]) == 0
    assert main(["source-network", "--config", str(config_path)]) == 0

    assert _sha256(workbook) == workbook_before
    assert {path.name: _sha256(path) for path in queue_dir.glob("*.csv")} == queues_before


def _ready_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["evidence_networks"]["reports_dir"] = str(tmp_path / "reports" / "evidence_networks")
    Path(config["evidence_networks"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
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
            {"source_id": "SRC0001", "source_type": "book", "title": "Central Support Source", "author_or_speaker": "Author A", "short_summary": "sample support", "relevant_hypotheses": "EC,CT", "processing_status": "reviewed"},
            {"source_id": "SRC0002", "source_type": "article", "title": "Defeater Source", "author_or_speaker": "Author B", "short_summary": "sample challenge", "relevant_hypotheses": "EC,N", "processing_status": "reviewed"},
            {"source_id": "SRC0003", "source_type": "lecture", "title": "Mixed Source", "author_or_speaker": "Author C", "short_summary": "sample mixed", "relevant_hypotheses": "EC", "processing_status": "reviewed"},
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "claim_text": "sample support for EC", "claim_type": "evidence", "source_context": "sample context", "related_hypotheses": "EC", "uncertainty_notes": "uncertainty about scope"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "claim_text": "sample objection to EC", "claim_type": "objection", "source_context": "sample context", "related_hypotheses": "EC", "uncertainty_notes": "open question"},
            {"claim_id": "CLM0003", "source_id": "SRC0003", "claim_text": "sample mixed support", "claim_type": "argument", "source_context": "sample context", "related_hypotheses": "EC"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "claim_text": "sample mixed challenge", "claim_type": "objection", "source_context": "sample context", "related_hypotheses": "EC"},
        ],
    )
    _append_rows(
        queue_dir / "criteria_matrix.csv",
        QUEUE_SCHEMAS["criteria_matrix"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "relevance_0_5": "5", "reliability_0_5": "4", "argument_strength_0_5": "4", "explanatory_power_0_5": "4", "uncertainty_0_5": "4", "existential_salience_0_5": "5", "moral_stakes_0_5": "4", "emotional_salience_0_5": "4", "notes": "sample salience"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "relevance_0_5": "5", "defeater_strength_0_5": "5", "uncertainty_0_5": "5", "clarity_0_5": "2", "notes": "sample defeater"},
            {"claim_id": "CLM0003", "source_id": "SRC0003", "uncertainty_0_5": "4"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "defeater_strength_0_5": "4", "uncertainty_0_5": "4"},
        ],
    )
    _append_rows(
        queue_dir / "approved_updates.csv",
        QUEUE_SCHEMAS["approved_updates"],
        [
            {"proposal_id": "PROP0001", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "sample support for EC", "category": "Philosophical argument", "source_book": "Book A", "approved_weight_0_5": "5", "EC_MI5": "Highly likely", "CT_MI5": "Likely / probable", "approved_date": "2026-05-24"},
            {"proposal_id": "PROP0005", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "second sample support for EC", "category": "Philosophical argument", "source_book": "Book A", "approved_weight_0_5": "4", "EC_MI5": "Likely / probable", "approved_date": "2026-05-23"},
            {"proposal_id": "PROP0002", "claim_id": "CLM0002", "source_id": "SRC0002", "evidence_argument": "sample challenge to EC", "category": "Philosophical argument", "source_book": "Article B", "approved_weight_0_5": "4", "EC_MI5": "Highly unlikely", "N_MI5": "Likely / probable", "notes": "defeater", "approved_date": "2026-05-25"},
            {"proposal_id": "PROP0003", "claim_id": "CLM0003", "source_id": "SRC0003", "evidence_argument": "sample mixed support", "category": "Historical argument", "approved_weight_0_5": "3", "EC_MI5": "Likely / probable", "approved_date": "2026-05-22"},
            {"proposal_id": "PROP0004", "claim_id": "CLM0004", "source_id": "SRC0003", "evidence_argument": "sample mixed challenge", "category": "Historical argument", "approved_weight_0_5": "3", "EC_MI5": "Unlikely", "approved_date": "2026-05-21"},
        ],
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
