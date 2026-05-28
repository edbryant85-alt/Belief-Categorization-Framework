from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from belief_dashboard.config import load_config
from belief_dashboard.dossiers import register_source
from belief_dashboard.manual_imports import append_manual_import, validate_manual_import
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.source_triage import (
    build_triage_summary,
    bulk_register_sources,
    generate_triage_prompt_packet,
)


def test_bulk_register_sources_registers_supported_transcripts(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "first.txt").write_text("First transcript.", encoding="utf-8")
    (raw_dir / "second.md").write_text("Second transcript.", encoding="utf-8")
    (raw_dir / "skip.pdf").write_text("Unsupported.", encoding="utf-8")
    init_queues(queue_dir, config)

    result = bulk_register_sources(raw_dir, queue_dir, config)

    rows = _read_rows(queue_dir / "source_dossiers.csv")
    assert result["files_considered"] == 2
    assert len(result["registered"]) == 2
    assert [row["source_id"] for row in rows] == ["SRC0001", "SRC0002"]
    assert {row["source_type"] for row in rows} == {"youtube_transcript"}


def test_triage_prompt_packet_includes_multiple_sources_and_schema(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    reports_dir = tmp_path / "reports"
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("A transcript about hell and biblical interpretation.", encoding="utf-8")
    second.write_text("A transcript about morality and social life.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(first, queue_dir, config, source_type="youtube_transcript")
    register_source(second, queue_dir, config, source_type="youtube_transcript")

    result = generate_triage_prompt_packet(
        queue_dir,
        reports_dir,
        config,
        limit=2,
        generated_at=datetime(2026, 5, 27, 12, 0, 0),
    )

    content = Path(result["prompt_packet_path"]).read_text(encoding="utf-8")
    assert result["source_ids"] == ["SRC0001", "SRC0002"]
    assert "Batch Source Triage Prompt Packet" in content
    assert "source_id, triage_status, priority_0_5, recommended_action" in content
    assert "recommended_action=full_extraction" in content
    assert "SRC0001" in content
    assert "SRC0002" in content


def test_source_triage_import_validates_and_summarizes_candidates(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "source.txt"
    source_path.write_text("Important transcript.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config, title="Important Source")
    import_path = tmp_path / "source_triage.csv"
    _write_rows(
        import_path,
        QUEUE_SCHEMAS["source_triage"],
        [
            {
                "source_id": "SRC0001",
                "triage_status": "triaged",
                "priority_0_5": "5",
                "recommended_action": "full_extraction",
                "relevance_tags": "hell; interpretation",
                "summary": "Likely useful.",
                "reviewer": "Eric",
                "triaged_at": "2026-05-27",
            }
        ],
    )

    validation = validate_manual_import("source_triage", import_path, queue_dir, config)
    append_result = append_manual_import("source_triage", import_path, queue_dir, config)
    summary = build_triage_summary(queue_dir, config)

    assert validation["overall_status"] == "pass"
    assert append_result["rows_appended"] == 1
    assert summary["triaged_source_count"] == 1
    assert summary["by_recommended_action"] == {"full_extraction": 1}
    assert summary["full_extraction_candidates"][0]["source_id"] == "SRC0001"
    assert summary["full_extraction_candidates"][0]["title"] == "Important Source"


def test_source_triage_import_rejects_invalid_actions_and_priorities(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "source.txt"
    source_path.write_text("Transcript.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config)
    import_path = tmp_path / "source_triage.csv"
    _write_rows(
        import_path,
        QUEUE_SCHEMAS["source_triage"],
        [
            {
                "source_id": "SRC0001",
                "triage_status": "triaged",
                "priority_0_5": "9",
                "recommended_action": "export_to_workbook",
            }
        ],
    )

    result = validate_manual_import("source_triage", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("recommended_action has invalid value" in error for error in result["errors"])
    assert any("priority_0_5 must be between 0 and 5" in error for error in result["errors"])


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
