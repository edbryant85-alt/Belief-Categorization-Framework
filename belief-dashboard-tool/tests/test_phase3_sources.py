from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest

from belief_dashboard.claims import create_claim_template
from belief_dashboard.config import load_config
from belief_dashboard.dossiers import DuplicateSourceError, find_source_dossiers, register_source
from belief_dashboard.prompts import generate_prompt_packet
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.sources import SourceRegistrationError


def test_registering_valid_md_source_creates_source_dossier_row(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "example_source.md"
    source_path.write_text("# Example\n\nSome notes.", encoding="utf-8")
    init_queues(queue_dir, config)

    result = register_source(
        source_path,
        queue_dir,
        config,
        source_type="book_notes",
        title="Example Source",
        author="Example Author",
        url="https://example.com",
        registered_on=date(2026, 5, 25),
    )

    rows = _read_rows(queue_dir / "source_dossiers.csv")
    assert result["source_id"] == "SRC0001"
    assert rows[0]["source_id"] == "SRC0001"
    assert rows[0]["source_type"] == "book_notes"
    assert rows[0]["title"] == "Example Source"
    assert rows[0]["author_or_speaker"] == "Example Author"
    assert rows[0]["date_added"] == "2026-05-25"
    assert rows[0]["original_file_path"] == str(source_path)
    assert rows[0]["url"] == "https://example.com"
    assert rows[0]["processing_status"] == "registered"


def test_registering_valid_txt_source_creates_source_dossier_row(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "plain-notes.txt"
    source_path.write_text("Plain text notes.", encoding="utf-8")
    init_queues(queue_dir, config)

    result = register_source(source_path, queue_dir, config)

    rows = _read_rows(queue_dir / "source_dossiers.csv")
    assert result["source_id"] == "SRC0001"
    assert rows[0]["title"] == "Plain Notes"


def test_unsupported_file_extensions_are_rejected_clearly(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "notes.pdf"
    source_path.write_text("Not supported.", encoding="utf-8")
    init_queues(queue_dir, config)

    with pytest.raises(SourceRegistrationError, match="Unsupported source file extension"):
        register_source(source_path, queue_dir, config)


def test_duplicate_source_file_paths_are_rejected_unless_allowed(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "duplicate.md"
    source_path.write_text("Duplicate test.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config)

    with pytest.raises(DuplicateSourceError):
        register_source(source_path, queue_dir, config)

    result = register_source(source_path, queue_dir, config, allow_duplicate=True)
    assert result["source_id"] == "SRC0002"


def test_generated_source_ids_increment_correctly(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("First.", encoding="utf-8")
    second.write_text("Second.", encoding="utf-8")
    init_queues(queue_dir, config)

    first_result = register_source(first, queue_dir, config)
    second_result = register_source(second, queue_dir, config)

    assert first_result["source_id"] == "SRC0001"
    assert second_result["source_id"] == "SRC0002"


def test_find_source_dossiers_locates_registered_discord_thread(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "are_humans_fundamentally_broken_or_fundamentally_good-page-1.txt"
    source_path.write_text("Discord thread text.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(
        source_path,
        queue_dir,
        config,
        source_type="discord_thread",
        title="Are Humans Fundamentally Broken or Fundamentally Good? - Page 1",
    )

    matches = find_source_dossiers(queue_dir, config, query="fundamentally good")

    assert len(matches) == 1
    assert matches[0]["source_id"] == "SRC0001"


def test_claim_template_generation_creates_source_specific_csv_template(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    output_dir = tmp_path / "prompt_packets"
    source_path = tmp_path / "source.md"
    source_path.write_text("Source text.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config)

    result = create_claim_template("SRC0001", queue_dir, output_dir, config)

    template_path = Path(result["template_path"])
    assert template_path.name == "SRC0001_extracted_claims_template.csv"
    assert _read_header(template_path) == QUEUE_SCHEMAS["extracted_claims"]


def test_prompt_packet_generation_creates_markdown_with_required_content(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    output_dir = tmp_path / "prompt_packets"
    source_path = tmp_path / "source.md"
    source_path.write_text("A source argues that an example claim matters.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config, title="Prompt Source")

    result = generate_prompt_packet(
        "SRC0001",
        queue_dir,
        output_dir,
        config,
        generated_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    prompt_path = Path(result["prompt_packet_path"])
    content = prompt_path.read_text(encoding="utf-8")
    assert prompt_path.name == "SRC0001_prompt_packet_2026-05-25_153000.md"
    assert "EC — Evangelical / Classical Christianity" in content
    assert "N — Naturalism" in content
    assert "Remote chance" in content
    assert "Almost certain" in content
    assert "Do not straw-man opposing views." in content
    assert "Distinguish summary from evaluation." in content
    assert "Avoid treating emotionally resonant claims as automatically stronger evidence." in content
    assert "extracted_claims.csv-ready rows" in content
    assert "criteria_matrix.csv-ready rows" in content
    assert "proposed_updates.csv-ready rows" in content


def test_discord_prompt_packet_includes_speaker_context_guidance(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    output_dir = tmp_path / "prompt_packets"
    source_path = tmp_path / "discord-thread.txt"
    source_path.write_text("Alice: humans are good.\nBob: I object.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config, source_type="discord_thread", title="Discord Debate")

    result = generate_prompt_packet("SRC0001", queue_dir, output_dir, config)

    content = Path(result["prompt_packet_path"]).read_text(encoding="utf-8")
    assert "Discord Thread Context Guidance" in content
    assert "Attribute claims to the clearest available speaker" in content


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))
