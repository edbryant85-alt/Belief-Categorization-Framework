from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import yaml
from openpyxl import Workbook

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.debate_packets import build_debate_packet, render_debate_packet
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_debate_packet_hypothesis_produces_packet(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# Debate Packet: EC" in output
    assert "## Strongest Supporting Evidence" in output
    assert "## Trace Appendix" in output


def test_debate_packet_topic_produces_topic_filtered_packet(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--topic", "sample"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Topic: `sample`" in output
    assert "PROP0001" in output
    assert "PROP0002" not in output


def test_debate_packet_requires_hypothesis_or_topic(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path)])

    assert exit_code == 1
    assert "Supply --hypothesis HYPOTHESIS_ID" in capsys.readouterr().out


def test_debate_packet_unknown_hypothesis_fails_clearly(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--hypothesis", "ZZ"])

    assert exit_code == 1
    assert "Unknown hypothesis ID: ZZ" in capsys.readouterr().out


def test_combined_hypothesis_and_topic_filters_work(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    packet = build_debate_packet(config, tmp_path, hypothesis="EC", topic="moral realism support")

    ids = {item["proposal_id"] for item in packet["trace_appendix"]}
    assert ids == {"PROP0001"}


def test_support_challenge_objection_and_counter_sections(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    packet = build_debate_packet(config, tmp_path, hypothesis="EC")

    assert any(item["proposal_id"] == "PROP0001" for item in packet["support_items"])
    assert any(item["proposal_id"] == "PROP0002" for item in packet["challenge_items"])
    assert any(item["proposal_id"] == "PROP0002" for item in packet["objections"])
    assert any(item["proposal_id"] == "PROP0003" for item in packet["counter_objections"])


def test_criteria_highlights_source_trace_and_appendix_are_included(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)

    packet = build_debate_packet(config, tmp_path, hypothesis="EC")

    assert any(item["proposal_id"] == "PROP0001" for item in packet["criteria_highlights"])
    assert any(item["source_id"] == "SRC0001" and item["title"] == "Sample Source One" for item in packet["source_trace"])
    assert any(item["proposal_id"] == "PROP0001" and item["claim_id"] == "CLM0001" for item in packet["trace_appendix"])


def test_debate_packet_format_json_returns_structured_packet(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC", "--format", "json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["operation"] == "debate_packet"
    assert output["support_items"]
    assert output["discord_section"]
    assert output["trace_appendix"]


def test_debate_packet_discord_returns_compact_text(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC", "--discord"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("Debate packet: EC")
    assert "Top support:" in output
    assert "Discussion question:" in output
    assert "## Trace Appendix" not in output


def test_short_produces_less_detail_than_long(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    packet = build_debate_packet(config, tmp_path, hypothesis="EC")

    short_text = render_debate_packet(packet, length="short")
    long_text = render_debate_packet(packet, length="long")

    assert len(long_text) > len(short_text)
    assert "claim:" in long_text


def test_debate_packet_save_writes_markdown_and_json_reports(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC", "--save"])

    output = capsys.readouterr().out
    reports_dir = tmp_path / "reports" / "debate_packets"
    assert exit_code == 0
    assert "Markdown report:" in output
    assert list(reports_dir.glob("debate_packet_EC_*.md"))
    assert list(reports_dir.glob("debate_packet_EC_*.json"))


def test_topic_save_filename_is_slugged(tmp_path: Path, capsys) -> None:
    config_path = _ready_project(tmp_path)

    exit_code = main(["debate-packet", "--config", str(config_path), "--topic", "moral realism", "--save"])

    reports_dir = tmp_path / "reports" / "debate_packets"
    assert exit_code == 0
    assert list(reports_dir.glob("debate_packet_TOPIC_moral_realism_*.md"))


def test_debate_packet_does_not_modify_workbooks(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    workbook = Path(config["workbook"]["default_path"])
    before = _sha256(workbook)

    assert main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC"]) == 0

    assert _sha256(workbook) == before


def test_debate_packet_does_not_modify_queue_csv_files(tmp_path: Path) -> None:
    config_path = _ready_project(tmp_path)
    config = load_config(config_path)
    queue_dir = Path(config["queues"]["base_dir"])
    before = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}

    assert main(["debate-packet", "--config", str(config_path), "--hypothesis", "EC"]) == 0

    after = {path.name: _sha256(path) for path in queue_dir.glob("*.csv")}
    assert after == before


def _ready_project(tmp_path: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = str(tmp_path / "workbooks" / "main.xlsx")
    config["queues"]["base_dir"] = str(tmp_path / "queues")
    config["debate_summaries"]["reports_dir"] = str(tmp_path / "reports" / "debate_summaries")
    config["debate_packets"]["reports_dir"] = str(tmp_path / "reports" / "debate_packets")
    Path(config["debate_packets"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
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
            {
                "source_id": "SRC0001",
                "source_type": "book_notes",
                "title": "Sample Source One",
                "author_or_speaker": "Author A",
                "url": "https://example.com/one",
                "short_summary": "sample moral realism source",
                "processing_status": "reviewed",
            },
            {
                "source_id": "SRC0002",
                "source_type": "article",
                "title": "Objection Source",
                "author_or_speaker": "Author B",
                "short_summary": "challenge source",
                "processing_status": "reviewed",
            },
        ],
    )
    _append_rows(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        [
            {"claim_id": "CLM0001", "source_id": "SRC0001", "claim_text": "Sample support claim.", "claim_type": "evidence", "source_context": "Longer sample context."},
            {"claim_id": "CLM0002", "source_id": "SRC0002", "claim_text": "Challenge claim.", "claim_type": "objection", "uncertainty_notes": "open question about premise"},
            {"claim_id": "CLM0003", "source_id": "SRC0001", "claim_text": "Counter defeater claim.", "claim_type": "counter_defeater"},
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
            },
            {"claim_id": "CLM0002", "source_id": "SRC0002", "defeater_strength_0_5": "5"},
        ],
    )
    _append_rows(
        queue_dir / "proposed_updates.csv",
        QUEUE_SCHEMAS["proposed_updates"],
        [
            {"proposal_id": "PROP0002", "claim_id": "CLM0002", "source_id": "SRC0002", "uncertainty_notes": "needs review"},
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
                "evidence_argument": "Sample moral realism support for EC.",
                "category": "Philosophical argument",
                "source_book": "Book A",
                "approved_weight_0_5": "4.5",
                "EC_MI5": "Highly likely",
                "N_MI5": "Unlikely",
                "notes": "important sample note",
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
                "evidence_argument": "A counter-defeater answer to the objection.",
                "category": "Counter-defeater",
                "source_book": "Book C",
                "approved_weight_0_5": "3.5",
                "EC_MI5": "Likely / probable",
                "N_MI5": "Unlikely",
                "notes": "counter_defeater response",
                "approved_date": "2026-05-23",
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
