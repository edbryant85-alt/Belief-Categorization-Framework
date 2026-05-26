from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import yaml
from openpyxl import Workbook

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.debate_summaries import build_debate_summary
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_debate_summary_hypothesis_produces_readable_summary(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hypothesis: EC - Evangelical / Classical Christianity" in output
    assert "Strongest supporting evidence:" in output
    assert "PROP0001" in output


def test_debate_summary_all_produces_all_configured_hypotheses(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--all", "--short"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hypothesis: EC" in output
    assert "Hypothesis: N" in output


def test_debate_summary_requires_hypothesis_or_all(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path)])

    assert exit_code == 1
    assert "Supply either --hypothesis HYPOTHESIS_ID or --all" in capsys.readouterr().out


def test_debate_summary_unknown_hypothesis_fails_clearly(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--hypothesis", "ZZ"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Unknown hypothesis ID: ZZ" in output


def test_support_challenge_classification_and_defeater_detection(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_debate_summary(config, tmp_path, hypothesis="EC")
    summary = result["hypotheses"][0]

    support_item = next(item for item in summary["support_items"] if item["proposal_id"] == "PROP0001")
    assert support_item["classification"] == "strong_support"
    assert any(item["proposal_id"] == "PROP0002" for item in summary["challenge_items"])
    assert any(item["proposal_id"] == "PROP0002" for item in summary["defeaters"])


def test_ranking_uses_weight_then_impact_then_date_then_proposal_id(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_debate_summary(config, tmp_path, hypothesis="EC")
    ids = [item["proposal_id"] for item in result["hypotheses"][0]["support_items"]]

    assert ids[:3] == ["PROP0004", "PROP0001", "PROP0003"]


def test_min_weight_filter_excludes_lower_weight_rows(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_debate_summary(config, tmp_path, hypothesis="EC", min_weight=4.6)

    ids = _all_item_ids(result)
    assert "PROP0001" not in ids
    assert "PROP0004" in ids


def test_exported_only_filters_to_exported_rows(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_debate_summary(config, tmp_path, hypothesis="EC", exported_only=True)

    ids = _all_item_ids(result)
    assert "PROP0001" in ids
    assert "PROP0004" not in ids


def test_source_id_and_category_filters(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    source_result = build_debate_summary(config, tmp_path, hypothesis="EC", source_id="SRC0002")
    category_result = build_debate_summary(config, tmp_path, hypothesis="EC", category="objection")

    assert _all_item_ids(source_result) == {"PROP0002"}
    assert _all_item_ids(category_result) == {"PROP0002"}


def test_debate_summary_format_json_returns_structured_output(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC", "--format", "json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "debate_summary"
    assert output["hypotheses"][0]["support_items"]
    assert output["hypotheses"][0]["challenge_items"]


def test_debate_summary_save_writes_markdown_and_json_reports(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC", "--save"])

    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "debate_summaries"
    assert exit_code == 0
    assert "Markdown report:" in output
    assert list(reports_dir.glob("debate_summary_EC_*.md"))
    assert list(reports_dir.glob("debate_summary_EC_*.json"))


def test_debate_summary_discord_format_is_compact(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC", "--discord"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Top support:" in output
    assert "Top challenge:" in output
    assert "Debate angle:" in output


def test_criteria_matrix_data_is_joined_and_surfaced(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_debate_summary(config, tmp_path, hypothesis="EC")
    item = next(item for item in result["hypotheses"][0]["support_items"] if item["proposal_id"] == "PROP0001")

    assert item["source_title"] == "Source One"
    assert item["claim_type"] == "evidence"
    assert item["criteria_scores"]["relevance_0_5"] == "5"
    assert "high existential salience" in item["salience_flags"]


def test_debate_summary_does_not_modify_workbooks(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    before = _sha256(workbook)

    assert main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC"]) == 0

    assert _sha256(workbook) == before


def test_debate_summary_does_not_modify_queue_csv_files(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    queue_dir = Path(config["queues"]["base_dir"])
    before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["debate-summary", "--config", str(config_path), "--hypothesis", "EC"]) == 0

    after = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}
    assert after == before


def _ready_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["debate_summaries"]["reports_dir"] = str(tmp_path / "reports" / "debate_summaries")
    Path(config["debate_summaries"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
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
            {"source_id": "SRC0001", "title": "Source One"},
            {"source_id": "SRC0002", "title": "Source Two"},
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "claim_text": "A strong case for EC.", "claim_type": "evidence"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "claim_text": "An objection to EC.", "claim_type": "objection", "uncertainty_notes": "open question about assumptions"},
            {"claim_id": "CLM0003", "source_id": "SRC0001", "claim_text": "A moderate case for EC.", "claim_type": "argument"},
            {"claim_id": "CLM0004", "source_id": "SRC0001", "claim_text": "A newer strong case for EC.", "claim_type": "evidence"},
        ],
    )
    _append_rows(
        queue_dir / "criteria_matrix.csv",
        QUEUE_SCHEMAS["criteria_matrix"],
        [
            {
                "claim_id": "CLM0001",
                "source_id": "SRC0001",
                "relevance_0_5": "5",
                "reliability_0_5": "4",
                "argument_strength_0_5": "4",
                "explanatory_power_0_5": "4",
                "existential_salience_0_5": "5",
                "emotional_salience_0_5": "4",
            }
        ],
    )
    _append_rows(
        queue_dir / "approved_updates.csv",
        QUEUE_SCHEMAS["approved_updates"],
        [
            {
                "proposal_id": "PROP0001",
                "claim_id": "CLM0001",
                "source_id": "SRC0001",
                "evidence_argument": "Strong support for EC.",
                "category": "Philosophical argument",
                "source_book": "Book A",
                "approved_weight_0_5": "4.5",
                "EC_MI5": "Highly likely",
                "N_MI5": "Unlikely",
                "approved_date": "2026-05-20",
                "export_status": "exported",
            },
            {
                "proposal_id": "PROP0002",
                "claim_id": "CLM0002",
                "source_id": "SRC0002",
                "evidence_argument": "A serious objection against EC.",
                "category": "Objection / defeater",
                "source_book": "Book B",
                "approved_weight_0_5": "4.0",
                "EC_MI5": "Highly unlikely",
                "N_MI5": "Likely / probable",
                "notes": "defeater and open question",
                "approved_date": "2026-05-22",
            },
            {
                "proposal_id": "PROP0003",
                "claim_id": "CLM0003",
                "source_id": "SRC0001",
                "evidence_argument": "Moderate support for EC.",
                "category": "Historical argument",
                "source_book": "Book C",
                "approved_weight_0_5": "4.5",
                "EC_MI5": "Likely / probable",
                "N_MI5": "Unlikely",
                "approved_date": "2026-05-23",
            },
            {
                "proposal_id": "PROP0004",
                "claim_id": "CLM0004",
                "source_id": "SRC0001",
                "evidence_argument": "Highest weighted support for EC.",
                "category": "Philosophical argument",
                "source_book": "Book D",
                "approved_weight_0_5": "5",
                "EC_MI5": "Highly likely",
                "N_MI5": "Remote chance",
                "approved_date": "2026-05-24",
            },
        ],
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


def _all_item_ids(result: dict) -> set[str]:
    summary = result["hypotheses"][0]
    ids = set()
    for key in ["support_items", "challenge_items", "neutral_items", "defeaters", "open_questions"]:
        ids.update(item["proposal_id"] for item in summary[key])
    return ids


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
