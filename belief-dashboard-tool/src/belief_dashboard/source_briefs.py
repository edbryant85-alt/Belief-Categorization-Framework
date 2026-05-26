from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.debate_summaries import HYPOTHESIS_NAMES, MI5_IMPACT
from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS, MI5_COLUMNS, QUEUE_SCHEMAS
from belief_dashboard.study_queue import build_study_queue
from belief_dashboard.utils import resolve_project_path, timestamp_for_filename, timestamp_iso


SUPPORT_CLASSES = {"strong_support", "moderate_support"}
CHALLENGE_CLASSES = {"strong_challenge", "moderate_challenge"}


def build_source_brief(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    source_id: str | None,
    limit: int | None = None,
    include_raw_excerpt: bool | None = None,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    brief_config = config.get("source_briefs", {})
    if not source_id:
        return _error_result("Missing required --source-id.", source_id)

    item_limit = int(limit if limit is not None else brief_config.get("default_limit", 25))
    queue_dir = _queue_dir(config, base_dir)
    files = config["queues"]["files"]
    rows = {
        "source_dossiers": _read_optional_csv(queue_dir / files["source_dossiers"]),
        "extracted_claims": _read_optional_csv(queue_dir / files["extracted_claims"]),
        "criteria_matrix": _read_optional_csv(queue_dir / files["criteria_matrix"]),
        "proposed_updates": _read_optional_csv(queue_dir / files["proposed_updates"]),
        "approved_updates": _read_optional_csv(queue_dir / files["approved_updates"]),
        "rejected_updates": _read_optional_csv(queue_dir / files["rejected_updates"]),
        "deferred_updates": _read_optional_csv(queue_dir / files["deferred_updates"]),
    }
    source = next((row for row in rows["source_dossiers"] if row.get("source_id") == source_id), None)
    if source is None:
        return _error_result(
            (
                f"Unknown source ID: {source_id}. Try: python -m belief_dashboard.cli "
                "register-source --file data/raw_sources/example.md; then run: "
                "python -m belief_dashboard.cli queue-summary"
            ),
            source_id,
        )

    claims = [row for row in rows["extracted_claims"] if row.get("source_id") == source_id]
    criteria = [row for row in rows["criteria_matrix"] if row.get("source_id") == source_id]
    proposed = [row for row in rows["proposed_updates"] if row.get("source_id") == source_id]
    approved = [row for row in rows["approved_updates"] if row.get("source_id") == source_id]
    rejected = [row for row in rows["rejected_updates"] if row.get("source_id") == source_id]
    deferred = [row for row in rows["deferred_updates"] if row.get("source_id") == source_id]
    claim_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in claims}
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}

    warnings: list[str] = []
    raw_enabled = bool(brief_config.get("include_raw_excerpt", False)) if include_raw_excerpt is None else include_raw_excerpt
    raw_excerpt = _raw_excerpt(
        source,
        base_dir=base_dir,
        max_characters=int(brief_config.get("raw_excerpt_max_characters", 1500)),
        enabled=raw_enabled,
        warnings=warnings,
    )
    study_result = build_study_queue(
        config,
        base_dir,
        source_id=source_id,
        limit=item_limit,
        include_deferred=True,
        include_rejected=False,
        include_reflections=False,
        length=length,
    )
    study_items = study_result.get("study_items", []) if study_result.get("overall_status") == "pass" else []

    include_claims = bool(brief_config.get("include_claims", True))
    include_criteria = bool(brief_config.get("include_criteria", True))
    include_review_outcomes = bool(brief_config.get("include_review_outcomes", True))
    include_approved_impacts = bool(brief_config.get("include_approved_impacts", True))
    include_study_items = bool(brief_config.get("include_study_items", True))
    include_trace_appendix = bool(brief_config.get("include_trace_appendix", True))

    claim_summaries = (
        [_claim_summary(row, criteria_index.get((row.get("claim_id", ""), source_id), {})) for row in claims]
        if include_claims
        else []
    )
    criteria_highlights = _criteria_highlights(criteria, item_limit) if include_criteria else []
    impacts = _approved_impacts(approved, claim_index, criteria_index, config, item_limit) if include_approved_impacts else []
    outcomes = _review_outcomes(proposed, approved, rejected, deferred, item_limit) if include_review_outcomes else _review_outcomes([], [], [], [], item_limit)
    source_study_items = study_items[:item_limit] if include_study_items else []
    trace_appendix = _trace_appendix(source_id, claims, proposed, approved, rejected, deferred) if include_trace_appendix else _trace_appendix(source_id, [], [], [], [], [])
    debate_use = _debate_use(impacts, criteria_highlights, source_study_items)
    discord = _discord_section(source, claims if include_claims else [], impacts, source_study_items, trace_appendix, item_limit)

    return {
        "operation": "source_brief",
        "generated_at": timestamp_iso(generated_at),
        "source_id": source_id,
        "source_metadata": source,
        "raw_excerpt": raw_excerpt,
        "extracted_claims": claim_summaries,
        "criteria_highlights": criteria_highlights,
        "proposal_review_outcomes": outcomes,
        "approved_hypothesis_impacts": impacts,
        "unresolved_study_items": source_study_items,
        "debate_use": debate_use,
        "discord_section": discord,
        "trace_appendix": trace_appendix,
        "counts": {
            "claims": len(claims),
            "criteria_rows": len(criteria),
            "proposed_updates": len(proposed),
            "approved_updates": len(approved),
            "rejected_updates": len(rejected),
            "deferred_updates": len(deferred),
            "unresolved_study_items": len(study_items),
        },
        "filters": {"source_id": source_id, "limit": item_limit, "length": length, "include_raw_excerpt": raw_enabled},
        "warnings": warnings,
        "errors": [],
        "overall_status": "pass",
        "no_workbook_or_queue_data_modified": True,
    }


