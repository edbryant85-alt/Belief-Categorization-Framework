from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from belief_dashboard.config import load_config
from belief_dashboard.dossiers import register_source
from belief_dashboard.extraction_workspace import (
    create_import_templates,
    diagnose_import_shape,
    generate_extraction_workspace,
    import_schema_spec,
    render_import_schema,
)
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_show_import_schema_extracted_claims_headers() -> None:
    config = load_config("config.yaml")
    spec = import_schema_spec("extracted_claims", config)

    assert spec["headers"] == QUEUE_SCHEMAS["extracted_claims"]
    assert "claim_type" in spec["enum_fields"]


def test_show_import_schema_criteria_matrix_headers() -> None:
    config = load_config("config.yaml")
    spec = import_schema_spec("criteria_matrix", config)

    assert spec["headers"] == QUEUE_SCHEMAS["criteria_matrix"]
    assert "relevance_0_5" in spec["enum_fields"]


def test_show_import_schema_proposed_updates_headers() -> None:
    config = load_config("config.yaml")
    spec = import_schema_spec("proposed_updates", config)

    assert spec["headers"] == QUEUE_SCHEMAS["proposed_updates"]
    assert "review_status" in spec["enum_fields"]


def test_render_import_schema_markdown_includes_exact_headers() -> None:
    config = load_config("config.yaml")
    spec = import_schema_spec("extracted_claims", config)

    rendered = render_import_schema(spec, output_format="markdown")

    assert ",".join(QUEUE_SCHEMAS["extracted_claims"]) in rendered


