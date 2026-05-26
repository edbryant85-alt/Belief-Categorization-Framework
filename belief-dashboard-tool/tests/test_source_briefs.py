from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.source_briefs import build_source_brief


def test_source_brief_produces_source_brief(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# Source Brief: SRC0001 - Source One" in output
    assert "No workbook or queue data was modified" in output


def test_source_brief_missing_source_id_fails_clearly(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["source-brief", "--config", str(config_path)])

    assert exc.value.code == 2
    assert "--source-id" in capsys.readouterr().err


def test_source_brief_unknown_source_id_fails_clearly(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC9999"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Unknown source ID: SRC9999" in output
    assert "register-source --file data/raw_sources/example.md" in output
    assert "queue-summary" in output


def test_source_metadata_claims_criteria_and_outcomes_appear(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--long"]) == 0

    output = capsys.readouterr().out
    assert "Author A" in output
    assert "CLM0001" in output
    assert "high relevance" in output
    assert "Proposed updates: 3" in output
    assert "Approved updates: 2" in output
    assert "Rejected updates: 1" in output
    assert "Deferred updates: 1" in output


def test_approved_hypothesis_impacts_are_summarized(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    result = build_source_brief(load_config(config_path), tmp_path, source_id="SRC0001")

    ec = next(item for item in result["approved_hypothesis_impacts"] if item["hypothesis_id"] == "EC")
    n = next(item for item in result["approved_hypothesis_impacts"] if item["hypothesis_id"] == "N")
    assert ec["classification_counts"]["strong_support"] == 1
    assert ec["classification_counts"]["moderate_support"] == 1
    assert n["classification_counts"]["moderate_challenge"] == 1
    assert ec["strongest_items"][0]["proposal_id"] == "PROP0001"


def test_unresolved_study_items_are_included_where_relevant(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    result = build_source_brief(load_config(config_path), tmp_path, source_id="SRC0001")

    reasons = " ".join(item["reason_for_study"] for item in result["unresolved_study_items"])
    assert "high uncertainty" in reasons or "deferred update" in reasons


def test_raw_excerpt_is_included_only_when_requested(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001"]) == 0
    default_output = capsys.readouterr().out
    assert "Raw source body" not in default_output

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--include-raw-excerpt"]) == 0
    included_output = capsys.readouterr().out
    assert "Raw source body" in included_output


def test_missing_raw_source_file_warns_without_failing(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path, missing_raw=True)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--include-raw-excerpt"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Raw source file not found" in output


def test_source_brief_format_json_returns_structured_data(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--format", "json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "source_brief"
    assert output["source_metadata"]["title"] == "Source One"
    assert output["criteria_highlights"]
    assert output["trace_appendix"]["claim_ids"]


def test_source_brief_discord_returns_compact_output(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--discord"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("Source Brief - SRC0001: Source One")
    assert "Top claims:" in output
    assert "Trace:" in output
    assert "## Trace Appendix" not in output


def test_short_produces_less_detail_than_long(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--short"]) == 0
    short_output = capsys.readouterr().out
    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--long"]) == 0
    long_output = capsys.readouterr().out

    assert len(short_output) < len(long_output)
    assert "source_context:" not in short_output
    assert "source_context:" in long_output


def test_source_brief_save_writes_markdown_and_json_reports(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001", "--save"])

    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "source_briefs"
    assert exit_code == 0
    assert "Markdown report:" in output
    assert list(reports_dir.glob("source_brief_SRC0001_*.md"))
    assert list(reports_dir.glob("source_brief_SRC0001_*.json"))


def test_source_brief_does_not_modify_workbooks(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    before = _sha256(workbook)

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001"]) == 0

    assert _sha256(workbook) == before


def test_source_brief_does_not_modify_queue_csv_files(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    queue_dir = Path(config["queues"]["base_dir"])
    before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["source-brief", "--config", str(config_path), "--source-id", "SRC0001"]) == 0

    after = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}
    assert after == before


def _ready_project(tmp_path: Path, *, missing_raw: bool = False) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["source_briefs"]["reports_dir"] = str(tmp_path / "reports" / "source_briefs")
    config["source_briefs"]["raw_excerpt_max_characters"] = 40
    Path(config["source_briefs"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
    _create_sample_workbook(Path(config["workbook"]["default_path"]))
    init_queues(tmp_path / "queues", config)
    raw_path = tmp_path / "raw" / "source_one.md"
    if not missing_raw:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text("Raw source body with enough extra words to truncate safely.", encoding="utf-8")
    _seed_rows(tmp_path / "queues", raw_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _seed_rows(queue_dir: Path, raw_path: Path) -> None:
    _append_rows(
        queue_dir / "source_dossiers.csv",
        QUEUE_SCHEMAS["source_dossiers"],
        [
            {
                "source_id": "SRC0001",
                "source_type": "book_notes",
                "title": "Source One",
                "author_or_speaker": "Author A",
                "date_added": "2026-05-26",
                "original_file_path": str(raw_path),
                "url": "https://example.test/source-one",
                "context": "Read for Phase 20 testing.",
                "short_summary": "A concise source summary.",
                "worldview_or_perspective": "Classical theist",
                "relevant_hypotheses": "EC,N",
                "reliability_notes": "Generally reliable.",
                "bias_or_framing_notes": "Has an apologetic frame.",
                "my_notes": "Important but needs precision.",
                "processing_status": "reviewed",
            }
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {
                "claim_id": "CLM0001",
                "source_id": "SRC0001",
                "claim_text": "A strong claim for EC.",
                "claim_type": "evidence",
                "argument_summary": "Supports EC.",
                "source_context": "Chapter one.",
                "related_hypotheses": "EC,N",
                "supports_hypotheses": "EC",
                "undermines_hypotheses": "N",
                "uncertainty_notes": "uncertainty about scope",
                "status": "ready",
            },
            {
                "claim_id": "CLM0002",
                "source_id": "SRC0001",
                "claim_text": "A lower-clarity claim that may be a defeater.",
                "claim_type": "objection",
                "argument_summary": "Raises an objection.",
                "source_context": "Chapter two.",
                "possible_defeater_for": "N",
                "uncertainty_notes": "open question",
                "status": "needs_review",
            },
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
                "clarity_0_5": "5",
                "argument_strength_0_5": "4",
                "explanatory_power_0_5": "4",
                "uncertainty_0_5": "4",
                "existential_salience_0_5": "5",
                "moral_stakes_0_5": "4",
                "emotional_salience_0_5": "4",
                "notes": "High salience is not evidential strength.",
            },
            {
                "claim_id": "CLM0002",
                "source_id": "SRC0001",
                "clarity_0_5": "2",
                "defeater_strength_0_5": "5",
                "uncertainty_0_5": "5",
            },
        ],
    )
    _append_rows(
        queue_dir / "proposed_updates.csv",
        QUEUE_SCHEMAS["proposed_updates"],
        [
            {"proposal_id": "PROP0001", "claim_id": "CLM0001", "source_id": "SRC0001", "evidence_argument": "Strong support for EC.", "review_status": "approved"},
            {"proposal_id": "PROP0002", "claim_id": "CLM0002", "source_id": "SRC0001", "evidence_argument": "Moderate support for EC.", "review_status": "approved"},
            {"proposal_id": "PROP0003", "claim_id": "CLM0002", "source_id": "SRC0001", "evidence_argument": "Unclear proposal.", "review_status": "deferred"},
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
                "approved_weight_0_5": "4.5",
                "EC_MI5": "Highly likely",
                "N_MI5": "Unlikely",
            },
            {
                "proposal_id": "PROP0002",
                "claim_id": "CLM0002",
                "source_id": "SRC0001",
                "evidence_argument": "Moderate support for EC.",
                "category": "Historical argument",
                "approved_weight_0_5": "3",
                "EC_MI5": "Likely / probable",
            },
        ],
    )
    _append_rows(
        queue_dir / "rejected_updates.csv",
        QUEUE_SCHEMAS["rejected_updates"],
        [{"proposal_id": "PROP0004", "claim_id": "CLM0002", "source_id": "SRC0001", "evidence_argument": "Bad proposal.", "rejection_reason": "duplicate"}],
    )
    _append_rows(
        queue_dir / "deferred_updates.csv",
        QUEUE_SCHEMAS["deferred_updates"],
        [{"proposal_id": "PROP0003", "claim_id": "CLM0002", "source_id": "SRC0001", "evidence_argument": "Unclear proposal.", "deferral_reason": "needs review"}],
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
