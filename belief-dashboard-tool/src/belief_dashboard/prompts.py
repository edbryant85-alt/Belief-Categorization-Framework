from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import append_import_log, find_source_dossier
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.sources import read_source_text
from belief_dashboard.utils import timestamp_for_filename


HYPOTHESIS_LABELS = {
    "EC": "Evangelical / Classical Christianity",
    "PC": "Progressive / Liberal Christianity",
    "PT": "Process Theology",
    "CT": "Classical Theism",
    "MT": "Minimal Theism / Deism",
    "IS": "Idealism / Consciousness-First",
    "MS": "Mystical / Spiritual Realism",
    "HC": "Humanistic / Cultural Christianity",
    "N": "Naturalism",
}

PHILOSOPHICAL_SAFEGUARDS = [
    "Do not straw-man opposing views.",
    "Distinguish summary from evaluation.",
    "Preserve context when extracting claims.",
    "Distinguish what a source claims from what I personally believe.",
    "Distinguish an author's argument from ChatGPT's interpretation of that argument.",
    "Identify uncertainty, ambiguity, and contested interpretations.",
    "Track objections and defeaters fairly.",
    "Avoid treating emotionally resonant claims as automatically stronger evidence.",
    "Avoid treating rhetorically weak presentation as proof that an argument itself is weak.",
    "Avoid collapsing different views into overly broad categories.",
    "Note when a claim affects multiple hypotheses differently.",
]

DISCORD_THREAD_GUIDANCE = [
    "Treat Discord exports as multi-speaker conversation, not as one authorial voice.",
    "Attribute claims to the clearest available speaker, role, or message context.",
    "When a reply quotes or paraphrases another person, distinguish the quoted target from the speaker's own claim.",
    "Preserve local conversational context for objections, concessions, clarifications, and reversals.",
    "Do not infer a participant's stable worldview from one short message unless the thread itself supports it.",
    "Split broad back-and-forth exchanges into smaller claims when different speakers or hypotheses are involved.",
    "Use source_context for speaker, reply target, timestamp, and surrounding-thread notes when available.",
]


def generate_prompt_packet(
    source_id: str,
    queue_dir: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    max_characters: int | None = None,
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

    output_path = (
        Path(output_dir)
        / f"{source_id}_prompt_packet_{timestamp_for_filename(generated_at)}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_prompt_packet(
            source_id=source_id,
            dossier=dossier,
            source_text=included_text,
            truncated=truncated,
            max_characters=max_inline,
        ),
        encoding="utf-8",
    )

    import_log_path = Path(queue_dir) / config["queues"]["files"]["import_log"]
    append_import_log(
        import_log_path,
        operation="generate_prompt_packet",
        file_path=str(output_path),
        status="success",
        message=f"Generated prompt packet for {source_id}.",
        logged_at=generated_at,
    )
    return {
        "source_id": source_id,
        "prompt_packet_path": str(output_path),
        "truncated": truncated,
        "characters_included": len(included_text),
    }


def render_prompt_packet(
    *,
    source_id: str,
    dossier: dict[str, str],
    source_text: str,
    truncated: bool,
    max_characters: int,
) -> str:
    truncation_note = (
        f"The source text below is truncated to the first {max_characters} characters."
        if truncated
        else "The full source text is included below."
    )
    return "\n".join(
        [
            f"# Prompt Packet for {source_id}",
            "",
            "I am using a local belief-dashboard workflow. Please help me analyze the source material below and return CSV-ready rows. These are suggestions only; I will review everything manually before anything enters my spreadsheet.",
            "",
            "## Source Metadata",
            f"- Source ID: {source_id}",
            f"- Title: {dossier.get('title', '')}",
            f"- Source type: {dossier.get('source_type', '')}",
            f"- Author or speaker: {dossier.get('author_or_speaker', '')}",
            f"- URL: {dossier.get('url', '')}",
            f"- Original file path: {dossier.get('original_file_path', '')}",
            "",
            "## Task",
            "Analyze the source material. Extract individual claims, arguments, objections, defeaters, counter-defeaters, definitions, interpretive claims, historical claims, scientific claims, moral claims, metaphysical claims, theological claims, and existential claims.",
            "",
            "Preserve context. Avoid straw-manning. Distinguish what the source says from what I believe. Distinguish summary from evaluation. Note ambiguity, uncertainty, and contested interpretations. Identify which hypotheses each claim supports, undermines, or functions as a defeater for.",
            "",
            "Propose MI5 labels for each hypothesis as suggestions only. Suggest weight values from 0-5 as suggestions only. Keep existential, moral, emotional, and practical salience separate from evidential weight.",
            "",
            "## Hypotheses",
            *_format_hypotheses(),
            "",
            "## MI5 Labels",
            *_format_bullets([
                "Remote chance",
                "Highly unlikely",
                "Unlikely",
                "Roughly even chance",
                "Likely / probable",
                "Highly likely",
                "Almost certain",
            ]),
            "",
            "## Philosophical Safeguards",
            *_format_bullets(PHILOSOPHICAL_SAFEGUARDS),
            "",
            *_discord_guidance_section(dossier),
            "",
            "## Return Format",
            "Return output in CSV-ready markdown tables matching these project schemas. Do not invent source metadata that is not present; leave uncertain cells blank or note uncertainty where appropriate.",
            "",
            "### extracted_claims.csv-ready rows",
            _format_schema("extracted_claims"),
            "",
            "### criteria_matrix.csv-ready rows",
            _format_schema("criteria_matrix"),
            "",
            "### proposed_updates.csv-ready rows",
            _format_schema("proposed_updates"),
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


def _format_hypotheses() -> list[str]:
    return [f"- {key} — {label}" for key, label in HYPOTHESIS_LABELS.items()]


def _format_bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _format_schema(queue_name: str) -> str:
    return ", ".join(QUEUE_SCHEMAS[queue_name])


def _discord_guidance_section(dossier: dict[str, str]) -> list[str]:
    source_type = (dossier.get("source_type") or "").lower()
    title = (dossier.get("title") or "").lower()
    path = (dossier.get("original_file_path") or "").lower()
    if "discord" not in " ".join([source_type, title, path]):
        return []
    return [
        "## Discord Thread Context Guidance",
        *_format_bullets(DISCORD_THREAD_GUIDANCE),
    ]
