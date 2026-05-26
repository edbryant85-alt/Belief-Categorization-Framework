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
from belief_dashboard.study_queue import build_study_queue


def test_study_queue_works_with_default_general_mode(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["study-queue", "--config", str(config_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Study Queue" in output
    assert "Top Study Items:" in output
    assert "PROP0001" in output


def test_study_queue_hypothesis_filters_by_hypothesis(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, hypothesis="EC", include_reflections=False)

    ids = _item_ids(result)
    assert "PROP0001" in ids
    assert "PROP0004" not in ids


def test_study_queue_all_includes_all_configured_hypotheses(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, all_hypotheses=True, include_reflections=False)

    assert result["filters"]["all"] is True
    assert "PROP0004" in _item_ids(result)


def test_study_queue_topic_filters_by_text(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, topic="sample", include_reflections=False)

    ids = _item_ids(result)
    assert "PROP0001" in ids
    assert "PROP0002" not in ids


def test_study_queue_min_priority_filters_low_priority_rows(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, min_priority=8, include_reflections=False)

    assert all(item["priority_score"] >= 8 for item in result["study_items"])


def test_study_queue_source_and_category_filters(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    source_result = build_study_queue(config, tmp_path, source_id="SRC0002", include_reflections=False)
    category_result = build_study_queue(config, tmp_path, category="Philosophical argument", include_reflections=False)

    assert _item_ids(source_result) == {"PROP0002"}
    assert "PROP0001" in _item_ids(category_result)


def test_priority_scoring_is_deterministic(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    first = build_study_queue(config, tmp_path, include_reflections=False)
    second = build_study_queue(config, tmp_path, include_reflections=False)

    assert [item["study_item_id"] for item in first["study_items"]] == [
        item["study_item_id"] for item in second["study_items"]
    ]


def test_uncertainty_defeater_salience_and_low_clarity_are_surfaced(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, include_reflections=False)

    assert any("high uncertainty" in item["reason_for_study"] for item in result["study_items"])
    assert any(item["proposal_id"] == "PROP0002" for item in result["unresolved_defeaters"])
    assert any(item["proposal_id"] == "PROP0001" for item in result["high_salience_items"])
    assert any(item["proposal_id"] == "PROP0003" for item in result["low_clarity_items"])


def test_deferred_updates_and_next_actions_are_included(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, include_deferred=True, include_reflections=False)

    assert any(item["source_kind"] == "deferred_update" for item in result["deferred_items"])
    assert all(item["suggested_next_action"] for item in result["study_items"])


def test_trace_ids_are_included(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    result = build_study_queue(config, tmp_path, include_reflections=False)

    item = result["study_items"][0]
    assert item["study_item_id"]
    assert item["trace_summary"]
    assert result["trace_appendix"][0]["source_id"]


def test_study_queue_format_json_returns_structured_output(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["study-queue", "--config", str(config_path), "--format", "json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "study_queue"
    assert output["study_items"]
    assert output["priority_summary"]


def test_study_queue_discord_returns_compact_output(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["study-queue", "--config", str(config_path), "--discord"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("Study Queue - Top Priorities")
    assert "Why:" in output
    assert "Trace Appendix:" not in output


def test_study_queue_save_writes_markdown_and_json_reports(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["study-queue", "--config", str(config_path), "--hypothesis", "EC", "--save"])

    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "study_queue"
    assert exit_code == 0
    assert "Markdown report:" in output
    assert list(reports_dir.glob("study_queue_EC_*.md"))
    assert list(reports_dir.glob("study_queue_EC_*.json"))


def test_study_queue_does_not_modify_workbooks(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    before = _sha256(workbook)

    assert main(["study-queue", "--config", str(config_path)]) == 0

    assert _sha256(workbook) == before


def test_study_queue_does_not_modify_queue_csv_files(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    queue_dir = Path(config["queues"]["base_dir"])
    before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["study-queue", "--config", str(config_path)]) == 0

    after = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}
    assert after == before


def _ready_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["study_queue"]["reports_dir"] = str(tmp_path / "reports" / "study_queue")
    Path(config["study_queue"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
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
            {"source_id": "SRC0001", "title": "Sample Source One", "short_summary": "sample source", "processing_status": "reviewed"},
            {"source_id": "SRC0002", "title": "Defeater Source", "short_summary": "challenge source", "processing_status": "reviewed"},
            {"source_id": "SRC0003", "title": "Naturalism Source", "short_summary": "naturalism source", "processing_status": "reviewed"},
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "claim_text": "Sample high salience claim.", "claim_type": "evidence", "related_hypotheses": "EC"},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "claim_text": "Defeater claim.", "claim_type": "objection", "uncertainty_notes": "open question about premise", "related_hypotheses": "EC"},
            {"claim_id": "CLM0003", "source_id": "SRC0001", "claim_text": "Low clarity claim.", "claim_type": "argument", "related_hypotheses": "EC"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "claim_text": "Naturalism uncertainty claim.", "claim_type": "evidence", "related_hypotheses": "N"},
        ],
    )
    _append_rows(
        queue_dir / "criteria_matrix.csv",
        QUEUE_SCHEMAS["criteria_matrix"],
        [
            {
                "claim_id": "CLM0001",
                "source_id": "SRC0001",
                "uncertainty_0_5": "4",
                "relevance_0_5": "5",
                "existential_salience_0_5": "5",
                "moral_stakes_0_5": "4",
                "emotional_salience_0_5": "4",
            },
            {"claim_id": "CLM0002", "source_id": "SRC0002", "defeater_strength_0_5": "5", "uncertainty_0_5": "4"},
            {"claim_id": "CLM0003", "source_id": "SRC0001", "clarity_0_5": "2", "uncertainty_0_5": "4"},
            {"claim_id": "CLM0004", "source_id": "SRC0003", "uncertainty_0_5": "4"},
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
                "evidence_argument": "Sample high salience support for EC.",
                "category": "Philosophical argument",
                "source_book": "Book A",
                "approved_weight_0_5": "4.5",
                "EC_MI5": "Highly likely",
                "N_MI5": "Unlikely",
                "notes": "uncertainty about framing",
            },
            {
                "proposal_id": "PROP0002",
                "claim_id": "CLM0002",
                "source_id": "SRC0002",
                "evidence_argument": "Possible defeater for EC.",
                "category": "Objection / defeater",
                "source_book": "Book B",
                "approved_weight_0_5": "4",
                "EC_MI5": "Highly unlikely",
                "notes": "defeater and open question",
            },
            {
                "proposal_id": "PROP0003",
                "claim_id": "CLM0003",
                "source_id": "SRC0001",
                "evidence_argument": "Important but unclear EC argument.",
                "category": "Philosophical argument",
                "source_book": "Book C",
                "approved_weight_0_5": "2",
                "EC_MI5": "Likely / probable",
            },
            {
                "proposal_id": "PROP0004",
                "claim_id": "CLM0004",
                "source_id": "SRC0003",
                "evidence_argument": "Naturalism item with uncertainty.",
                "category": "Scientific argument",
                "source_book": "Book D",
                "approved_weight_0_5": "3",
                "N_MI5": "Likely / probable",
            },
        ],
    )
    _append_rows(
        queue_dir / "deferred_updates.csv",
        QUEUE_SCHEMAS["deferred_updates"],
        [
            {
                "proposal_id": "PROP0005",
                "claim_id": "CLM0001",
                "source_id": "SRC0001",
                "evidence_argument": "Deferred sample follow-up.",
                "deferral_reason": "needs review",
                "revisit_date": "2026-06-01",
            }
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


def _item_ids(result: dict) -> set[str]:
    return {item["proposal_id"] for item in result["study_items"] if item["proposal_id"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
