from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from belief_dashboard.config import load_config
from belief_dashboard.dossiers import register_source
from belief_dashboard.queues import init_queues
from belief_dashboard.source_packet_cycle import (
    build_source_packet_cycle_plan,
    discover_packet_rows,
    find_newest_source_map,
)


def test_finds_newest_source_map_when_omitted(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompt_packets"
    prompt_dir.mkdir()
    older = prompt_dir / "SRC9999_source_map_2026-05-28_120000.md"
    newer = prompt_dir / "SRC9999_source_map_2026-05-29_120000.md"
    older.write_text("# old\n", encoding="utf-8")
    newer.write_text("# new\n", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    assert find_newest_source_map("SRC9999", prompt_dir) == newer


def test_parses_packet_paths_from_source_map(tmp_path: Path) -> None:
    source_map = _write_source_map(
        tmp_path,
        [
            ("SRC9999-PKT-001", "0-100", "Preamble, Contents", "packet_01_preamble.md"),
            ("SRC9999-PKT-002", "100-200", "Introduction, What Good Is Apologetics?", "packet_02_intro.md"),
        ],
    )

    rows = discover_packet_rows("SRC9999", tmp_path / "prompt_packets", source_map_path=source_map)

    assert [row["packet_id"] for row in rows] == ["SRC9999-PKT-001", "SRC9999-PKT-002"]
    assert rows[1]["packet_path"].endswith("packet_02_intro.md")


def test_falls_back_to_prompt_packet_directory(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompt_packets"
    prompt_dir.mkdir()
    _write_packet(prompt_dir / "SRC9999_schema_locked_packet_01_preamble_2026-05-29_120000.md", "SRC9999-PKT-001", "Preamble", "Preamble, Contents")
    _write_packet(prompt_dir / "SRC9999_schema_locked_packet_02_introduction_2026-05-29_120000.md", "SRC9999-PKT-002", "Introduction", "Introduction")

    rows = discover_packet_rows("SRC9999", prompt_dir)

    assert len(rows) == 2
    assert rows[0]["packet_title"] == "Preamble"
    assert rows[1]["included_headings"] == ["Introduction"]


def test_classifies_front_matter_as_skip_front_matter(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [
            ("SRC0001-PKT-001", "0-100", "Preamble, Contents, Preface to the Third Edition", "SRC0001_schema_locked_packet_01_preamble.md"),
        ],
    )

    assert plan["packets"][0]["recommended_action"] == "skip_front_matter"


def test_classifies_index_and_bibliography_like_packets(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [
            ("SRC0001-PKT-113", "100-200", "Press, 1983., Bibliography, Conclusion", "SRC0001_schema_locked_packet_113_press_1983.md"),
            ("SRC0001-PKT-114", "200-300", "Index, Becker, Carl, Jesus Seminar", "SRC0001_schema_locked_packet_114_becker_carl.md"),
        ],
    )

    assert plan["packets"][0]["recommended_action"] == "skip_bibliography"
    assert plan["packets"][1]["recommended_action"] == "skip_index"


def test_classifies_substantive_introduction_packet(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [
            ("SRC0001-PKT-004", "300-400", "Introduction, What Good Is Apologetics?", "SRC0001_schema_locked_packet_04_introduction.md"),
        ],
    )

    assert plan["packets"][0]["recommended_action"] in {"extract_now", "extract_later"}
    assert plan["packets"][0]["group_name"] == "Introduction / What Good Is Apologetics"


def test_groups_packets_into_chapter_topic_groups(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [
            ("SRC0001-PKT-004", "300-400", "Introduction, What Good Is Apologetics?", "SRC0001_schema_locked_packet_04_introduction.md"),
            ("SRC0001-PKT-012", "400-500", "How Do I Know Christianity Is True?, ROLE OF REASON", "SRC0001_schema_locked_packet_12_role_of_reason.md"),
            ("SRC0001-PKT-017", "500-600", "NO ULTIMATE MEANING WITHOUT GOD AND IMMORTALITY", "SRC0001_schema_locked_packet_17_no_ultimate_meaning_without_god.md"),
            ("SRC0001-PKT-026", "600-700", "THOMAS AQUINAS, WILLIAM SORLEY, Kalām Cosmological Argument", "SRC0001_schema_locked_packet_26_william_sorley.md"),
            ("SRC0001-PKT-045", "700-800", "Design Hypothesis, Many Worlds, Inflationary Multiverse", "SRC0001_schema_locked_packet_45_design_hypothesis.md"),
            ("SRC0001-PKT-060", "800-900", "Historical Knowledge, Testing Historical Hypotheses", "SRC0001_schema_locked_packet_60_historical_knowledge.md"),
            ("SRC0001-PKT-070", "900-1000", "Miracles", "SRC0001_schema_locked_packet_70_miracles.md"),
            ("SRC0001-PKT-080", "1000-1100", "Self-Understanding of Jesus, Implicit Christology", "SRC0001_schema_locked_packet_80_self_understanding_of_jesus.md"),
            ("SRC0001-PKT-100", "1100-1200", "Resurrection, Conspiracy Hypothesis, Resurrection Appearances", "SRC0001_schema_locked_packet_100_resurrection.md"),
        ],
    )

    group_names = {group["group_name"] for group in plan["groups"]}
    assert "How Do I Know Christianity Is True?" in group_names
    assert "Existence of God, chapter 3" in group_names
    assert "Existence of God, chapter 4" in group_names
    assert "Resurrection of Jesus" in group_names


def test_respects_max_batch_size(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [
            ("SRC0001-PKT-004", "300-400", "Introduction, What Good Is Apologetics?", "SRC0001_schema_locked_packet_04_introduction.md"),
            ("SRC0001-PKT-005", "400-500", "Introduction 23", "SRC0001_schema_locked_packet_05_introduction_23.md"),
            ("SRC0001-PKT-006", "500-600", "Introduction 24", "SRC0001_schema_locked_packet_06_introduction_24.md"),
        ],
        max_batch_size=2,
    )

    assert len(plan["recommended_first_batch"]["packet_ids"]) == 2


def test_produces_markdown_and_json_reports(tmp_path: Path) -> None:
    plan = _build_plan(
        tmp_path,
        [("SRC0001-PKT-004", "300-400", "Introduction", "SRC0001_schema_locked_packet_04_introduction.md")],
    )

    markdown_path = Path(plan["markdown_report_path"])
    json_path = Path(plan["json_report_path"])
    assert markdown_path.exists()
    assert json_path.exists()
    assert "## Full Packet Table" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["source_id"] == "SRC0001"


def test_planner_does_not_mutate_queues_imports_or_workbook_files(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    source_map = _write_source_map(
        tmp_path,
        [("SRC0001-PKT-004", "300-400", "Introduction", "SRC0001_schema_locked_packet_04_introduction.md")],
    )
    manual_imports = tmp_path / "manual_imports"
    workbook_dir = tmp_path / "workbooks"
    manual_imports.mkdir()
    workbook_dir.mkdir()
    (manual_imports / "existing.csv").write_text("keep\n", encoding="utf-8")
    (workbook_dir / "book.xlsx").write_text("keep\n", encoding="utf-8")
    before = _snapshot_files(queue_dir) | _snapshot_files(manual_imports) | _snapshot_files(workbook_dir)

    build_source_packet_cycle_plan(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "reports" / "source_packet_cycles",
        config,
        source_map=source_map,
        generated_at=datetime(2026, 5, 29, 12, 0, 0),
    )

    after = _snapshot_files(queue_dir) | _snapshot_files(manual_imports) | _snapshot_files(workbook_dir)
    assert after == before


def _build_plan(
    tmp_path: Path,
    rows: list[tuple[str, str, str, str]],
    *,
    max_batch_size: int = 10,
) -> dict:
    config, queue_dir, source_id = _setup_source(tmp_path)
    source_map = _write_source_map(tmp_path, rows)
    return build_source_packet_cycle_plan(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "reports" / "source_packet_cycles",
        config,
        source_map=source_map,
        max_batch_size=max_batch_size,
        generated_at=datetime(2026, 5, 29, 12, 0, 0),
    )


def _setup_source(tmp_path: Path) -> tuple[dict, Path, str]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    source_path = tmp_path / "source.md"
    source_path.write_text("# Example Book\n\nBody.", encoding="utf-8")
    result = register_source(
        source_path,
        queue_dir,
        config,
        source_type="book",
        title="Reasonable Faith: Christian Truth and Apologetics",
        author="William Lane Craig",
        registered_on=date(2026, 5, 29),
    )
    return config, queue_dir, result["source_id"]


def _write_source_map(tmp_path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    prompt_dir = tmp_path / "prompt_packets"
    prompt_dir.mkdir(exist_ok=True)
    lines = [
        "# Source Map for SRC0001",
        "",
        "## Packets",
        "",
        "| packet_id | character_range | included_headings_pages | truncated | packet_path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for packet_id, character_range, headings, path_name in rows:
        packet_path = prompt_dir / path_name
        lines.append(f"| {packet_id} | {character_range} | {headings} | False | {packet_path} |")
    source_map = prompt_dir / "SRC0001_source_map_2026-05-29_120000.md"
    source_map.write_text("\n".join(lines), encoding="utf-8")
    return source_map


def _write_packet(path: Path, packet_id: str, label: str, headings: str) -> None:
    path.write_text(
        "\n".join(
            [
                "# Schema-Locked Extraction Prompt Packet",
                "",
                "## Packet Metadata",
                "- Packet strategy: section",
                f"- Packet ID: {packet_id}",
                f"- Packet label: {label}",
                "- Character range: 0-100",
                f"- Included headings/pages: {headings}",
            ]
        ),
        encoding="utf-8",
    )


def _snapshot_files(path: Path) -> dict[str, str]:
    return {str(file.relative_to(path.parent)): file.read_text(encoding="utf-8") for file in path.rglob("*") if file.is_file()}