def test_create_import_templates_writes_exact_headers(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    output_dir = tmp_path / "templates"

    result = create_import_templates(source_id, queue_dir, output_dir, config)

    assert len([path for path in result["written"] if path.endswith(".csv")]) == 3
    for import_type in ["extracted_claims", "criteria_matrix", "proposed_updates"]:
        template_path = output_dir / f"{source_id}_{import_type}_template.csv"
        assert _read_header(template_path) == QUEUE_SCHEMAS[import_type]
    instructions = (output_dir / f"{source_id}_template_instructions.md").read_text(encoding="utf-8")
    assert "Do not add, remove, rename, or reorder columns." in instructions


def test_create_import_templates_does_not_overwrite_without_force(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    output_dir = tmp_path / "templates"
    create_import_templates(source_id, queue_dir, output_dir, config)
    template_path = output_dir / f"{source_id}_extracted_claims_template.csv"
    template_path.write_text("custom\n", encoding="utf-8")

    result = create_import_templates(source_id, queue_dir, output_dir, config)

    assert str(template_path) in result["skipped"]
    assert template_path.read_text(encoding="utf-8") == "custom\n"


def test_create_import_templates_overwrites_with_force(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    output_dir = tmp_path / "templates"
    create_import_templates(source_id, queue_dir, output_dir, config)
    template_path = output_dir / f"{source_id}_extracted_claims_template.csv"
    template_path.write_text("custom\n", encoding="utf-8")

    create_import_templates(source_id, queue_dir, output_dir, config, force=True)

    assert _read_header(template_path) == QUEUE_SCHEMAS["extracted_claims"]


def test_generate_extraction_workspace_creates_schema_locked_prompt(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    prompt_dir = tmp_path / "prompt_packets"
    template_dir = tmp_path / "templates"

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        prompt_dir,
        template_dir,
        config,
        generated_at=datetime(2026, 5, 28, 12, 0, 0),
    )

    prompt_path = Path(result["prompt_packet_path"])
    assert prompt_path.name == f"{source_id}_schema_locked_prompt_packet_2026-05-28_120000.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "strict local CSV validator" in prompt_text
    assert ",".join(QUEUE_SCHEMAS["extracted_claims"]) in prompt_text
    assert ",".join(QUEUE_SCHEMAS["criteria_matrix"]) in prompt_text
    assert ",".join(QUEUE_SCHEMAS["proposed_updates"]) in prompt_text


def test_generate_extraction_workspace_default_first_strategy_preserves_existing_behavior(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        generated_at=datetime(2026, 5, 28, 12, 0, 0),
    )

    assert result["packet_strategy"] == "first"
    assert result["prompt_packet_path"].endswith(f"{source_id}_schema_locked_prompt_packet_2026-05-28_120000.md")
    assert result["prompt_packet_paths"] == [result["prompt_packet_path"]]
    assert result["source_map_path"] == ""


def test_section_strategy_creates_multiple_packets_for_long_markdown_source(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=450,
        packet_strategy="section",
        generated_at=datetime(2026, 5, 28, 12, 0, 0),
    )

    assert len(result["prompt_packet_paths"]) > 1
    assert all("schema_locked_packet" in Path(path).name for path in result["prompt_packet_paths"])


def test_section_strategy_creates_source_map_with_packet_ids_and_ranges(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=450,
        packet_strategy="section",
    )

    source_map = Path(result["source_map_path"]).read_text(encoding="utf-8")
    assert f"# Source Map for {source_id}" in source_map
    assert f"{source_id}-PKT-001" in source_map
    assert "character_range" in source_map
    assert "Recommended Extraction Order" in source_map


def test_section_packet_includes_exact_schemas_metadata_and_packet_id(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=450,
        packet_strategy="section",
    )

    packet_text = Path(result["prompt_packet_paths"][0]).read_text(encoding="utf-8")
    assert "## Packet Metadata" in packet_text
    assert f"- Packet ID: {source_id}-PKT-001" in packet_text
    assert "Extract claims only from the source text included in this packet." in packet_text
    assert ",".join(QUEUE_SCHEMAS["extracted_claims"]) in packet_text
    assert ",".join(QUEUE_SCHEMAS["criteria_matrix"]) in packet_text
    assert ",".join(QUEUE_SCHEMAS["proposed_updates"]) in packet_text


def test_section_packet_includes_only_selected_section_text(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=450,
        packet_strategy="section",
    )

    first_packet_text = Path(result["prompt_packet_paths"][0]).read_text(encoding="utf-8")
    assert "Introduction marker alpha" in first_packet_text
    assert "Neoplatonism marker gamma" not in first_packet_text


def test_targeted_strategy_includes_matching_heading_text(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=900,
        packet_strategy="targeted",
        include_headings=["Neoplatonism"],
    )

    packet_text = "\n".join(Path(path).read_text(encoding="utf-8") for path in result["prompt_packet_paths"])
    assert "Neoplatonism marker gamma" in packet_text
    assert "Introduction marker alpha" not in packet_text


def test_section_mode_does_not_silently_omit_later_sections(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path, source_text=_long_sectioned_source())

    result = generate_extraction_workspace(
        source_id,
        queue_dir,
        tmp_path / "prompt_packets",
        tmp_path / "templates",
        config,
        max_characters=450,
        packet_strategy="section",
    )

    all_packet_text = "\n".join(Path(path).read_text(encoding="utf-8") for path in result["prompt_packet_paths"])
    assert "Design marker beta" in all_packet_text
    assert "Neoplatonism marker gamma" in all_packet_text


def test_schema_locked_prompt_includes_allowed_values(tmp_path: Path) -> None:
    config, queue_dir, source_id = _setup_source(tmp_path)
    result = generate_extraction_workspace(source_id, queue_dir, tmp_path / "prompts", tmp_path / "templates", config)
    prompt_text = Path(result["prompt_packet_path"]).read_text(encoding="utf-8")

    assert "metaphysical_claim" in prompt_text
    assert "review_status" in prompt_text
    assert "proposed, approved, rejected, deferred" in prompt_text


def test_diagnose_import_shape_detects_wrong_headers(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    import_path = tmp_path / "criteria.csv"
    import_path.write_text("claim_id,source_id,criterion,rating,rationale,uncertainty_notes\n", encoding="utf-8")

    result = diagnose_import_shape("criteria_matrix", import_path, config)

    assert result["overall_status"] == "fail"
    assert "relevance_0_5" in result["missing_headers"]
    assert result["known_wrong_schema_pattern"]


def _setup_source(tmp_path: Path, *, source_text: str = "# Example Source\n\nA sample claim.") -> tuple[dict, Path, str]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    source_path = tmp_path / "source.md"
    source_path.write_text(source_text, encoding="utf-8")
    result = register_source(
        source_path,
        queue_dir,
        config,
        source_type="scholarly_article",
        title="Example Source",
        author="Example Author",
        registered_on=date(2026, 5, 28),
    )
    return config, queue_dir, result["source_id"]


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def _long_sectioned_source() -> str:
    intro = "Introduction marker alpha. " + "This opening section frames the article. " * 20
    design = "Design marker beta. " + "This later section develops design, resurrection, and theodicy themes. " * 20
    neoplatonism = "Neoplatonism marker gamma. " + "This final section compares simulationism, Neoplatonism, and theism. " * 20
    return "\n\n".join(
        [
            "# Example Long Source",
            "1. Introduction",
            intro,
            "2. Design, Resurrection, and Theodicy",
            design,
            "3. Neoplatonism and Theism",
            neoplatonism,
        ]
    )
