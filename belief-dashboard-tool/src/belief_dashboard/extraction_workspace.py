from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import find_source_dossier
from belief_dashboard.prompts import HYPOTHESIS_LABELS, PHILOSOPHICAL_SAFEGUARDS
from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS, MI5_COLUMNS, QUEUE_SCHEMAS
from belief_dashboard.sources import SourceRegistrationError, read_source_text
from belief_dashboard.utils import timestamp_for_filename


EXTRACTION_IMPORT_TYPES = ["extracted_claims", "criteria_matrix", "proposed_updates"]


def import_schema_spec(import_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if import_type not in QUEUE_SCHEMAS:
        raise ValueError(f"Unknown import type: {import_type}")
    headers = QUEUE_SCHEMAS[import_type]
    enum_fields = _enum_fields(import_type, config)
    defaults = _default_fields(import_type)
    return {
        "import_type": import_type,
        "headers": headers,
        "required_headers": headers,
        "optional_headers": [],
        "enum_fields": enum_fields,
        "defaults": defaults,
        "id_guidance": _id_guidance(import_type),
    }


def render_import_schema(spec: dict[str, Any], *, output_format: str = "table") -> str:
    if output_format == "json":
        return json.dumps(spec, indent=2)
    if output_format == "markdown":
        return _render_schema_markdown(spec)
    return _render_schema_table(spec)


def create_import_templates(
    source_id: str,
    queue_dir: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    import_types: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    dossier = find_source_dossier(source_id, queue_dir, config)
    selected_types = import_types or EXTRACTION_IMPORT_TYPES
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    specs = [import_schema_spec(import_type, config) for import_type in selected_types]
    for spec in specs:
        template_path = output_path / f"{source_id}_{spec['import_type']}_template.csv"
        if template_path.exists() and not force:
            skipped.append(str(template_path))
            continue
        with template_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(spec["headers"])
        written.append(str(template_path))
    instructions_path = output_path / f"{source_id}_template_instructions.md"
    if instructions_path.exists() and not force:
        skipped.append(str(instructions_path))
    else:
        instructions_path.write_text(
            render_template_instructions(source_id, dossier, specs, config),
            encoding="utf-8",
        )
        written.append(str(instructions_path))
    return {
        "source_id": source_id,
        "source_title": dossier.get("title", ""),
        "written": written,
        "skipped": skipped,
        "instructions_path": str(instructions_path),
    }


def generate_extraction_workspace(
    source_id: str,
    queue_dir: str | Path,
    prompt_output_dir: str | Path,
    template_output_dir: str | Path,
    config: dict[str, Any],
    *,
    max_characters: int | None = None,
    force: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    dossier = find_source_dossier(source_id, queue_dir, config)
    source_path = Path(dossier["original_file_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"Registered source file no longer exists: {source_path}")
    max_inline = max_characters or int(config["prompt_packets"]["max_inline_characters"])
    source_text = read_source_text(source_path)
    included_text = source_text[:max_inline]
    truncated = len(source_text) > max_inline
    specs = [import_schema_spec(import_type, config) for import_type in EXTRACTION_IMPORT_TYPES]
    prompt_path = (
        Path(prompt_output_dir)
        / f"{source_id}_schema_locked_prompt_packet_{timestamp_for_filename(generated_at)}.md"
    )
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        render_schema_locked_prompt_packet(
            source_id=source_id,
            dossier=dossier,
            source_text=included_text,
            truncated=truncated,
            max_characters=max_inline,
            specs=specs,
            config=config,
        ),
        encoding="utf-8",
    )
    templates = create_import_templates(
        source_id,
        queue_dir,
        template_output_dir,
        config,
        import_types=EXTRACTION_IMPORT_TYPES,
        force=force,
    )
    return {
        "source_id": source_id,
        "prompt_packet_path": str(prompt_path),
        "characters_included": len(included_text),
        "truncated": truncated,
        "template_paths": [path for path in templates["written"] if path.endswith(".csv")],
        "instructions_path": templates["instructions_path"],
        "skipped": templates["skipped"],
    }


def diagnose_import_shape(import_type: str, import_file: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    spec = import_schema_spec(import_type, config)
    file_path = Path(import_file)
    result: dict[str, Any] = {
        "import_type": import_type,
        "import_file": str(file_path),
        "expected_headers": spec["headers"],
        "actual_headers": [],
        "missing_headers": [],
        "extra_headers": [],
        "wrong_order": False,
        "known_wrong_schema_pattern": "",
        "overall_status": "fail",
    }
    if not file_path.exists():
        result["error"] = f"Import file not found: {file_path}"
        return result
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        actual = next(reader, [])
    expected = spec["headers"]
    result["actual_headers"] = actual
    result["missing_headers"] = [header for header in expected if header not in actual]
    result["extra_headers"] = [header for header in actual if header not in expected]
    result["wrong_order"] = actual != expected and not result["missing_headers"] and not result["extra_headers"]
    result["known_wrong_schema_pattern"] = _known_wrong_schema_pattern(import_type, actual)
    result["overall_status"] = "pass" if actual == expected else "fail"
    return result


def render_diagnosis(result: dict[str, Any], *, output_format: str = "table") -> str:
    if output_format == "json":
        return json.dumps(result, indent=2)
    lines = [
        f"Import type: {result['import_type']}",
        f"Import file: {result['import_file']}",
        f"Overall status: {result['overall_status']}",
        f"Expected headers: {', '.join(result['expected_headers'])}",
        f"Actual headers: {', '.join(result['actual_headers'])}",
        f"Missing headers: {', '.join(result['missing_headers']) or 'None'}",
        f"Extra headers: {', '.join(result['extra_headers']) or 'None'}",
        f"Wrong order only: {result['wrong_order']}",
    ]
    if result.get("known_wrong_schema_pattern"):
        lines.append(f"Known wrong-schema pattern: {result['known_wrong_schema_pattern']}")
    if result.get("error"):
        lines.append(f"Error: {result['error']}")
    return "\n".join(lines)


def render_template_instructions(
    source_id: str,
    dossier: dict[str, str],
    specs: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    return "\n".join(
        [
            f"# Import Template Instructions for {source_id}",
            "",
            f"- Source ID: `{source_id}`",
            f"- Title: {dossier.get('title', '')}",
            f"- Author or speaker: {dossier.get('author_or_speaker', '')}",
            f"- Source type: {dossier.get('source_type', '')}",
            "",
            "## ID Rules",
            f"- Claim IDs: `{source_id}-C001`, `{source_id}-C002`, ...",
            f"- Proposal IDs: `{source_id}-P001`, `{source_id}-P002`, ...",
            "- `criteria_matrix.claim_id` must exactly match an extracted claim ID.",
            "- `proposed_updates.claim_id` must exactly match an extracted claim ID.",
            "",
            "## Strict CSV Rules",
            "- Use the CSV templates exactly as written.",
            "- Do not add, remove, rename, or reorder columns.",
            "- Leave uncertain values blank or explain uncertainty in the appropriate notes field.",
            "- Use only allowed enum values.",
            "",
            "## Allowed Values",
            f"- claim_type: {', '.join(config['allowed_values']['claim_types'])}",
            f"- review_status/status: {', '.join(config['allowed_values']['review_statuses'])}",
            f"- MI5 labels: {', '.join(config['allowed_values']['mi5_labels'])}",
            "",
            "## Schemas",
            *[_render_schema_markdown(spec) for spec in specs],
            "",
        ]
    )


def render_schema_locked_prompt_packet(
    *,
    source_id: str,
    dossier: dict[str, str],
    source_text: str,
    truncated: bool,
    max_characters: int,
    specs: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    truncation_note = (
        f"The source text below is truncated to the first {max_characters} characters."
        if truncated
        else "The full source text is included below."
    )
    return "\n".join(
        [
            f"# Schema-Locked Extraction Prompt Packet for {source_id}",
            "",
            "Your output will be parsed by a strict local CSV validator. If you add columns, rename columns, omit columns, reorder columns, or use values outside the allowed enums, the import will fail.",
            "",
            "Do not create simplified schemas. Use only the exact headers below.",
            "",
            "Return exactly three CSV-ready markdown tables: `extracted_claims`, `criteria_matrix`, and `proposed_updates`.",
            "",
            "## Source Metadata",
            f"- Source ID: {source_id}",
            f"- Title: {dossier.get('title', '')}",
            f"- Source type: {dossier.get('source_type', '')}",
            f"- Author or speaker: {dossier.get('author_or_speaker', '')}",
            f"- URL: {dossier.get('url', '')}",
            f"- Original file path: {dossier.get('original_file_path', '')}",
            "",
            "## Extraction Scope",
            "- Extract claims from this source only.",
            "- Do not import objections, revisions, interpretations, or debate claims from other sources.",
            "- Distinguish what the source says from later evaluation.",
            "",
            "## ID Rules",
            f"- Use claim IDs in this form: `{source_id}-C001`, `{source_id}-C002`, ...",
            f"- Use proposal IDs in this form: `{source_id}-P001`, `{source_id}-P002`, ...",
            "- Every criteria row must use a `claim_id` from extracted_claims.",
            "- Every proposed update row must use a `claim_id` from extracted_claims.",
            "",
            "## Exact Schemas",
            *[_render_prompt_schema_section(spec, config) for spec in specs],
            "",
            "## Hypotheses",
            *[f"- {key} - {label}" for key, label in HYPOTHESIS_LABELS.items()],
            "",
            "## Philosophical Safeguards",
            *[f"- {item}" for item in PHILOSOPHICAL_SAFEGUARDS],
            "",
            "## Formatting Rules",
            "- Return only the three requested CSV-ready markdown tables.",
            "- Use the exact column names in the exact order shown.",
            "- Do not add prose between table rows.",
            "- Use `proposed` for new `extracted_claims.status` and `proposed_updates.review_status` rows unless there is a project-specific reason not to.",
            "- Keep `criteria_matrix` scores in the inclusive range 0-5.",
            "- Use only listed MI5 labels.",
            "",
            "## Source Text",
            truncation_note,
            "",
            "```text",
            source_text,
            "```",
            "",
        ]
    )


def _enum_fields(import_type: str, config: dict[str, Any]) -> dict[str, list[str]]:
    allowed = config["allowed_values"]
    if import_type == "extracted_claims":
        return {
            "claim_type": allowed["claim_types"],
            "status": allowed["review_statuses"],
        }
    if import_type == "criteria_matrix":
        return {field: ["0", "1", "2", "3", "4", "5"] for field in CRITERIA_SCORE_FIELDS}
    if import_type == "proposed_updates":
        fields = {column: allowed["mi5_labels"] for column in MI5_COLUMNS}
        fields["suggested_weight_0_5"] = ["0", "1", "2", "3", "4", "5"]
        fields["review_status"] = allowed["review_statuses"]
        return fields
    return {}


def _default_fields(import_type: str) -> dict[str, str]:
    if import_type == "extracted_claims":
        return {"status": "proposed"}
    if import_type == "proposed_updates":
        return {"review_status": "proposed"}
    return {}


def _id_guidance(import_type: str) -> list[str]:
    if import_type == "extracted_claims":
        return ["claim_id should use SOURCE_ID-C###, for example SRC0012-C001."]
    if import_type == "criteria_matrix":
        return ["claim_id must exactly match a claim_id from extracted_claims."]
    if import_type == "proposed_updates":
        return [
            "proposal_id should use SOURCE_ID-P###, for example SRC0012-P001.",
            "claim_id must exactly match a claim_id from extracted_claims.",
        ]
    return []


def _render_schema_table(spec: dict[str, Any]) -> str:
    lines = [
        f"Import type: {spec['import_type']}",
        f"Headers: {', '.join(spec['headers'])}",
        "Enum fields:",
    ]
    if spec["enum_fields"]:
        for field, values in spec["enum_fields"].items():
            lines.append(f"- {field}: {', '.join(values)}")
    else:
        lines.append("- None")
    if spec["defaults"]:
        lines.append("Defaults:")
        for field, value in spec["defaults"].items():
            lines.append(f"- {field}: {value}")
    return "\n".join(lines)


def _render_schema_markdown(spec: dict[str, Any]) -> str:
    lines = [
        f"### {spec['import_type']}",
        "",
        "Headers, in exact order:",
        "",
        "```csv",
        ",".join(spec["headers"]),
        "```",
        "",
    ]
    if spec["enum_fields"]:
        lines.append("Enum fields:")
        for field, values in spec["enum_fields"].items():
            lines.append(f"- `{field}`: {', '.join(values)}")
        lines.append("")
    if spec["defaults"]:
        lines.append("Defaults:")
        for field, value in spec["defaults"].items():
            lines.append(f"- `{field}`: `{value}`")
        lines.append("")
    if spec["id_guidance"]:
        lines.append("ID guidance:")
        for item in spec["id_guidance"]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_prompt_schema_section(spec: dict[str, Any], config: dict[str, Any]) -> str:
    del config
    return "\n".join(
        [
            f"### {spec['import_type']}",
            "",
            "Use exactly these headers:",
            "",
            "```csv",
            ",".join(spec["headers"]),
            "```",
            "",
            "Allowed values and defaults:",
            *(_format_enum_lines(spec) or ["- None"]),
            "",
        ]
    )


def _format_enum_lines(spec: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for field, values in spec["enum_fields"].items():
        lines.append(f"- `{field}` allowed values: {', '.join(values)}")
    for field, value in spec["defaults"].items():
        lines.append(f"- `{field}` default for new rows: `{value}`")
    return lines


def _known_wrong_schema_pattern(import_type: str, actual_headers: list[str]) -> str:
    actual = set(actual_headers)
    if import_type == "criteria_matrix" and {"criterion", "rating", "rationale"}.issubset(actual):
        return "rubric-style criteria matrix; expected one row per claim with numeric score columns"
    if import_type == "proposed_updates" and {"update_id", "update_type", "target_area", "proposed_update"}.issubset(actual):
        return "generic update list; expected proposed_updates queue schema"
    if import_type == "proposed_updates" and {"affected_hypotheses", "direction", "rationale"}.issubset(actual):
        return "simplified proposal schema; expected MI5 columns and source_book"
    if import_type == "extracted_claims" and {"cluster_id", "source_role", "evidence_basis"}.issubset(actual):
        return "expanded extraction schema; expected extracted_claims queue schema"
    return ""
