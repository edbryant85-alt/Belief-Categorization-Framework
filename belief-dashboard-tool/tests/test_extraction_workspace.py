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


def _setup_source(tmp_path: Path) -> tuple[dict, Path, str]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    source_path = tmp_path / "source.md"
    source_path.write_text("# Example Source\n\nA sample claim.", encoding="utf-8")
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