def render_source_brief(result: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Source brief status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return result["discord_section"]

    source = result["source_metadata"]
    lines = [
        f"# Source Brief: {result['source_id']} - {source.get('title', '') or 'Untitled Source'}",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Source type: `{source.get('source_type', '')}`",
        f"- Author/speaker: `{source.get('author_or_speaker', '')}`",
        f"- Date added: `{source.get('date_added', '')}`",
        f"- Processing status: `{source.get('processing_status', '')}`",
        "- Caveat: This summarizes queue records for inspection and does not change data.",
        "- No workbook or queue data was modified.",
        "",
        "## Source Metadata",
        *_metadata_lines(source, length=length),
        "",
    ]
    if result["raw_excerpt"].get("included"):
        lines.extend(["## Raw Source Excerpt", _raw_excerpt_block(result["raw_excerpt"]), ""])
    elif result["raw_excerpt"].get("warning"):
        lines.extend(["## Raw Source Excerpt", f"- Warning: {result['raw_excerpt']['warning']}", ""])

    lines.extend(
        [
            "## Extracted Claims",
            *_claim_lines(result["extracted_claims"], result["filters"]["limit"], length=length),
            "",
            "## Criteria Highlights",
            *_criteria_lines(result["criteria_highlights"], length=length),
            "",
            "## Proposal / Review Outcomes",
            *_outcome_lines(result["proposal_review_outcomes"], length=length),
            "",
            "## Approved Hypothesis Impacts",
            *_impact_lines(result["approved_hypothesis_impacts"], length=length),
            "",
            "## Unresolved / Study Items",
            *_study_lines(result["unresolved_study_items"], result["filters"]["limit"], length=length),
            "",
            "## Debate Use",
            *_debate_use_lines(result["debate_use"]),
            "",
            "## Discord Copy Section",
            result["discord_section"],
            "",
            "## Trace Appendix",
            *_trace_lines(result["trace_appendix"], length=length),
        ]
    )
    if result["warnings"]:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in result["warnings"]]])
    return "\n".join(lines).rstrip()


def write_source_brief_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    source_id = result.get("source_id") or "UNKNOWN"
    markdown_path = reports_path / f"source_brief_{source_id}_{stamp}.md"
    json_path = reports_path / f"source_brief_{source_id}_{stamp}.json"
    markdown_path.write_text(render_source_brief(result, length="long") + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _criteria_highlights(rows: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
    highlights = []
    for row in rows:
        flags = []
        high_mapping = {
            "relevance_0_5": "high relevance",
            "reliability_0_5": "high reliability",
            "argument_strength_0_5": "high argument strength",
            "explanatory_power_0_5": "high explanatory power",
            "defeater_strength_0_5": "high defeater strength",
            "uncertainty_0_5": "high uncertainty",
            "existential_salience_0_5": "high existential salience",
            "moral_stakes_0_5": "high moral stakes",
            "emotional_salience_0_5": "high emotional salience",
        }
        for field, label in high_mapping.items():
            if _float(row.get(field)) >= 4:
                flags.append(label)
        clarity = _float(row.get("clarity_0_5"))
        if clarity and clarity <= 2:
            flags.append("low clarity")
        highlights.append(
            {
                "claim_id": row.get("claim_id", ""),
                "source_id": row.get("source_id", ""),
                "scores": {field: row.get(field, "") for field in CRITERIA_SCORE_FIELDS if row.get(field, "")},
                "highlights": flags,
                "notes": row.get("notes", ""),
                "salience_note": "Salience flags are separate from evidential strength.",
            }
        )
    return highlights[:limit]


def _review_outcomes(
    proposed: list[dict[str, str]],
    approved: list[dict[str, str]],
    rejected: list[dict[str, str]],
    deferred: list[dict[str, str]],
    limit: int,
) -> dict[str, Any]:
    return {
        "counts": {
            "proposed": len(proposed),
            "approved": len(approved),
            "rejected": len(rejected),
            "deferred": len(deferred),
        },
        "proposed_ids": [row.get("proposal_id", "") for row in proposed[:limit]],
        "approved_ids": [row.get("proposal_id", "") for row in approved[:limit]],
        "rejected": [_review_reason(row, "rejection_reason") for row in rejected[:limit]],
        "deferred": [_review_reason(row, "deferral_reason") for row in deferred[:limit]],
    }


def _approved_impacts(
    approved: list[dict[str, str]],
    claims: dict[tuple[str, str], dict[str, str]],
    criteria: dict[tuple[str, str], dict[str, str]],
    config: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    hypotheses = [item.upper() for item in config["workbook"].get("hypotheses", HYPOTHESIS_NAMES)]
    summaries = []
    for hypothesis in hypotheses:
        items = []
        for row in approved:
            mi5 = (row.get(f"{hypothesis}_MI5") or "").strip()
            if not mi5:
                continue
            classification, strength = MI5_IMPACT.get(mi5, ("neutral_mixed", 2))
            claim = claims.get((row.get("claim_id", ""), row.get("source_id", "")), {})
            criteria_row = criteria.get((row.get("claim_id", ""), row.get("source_id", "")), {})
            items.append(
                {
                    "proposal_id": row.get("proposal_id", ""),
                    "claim_id": row.get("claim_id", ""),
                    "source_id": row.get("source_id", ""),
                    "category": row.get("category", ""),
                    "approved_weight_0_5": _float(row.get("approved_weight_0_5")),
                    "mi5_label": mi5,
                    "classification": classification,
                    "impact_strength": strength,
                    "evidence_preview": _preview(row.get("evidence_argument", "")),
                    "claim_preview": _preview(claim.get("claim_text", "")),
                    "criteria_highlights": _criteria_highlights([criteria_row], 1)[0]["highlights"] if criteria_row else [],
                    "trace": {"proposal_id": row.get("proposal_id", ""), "claim_id": row.get("claim_id", ""), "source_id": row.get("source_id", "")},
                }
            )
        ranked = sorted(items, key=lambda item: (-item["approved_weight_0_5"], -item["impact_strength"], item["proposal_id"]))
        counts = Counter(item["classification"] for item in items)
        summaries.append(
            {
                "hypothesis_id": hypothesis,
                "hypothesis_name": HYPOTHESIS_NAMES.get(hypothesis, hypothesis),
                "approved_rows": len(items),
                "counts_by_mi5_label": dict(Counter(item["mi5_label"] for item in items)),
                "classification_counts": {
                    "strong_support": counts.get("strong_support", 0),
                    "moderate_support": counts.get("moderate_support", 0),
                    "neutral_mixed": counts.get("neutral_mixed", 0),
                    "moderate_challenge": counts.get("moderate_challenge", 0),
                    "strong_challenge": counts.get("strong_challenge", 0),
                },
                "strongest_items": ranked[:limit],
            }
        )
    return summaries


def _debate_use(
    impacts: list[dict[str, Any]],
    criteria_highlights: list[dict[str, Any]],
    study_items: list[dict[str, Any]],
) -> dict[str, str]:
    support = []
    challenge = []
    for summary in impacts:
        for item in summary["strongest_items"]:
            if item["classification"] in SUPPORT_CLASSES:
                support.append((summary["hypothesis_id"], item))
            if item["classification"] in CHALLENGE_CLASSES:
                challenge.append((summary["hypothesis_id"], item))
    support.sort(key=lambda pair: (-pair[1]["approved_weight_0_5"], pair[0]))
    challenge.sort(key=lambda pair: (-pair[1]["approved_weight_0_5"], pair[0]))
    caution_flags = [flag for row in criteria_highlights for flag in row["highlights"] if flag in {"high uncertainty", "high defeater strength", "low clarity"}]
    strongest = support[0] if support else challenge[0] if challenge else None
    return {
        "strongest_line_of_use": (
            f"{strongest[1]['proposal_id']} is most useful for {strongest[0]}: {strongest[1]['evidence_preview']}"
            if strongest
            else "No approved source-specific impact is available yet."
        ),
        "most_important_caution": ", ".join(dict.fromkeys(caution_flags)) or "No major criteria caution is recorded.",
        "best_question_to_ask_next": (
            study_items[0].get("suggested_next_action", "Inspect extracted claims and criteria rows.")
            if study_items
            else "Inspect extracted claims and criteria rows."
        ),
    }


def _discord_section(
    source: dict[str, str],
    claims: list[dict[str, str]],
    impacts: list[dict[str, Any]],
    study_items: list[dict[str, Any]],
    trace: dict[str, Any],
    limit: int,
) -> str:
    source_id = source.get("source_id", "")
    lines = [f"Source Brief - {source_id}: {source.get('title', '') or 'Untitled Source'}", "", "Top claims:"]
    if claims:
        for index, claim in enumerate(claims[: min(3, limit)], start=1):
            lines.append(f"{index}. {claim.get('claim_id', '')} - {_preview(claim.get('claim_text', ''), 100)}")
    else:
        lines.append("None")
    lines.extend(["", "Approved impacts:"])
    shown = False
    for summary in impacts:
        counts = summary["classification_counts"]
        support = counts["strong_support"] + counts["moderate_support"]
        challenge = counts["strong_challenge"] + counts["moderate_challenge"]
        mixed = counts["neutral_mixed"]
        if support or challenge or mixed:
            shown = True
            lines.append(f"- {summary['hypothesis_id']}: {support} support / {mixed} mixed / {challenge} challenge")
    if not shown:
        lines.append("- None")
    lines.extend(["", "Unresolved:"])
    if study_items:
        for item in study_items[: min(3, limit)]:
            lines.append(
                f"- {item.get('proposal_id') or item.get('claim_id')} - {item.get('reason_for_study')}; {item.get('suggested_next_action')}."
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "Trace:",
            (
                f"{source_id} | Claims: {', '.join(trace['claim_ids']) or 'None'} | "
                f"Proposals: {', '.join(trace['proposal_ids']) or 'None'}"
            ),
        ]
    )
    return "\n".join(lines).rstrip()


def _trace_appendix(
    source_id: str,
    claims: list[dict[str, str]],
    proposed: list[dict[str, str]],
    approved: list[dict[str, str]],
    rejected: list[dict[str, str]],
    deferred: list[dict[str, str]],
) -> dict[str, Any]:
    proposal_rows = []
    for status, rows in [("proposed", proposed), ("approved", approved), ("rejected", rejected), ("deferred", deferred)]:
        for row in rows:
            proposal_rows.append(
                {
                    "proposal_id": row.get("proposal_id", ""),
                    "claim_id": row.get("claim_id", ""),
                    "source_id": row.get("source_id", source_id),
                    "status": status,
                    "category": row.get("category", ""),
                    "weight": row.get("approved_weight_0_5", "") or row.get("suggested_weight_0_5", ""),
                    "mi5_labels": {column: row.get(column, "") for column in MI5_COLUMNS if row.get(column, "")},
                }
            )
    return {
        "source_id": source_id,
        "claim_ids": [row.get("claim_id", "") for row in claims if row.get("claim_id")],
        "proposal_ids": [row["proposal_id"] for row in proposal_rows if row.get("proposal_id")],
        "proposals": proposal_rows,
    }


def _claim_summary(row: dict[str, str], criteria: dict[str, str]) -> dict[str, Any]:
    return {
        "claim_id": row.get("claim_id", ""),
        "source_id": row.get("source_id", ""),
        "claim_type": row.get("claim_type", ""),
        "claim_text": row.get("claim_text", ""),
        "claim_preview": _preview(row.get("claim_text", "")),
        "argument_summary": row.get("argument_summary", ""),
        "source_context": row.get("source_context", ""),
        "quoted_excerpt": row.get("quoted_excerpt", ""),
        "related_hypotheses": row.get("related_hypotheses", ""),
        "supports_hypotheses": row.get("supports_hypotheses", ""),
        "undermines_hypotheses": row.get("undermines_hypotheses", ""),
        "possible_defeater_for": row.get("possible_defeater_for", ""),
        "uncertainty_notes": row.get("uncertainty_notes", ""),
        "status": row.get("status", ""),
        "criteria_scores": {field: criteria.get(field, "") for field in CRITERIA_SCORE_FIELDS if criteria.get(field, "")},
    }


def _metadata_lines(source: dict[str, str], *, length: str) -> list[str]:
    fields = QUEUE_SCHEMAS["source_dossiers"] if length == "long" else [
        "source_id",
        "title",
        "author_or_speaker",
        "original_file_path",
        "url",
        "context",
        "short_summary",
        "worldview_or_perspective",
        "relevant_hypotheses",
        "reliability_notes",
        "bias_or_framing_notes",
        "my_notes",
    ]
    return [f"- {field}: {source.get(field, '')}" for field in fields if source.get(field, "") or length == "long"]


def _claim_lines(claims: list[dict[str, Any]], limit: int, *, length: str) -> list[str]:
    if not claims:
        return ["- None"]
    lines = [f"- Total claims: {len(claims)}"]
    for claim in claims[:limit]:
        line = f"- {claim['claim_id']} ({claim['claim_type'] or 'untyped'}): {claim['claim_preview']}"
        extras = []
        for field in ["argument_summary", "related_hypotheses", "supports_hypotheses", "undermines_hypotheses", "uncertainty_notes", "status"]:
            if claim.get(field):
                extras.append(f"{field}: {claim[field]}")
        if length == "long" and claim.get("source_context"):
            extras.append(f"source_context: {claim['source_context']}")
        if extras:
            line += f" ({'; '.join(extras)})"
        lines.append(line)
    return lines


def _criteria_lines(highlights: list[dict[str, Any]], *, length: str) -> list[str]:
    if not highlights:
        return ["- None"]
    lines = ["- Salience is listed separately from evidential strength."]
    for row in highlights:
        flags = ", ".join(row["highlights"]) or "no threshold flags"
        line = f"- {row['claim_id']}: {flags}"
        if length == "long":
            line += f" scores={row['scores']} notes={row['notes']}"
        lines.append(line)
    return lines


def _outcome_lines(outcomes: dict[str, Any], *, length: str) -> list[str]:
    counts = outcomes["counts"]
    lines = [
        f"- Proposed updates: {counts['proposed']}",
        f"- Approved updates: {counts['approved']}",
        f"- Rejected updates: {counts['rejected']}",
        f"- Deferred updates: {counts['deferred']}",
        f"- Proposed IDs: {', '.join(outcomes['proposed_ids']) or 'None'}",
        f"- Approved IDs: {', '.join(outcomes['approved_ids']) or 'None'}",
    ]
    if length != "short":
        lines.extend([f"- Rejected: {_format_reason(row)}" for row in outcomes["rejected"]] or ["- Rejected: None"])
        lines.extend([f"- Deferred: {_format_reason(row)}" for row in outcomes["deferred"]] or ["- Deferred: None"])
    return lines


def _impact_lines(impacts: list[dict[str, Any]], *, length: str) -> list[str]:
    lines = []
    for summary in impacts:
        counts = summary["classification_counts"]
        if not summary["approved_rows"] and length == "short":
            continue
        lines.extend(
            [
                f"- {summary['hypothesis_id']} - {summary['hypothesis_name']}",
                f"  Approved rows: {summary['approved_rows']}",
                f"  Strong support: {counts['strong_support']}",
                f"  Moderate support: {counts['moderate_support']}",
                f"  Neutral/mixed: {counts['neutral_mixed']}",
                f"  Moderate challenge: {counts['moderate_challenge']}",
                f"  Strong challenge: {counts['strong_challenge']}",
            ]
        )
        if summary["strongest_items"]:
            item = summary["strongest_items"][0]
            lines.append(
                f"  Strongest item: {item['proposal_id']} / {item['claim_id']}, Weight {item['approved_weight_0_5']}, MI5 {item['mi5_label']}"
            )
        if length == "long":
            for item in summary["strongest_items"]:
                lines.append(f"  - {item['proposal_id']} / {item['claim_id']} - {item['classification']} - {item['evidence_preview']}")
    return lines or ["- None"]


def _study_lines(items: list[dict[str, Any]], limit: int, *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = [f"- Total source-specific study candidates shown: {min(len(items), limit)}"]
    for item in items[:limit]:
        line = (
            f"- {item.get('proposal_id') or item.get('claim_id') or item.get('source_id')}: "
            f"{item.get('reason_for_study')}. Next: {item.get('suggested_next_action')}."
        )
        if length == "long":
            line += f" Trace: {item.get('trace_summary')} Evidence: {item.get('evidence_preview')}"
        lines.append(line)
    return lines


def _debate_use_lines(debate_use: dict[str, str]) -> list[str]:
    return [
        f"- Strongest line of use: {debate_use['strongest_line_of_use']}",
        f"- Most important caution: {debate_use['most_important_caution']}",
        f"- Best question to ask next: {debate_use['best_question_to_ask_next']}",
    ]


def _trace_lines(trace: dict[str, Any], *, length: str) -> list[str]:
    lines = [
        f"- Source ID: {trace['source_id']}",
        f"- Claim IDs: {', '.join(trace['claim_ids']) or 'None'}",
        f"- Proposal IDs: {', '.join(trace['proposal_ids']) or 'None'}",
    ]
    if length != "short":
        lines.extend(
            f"- {row['proposal_id']} | {row['claim_id']} | {row['source_id']} | {row['status']} | {row['category']} | {row['weight']} | {row['mi5_labels']}"
            for row in trace["proposals"]
        )
    return lines


def _raw_excerpt(
    source: dict[str, str],
    *,
    base_dir: str | Path,
    max_characters: int,
    enabled: bool,
    warnings: list[str],
) -> dict[str, Any]:
    path_value = source.get("original_file_path", "")
    result = {"included": False, "path": path_value, "text": "", "characters_included": 0, "truncated": False, "warning": ""}
    if not enabled:
        return result
    if not path_value:
        result["warning"] = "No original_file_path is recorded for this source."
        warnings.append(result["warning"])
        return result
    path = resolve_project_path(path_value, base_dir=base_dir)
    if not path.exists():
        result["warning"] = f"Raw source file not found: {path}"
        warnings.append(result["warning"])
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    result.update(
        {
            "included": True,
            "path": str(path),
            "text": text[:max_characters],
            "characters_included": min(len(text), max_characters),
            "truncated": len(text) > max_characters,
        }
    )
    return result


def _raw_excerpt_block(excerpt: dict[str, Any]) -> str:
    marker = "\n\n[truncated]" if excerpt.get("truncated") else ""
    return f"Path: `{excerpt.get('path', '')}`\n\n```text\n{excerpt.get('text', '')}{marker}\n```"


def _review_reason(row: dict[str, str], reason_field: str) -> dict[str, str]:
    return {
        "proposal_id": row.get("proposal_id", ""),
        "claim_id": row.get("claim_id", ""),
        "reason": row.get(reason_field, ""),
        "notes": row.get("notes", ""),
    }


def _format_reason(row: dict[str, str]) -> str:
    return f"{row.get('proposal_id', '')} / {row.get('claim_id', '')} - {row.get('reason', '') or row.get('notes', '') or 'no reason recorded'}"


def _queue_dir(config: dict[str, Any], base_dir: str | Path) -> Path:
    value = Path(config["queues"]["base_dir"])
    return value if value.is_absolute() else Path(base_dir) / value


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _float(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _preview(value: str, limit: int = 140) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _error_result(message: str, source_id: str | None) -> dict[str, Any]:
    return {
        "operation": "source_brief",
        "generated_at": timestamp_iso(),
        "source_id": source_id or "",
        "source_metadata": {},
        "raw_excerpt": {"included": False, "path": "", "text": "", "characters_included": 0, "truncated": False, "warning": ""},
        "extracted_claims": [],
        "criteria_highlights": [],
        "proposal_review_outcomes": {"counts": {"proposed": 0, "approved": 0, "rejected": 0, "deferred": 0}},
        "approved_hypothesis_impacts": [],
        "unresolved_study_items": [],
        "debate_use": {},
        "discord_section": "",
        "trace_appendix": {"source_id": source_id or "", "claim_ids": [], "proposal_ids": [], "proposals": []},
        "warnings": [],
        "errors": [message],
        "overall_status": "fail",
        "no_workbook_or_queue_data_modified": True,
    }
