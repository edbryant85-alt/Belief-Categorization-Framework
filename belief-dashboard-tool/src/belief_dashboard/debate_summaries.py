from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


HYPOTHESIS_NAMES = {
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

MI5_IMPACT = {
    "Almost certain": ("strong_support", 5),
    "Highly likely": ("strong_support", 4),
    "Likely / probable": ("moderate_support", 3),
    "Roughly even chance": ("neutral_mixed", 2),
    "": ("neutral_mixed", 2),
    "Unlikely": ("moderate_challenge", 3),
    "Highly unlikely": ("strong_challenge", 4),
    "Remote chance": ("strong_challenge", 5),
}

DEFEATER_TERMS = ["defeater", "objection", "counterargument", "counter-argument", "challenge"]
COUNTER_DEFEATER_TERMS = ["counter_defeater", "counter-defeater", "counter defeater"]
OPEN_QUESTION_TERMS = ["uncertain", "uncertainty", "open question", "unknown", "needs review"]


def build_debate_summary(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    all_hypotheses: bool = False,
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    source_id: str | None = None,
    category: str | None = None,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    base_path = Path(base_dir)
    debate_config = config.get("debate_summaries", {})
    hypotheses = [item.upper() for item in config["workbook"].get("hypotheses", HYPOTHESIS_NAMES)]
    if not all_hypotheses:
        if not hypothesis:
            return _error_result("Supply either --hypothesis HYPOTHESIS_ID or --all.", hypothesis, all_hypotheses)
        if hypothesis.upper() not in hypotheses:
            return _error_result(f"Unknown hypothesis ID: {hypothesis}", hypothesis, all_hypotheses)
        selected = [hypothesis.upper()]
    else:
        selected = hypotheses

    queue_dir = base_path / config["queues"]["base_dir"] if not Path(config["queues"]["base_dir"]).is_absolute() else Path(config["queues"]["base_dir"])
    files = config["queues"]["files"]
    approved_path = queue_dir / files["approved_updates"]
    if not approved_path.exists():
        return _error_result(f"Approved updates file not found: {approved_path}", hypothesis, all_hypotheses)

    rows = _read_csv(approved_path)
    sources = _index_rows(_optional_csv(queue_dir / files["source_dossiers"]), ["source_id"])
    claims = _index_rows(_optional_csv(queue_dir / files["extracted_claims"]), ["claim_id", "source_id"])
    criteria = _index_rows(_optional_csv(queue_dir / files["criteria_matrix"]), ["claim_id", "source_id"])

    filters = {
        "hypothesis": hypothesis.upper() if hypothesis else "",
        "all": all_hypotheses,
        "limit": limit if limit is not None else debate_config.get("default_limit", 10),
        "min_weight": min_weight if min_weight is not None else debate_config.get("default_min_weight", 0),
        "exported_only": exported_only,
        "include_unexported": include_unexported,
        "source_id": source_id or "",
        "category": category or "",
        "length": length,
    }
    filtered = _apply_filters(rows, filters)
    summaries = [
        _summarize_hypothesis(
            hypothesis_id=item,
            rows=filtered,
            sources=sources,
            claims=claims,
            criteria=criteria,
            limit=int(filters["limit"]),
            include_source_titles=debate_config.get("include_source_titles", True),
            include_claim_context=debate_config.get("include_claim_context", True),
            include_criteria_scores=debate_config.get("include_criteria_scores", True),
        )
        for item in selected
    ]
    counts = {
        "approved_rows_total": len(rows),
        "approved_rows_considered": len(filtered),
        "hypotheses_count": len(summaries),
    }
    return {
        "operation": "debate_summary",
        "generated_at": timestamp_iso(generated_at),
        "overall_status": "pass",
        "filters": filters,
        "counts": counts,
        "hypotheses": summaries,
        "warnings": [],
        "errors": [],
        "no_workbook_or_queue_data_modified": True,
    }


def render_debate_summary(result: dict[str, Any], *, style: str = "table", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Debate summary status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return _render_discord(result)

    lines = [
        "Debate summary",
        f"Status: {result['overall_status']}",
        f"Rows considered: {result['counts']['approved_rows_considered']} of {result['counts']['approved_rows_total']}",
        "Caveat: This summarizes approved records for debate prep. It is not a final declaration of belief.",
        "",
    ]
    for summary in result["hypotheses"]:
        lines.extend(_render_hypothesis(summary, length=length))
        lines.append("")
    lines.append("No workbook or queue data was modified.")
    return "\n".join(lines).rstrip()


def write_debate_summary_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    label = "ALL" if result["filters"].get("all") else result["filters"].get("hypothesis", "UNKNOWN")
    markdown_path = reports_path / f"debate_summary_{label}_{stamp}.md"
    json_path = reports_path / f"debate_summary_{label}_{stamp}.json"
    markdown_path.write_text(_render_markdown_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _summarize_hypothesis(
    *,
    hypothesis_id: str,
    rows: list[dict[str, str]],
    sources: dict[tuple[str, ...], dict[str, str]],
    claims: dict[tuple[str, ...], dict[str, str]],
    criteria: dict[tuple[str, ...], dict[str, str]],
    limit: int,
    include_source_titles: bool,
    include_claim_context: bool,
    include_criteria_scores: bool,
) -> dict[str, Any]:
    enriched = [
        _enrich_row(
            row,
            hypothesis_id,
            sources,
            claims,
            criteria,
            include_source_titles=include_source_titles,
            include_claim_context=include_claim_context,
            include_criteria_scores=include_criteria_scores,
        )
        for row in rows
    ]
    ranked = sorted(enriched, key=_rank_key)
    support = [item for item in ranked if item["classification"] in {"strong_support", "moderate_support"}]
    challenge = [item for item in ranked if item["classification"] in {"strong_challenge", "moderate_challenge"}]
    neutral = [item for item in ranked if item["classification"] == "neutral_mixed"]
    defeaters = [item for item in ranked if item["is_defeater"]]
    counter_defeaters = [item for item in ranked if item["is_counter_defeater"]]
    open_questions = [item for item in ranked if item["open_question_note"]]
    salience = [item for item in ranked if item.get("salience_flags")]
    return {
        "hypothesis_id": hypothesis_id,
        "hypothesis_name": HYPOTHESIS_NAMES.get(hypothesis_id, hypothesis_id),
        "counts": {
            "rows_considered": len(enriched),
            "support": len(support),
            "challenge": len(challenge),
            "neutral_mixed": len(neutral),
            "defeaters": len(defeaters),
            "counter_defeaters": len(counter_defeaters),
            "open_questions": len(open_questions),
        },
        "support_items": support[:limit],
        "challenge_items": challenge[:limit],
        "neutral_items": neutral[:limit],
        "defeaters": defeaters[:limit],
        "counter_defeaters": counter_defeaters[:limit],
        "open_questions": open_questions[:limit],
        "salient_items": salience[:limit],
        "debate_angle": _debate_angle(hypothesis_id, support, challenge, defeaters),
    }


def _enrich_row(
    row: dict[str, str],
    hypothesis_id: str,
    sources: dict[tuple[str, ...], dict[str, str]],
    claims: dict[tuple[str, ...], dict[str, str]],
    criteria: dict[tuple[str, ...], dict[str, str]],
    *,
    include_source_titles: bool,
    include_claim_context: bool,
    include_criteria_scores: bool,
) -> dict[str, Any]:
    source = sources.get((row.get("source_id", ""),), {})
    claim = claims.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    criteria_row = criteria.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    mi5 = (row.get(f"{hypothesis_id}_MI5") or "").strip()
    classification, impact_strength = MI5_IMPACT.get(mi5, ("neutral_mixed", 2))
    text_for_flags = " ".join(
        [
            row.get("category", ""),
            row.get("notes", ""),
            claim.get("claim_type", ""),
            claim.get("uncertainty_notes", ""),
            claim.get("possible_defeater_for", ""),
            criteria_row.get("notes", ""),
        ]
    ).lower()
    item = {
        "proposal_id": row.get("proposal_id", ""),
        "claim_id": row.get("claim_id", ""),
        "source_id": row.get("source_id", ""),
        "category": row.get("category", ""),
        "source_book": row.get("source_book", ""),
        "approved_weight_0_5": _float_value(row.get("approved_weight_0_5")),
        "hypothesis_mi5_label": mi5,
        "classification": classification,
        "impact_strength": impact_strength,
        "evidence_preview": _preview(row.get("evidence_argument", "")),
        "notes_preview": _preview(row.get("notes", "")),
        "approved_date": row.get("approved_date", ""),
        "export_status": row.get("export_status", ""),
        "trace_ids": {
            "proposal_id": row.get("proposal_id", ""),
            "claim_id": row.get("claim_id", ""),
            "source_id": row.get("source_id", ""),
        },
        "is_defeater": any(term in text_for_flags for term in DEFEATER_TERMS) or claim.get("claim_type", "") in {"objection", "defeater"},
        "is_counter_defeater": any(term in text_for_flags for term in COUNTER_DEFEATER_TERMS) or claim.get("claim_type", "") == "counter_defeater",
        "open_question_note": _preview(claim.get("uncertainty_notes", "") or row.get("notes", "")) if any(term in text_for_flags for term in OPEN_QUESTION_TERMS) else "",
    }
    if include_source_titles:
        item["source_title"] = source.get("title", "")
        item["source_summary_preview"] = _preview(source.get("short_summary", ""))
    if include_claim_context:
        item["claim_type"] = claim.get("claim_type", "")
        item["claim_preview"] = _preview(claim.get("claim_text", ""))
        item["claim_context_preview"] = _preview(claim.get("source_context", ""))
    if include_criteria_scores:
        item["criteria_scores"] = {field: criteria_row.get(field, "") for field in CRITERIA_SCORE_FIELDS if criteria_row.get(field, "")}
        item["salience_flags"] = _salience_flags(criteria_row)
    return item


def _rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -float(item.get("approved_weight_0_5", 0)),
        -int(item.get("impact_strength", 0)),
        _reverse_date_key(str(item.get("approved_date", ""))),
        str(item.get("proposal_id", "")),
    )


def _reverse_date_key(value: str) -> str:
    if not value:
        return "9999-99-99"
    return "".join(str(9 - int(char)) if char.isdigit() else char for char in value)


def _apply_filters(rows: list[dict[str, str]], filters: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for row in rows:
        if float(filters["min_weight"]) and _float_value(row.get("approved_weight_0_5")) < float(filters["min_weight"]):
            continue
        if filters["exported_only"] and (row.get("export_status") or "").strip() != "exported":
            continue
        if filters["source_id"] and row.get("source_id") != filters["source_id"]:
            continue
        if filters["category"] and filters["category"].lower() not in (row.get("category") or "").lower():
            continue
        result.append(row)
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _optional_csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path) if path.exists() else []


def _index_rows(rows: list[dict[str, str]], fields: list[str]) -> dict[tuple[str, ...], dict[str, str]]:
    return {tuple(row.get(field, "") for field in fields): row for row in rows}


def _float_value(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _preview(value: str, limit: int = 140) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _salience_flags(row: dict[str, str]) -> list[str]:
    labels = []
    mapping = {
        "relevance_0_5": "high relevance",
        "reliability_0_5": "high reliability",
        "argument_strength_0_5": "high argument strength",
        "explanatory_power_0_5": "high explanatory power",
        "defeater_strength_0_5": "high defeater strength",
        "existential_salience_0_5": "high existential salience",
        "emotional_salience_0_5": "high emotional salience",
    }
    for field, label in mapping.items():
        if _float_value(row.get(field)) >= 4:
            labels.append(label)
    return labels


def _debate_angle(hypothesis_id: str, support: list[dict[str, Any]], challenge: list[dict[str, Any]], defeaters: list[dict[str, Any]]) -> str:
    if support and challenge:
        return f"For {hypothesis_id}, lead with the strongest support while naming the best challenge directly."
    if support:
        return f"For {hypothesis_id}, the approved record currently gives more obvious support than challenge."
    if challenge:
        return f"For {hypothesis_id}, prepare to answer the strongest challenge before making a positive case."
    if defeaters:
        return f"For {hypothesis_id}, focus first on objections and defeaters because support/challenge labels are sparse."
    return f"For {hypothesis_id}, the approved record is too thin for a confident debate angle."


def _render_hypothesis(summary: dict[str, Any], *, length: str) -> list[str]:
    lines = [
        f"Hypothesis: {summary['hypothesis_id']} - {summary['hypothesis_name']}",
        f"Rows considered: {summary['counts']['rows_considered']}",
        "",
        "Strongest supporting evidence:",
        *_item_lines(summary["support_items"], length=length),
        "",
        "Strongest challenging evidence:",
        *_item_lines(summary["challenge_items"], length=length),
        "",
        "Possible defeaters / objections:",
        *_item_lines(summary["defeaters"], length=length),
        "",
        "Open questions or uncertainty notes:",
        *_open_question_lines(summary["open_questions"]),
        "",
        "Emotionally/existentially salient items:",
        *_salience_lines(summary["salient_items"]),
        "",
        "Debate angle:",
        f"- {summary['debate_angle']}",
    ]
    return lines


def _item_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = (
            f"- [{item['proposal_id']} / {item['claim_id']} / {item['source_id']}] "
            f"Weight {item['approved_weight_0_5']}, MI5: {item['hypothesis_mi5_label'] or 'blank'} - "
            f"{item['evidence_preview']}"
        )
        extras = []
        if item.get("category"):
            extras.append(f"category: {item['category']}")
        if item.get("source_title"):
            extras.append(f"source: {item['source_title']}")
        if item.get("claim_type"):
            extras.append(f"claim type: {item['claim_type']}")
        if length == "long" and item.get("notes_preview"):
            extras.append(f"notes: {item['notes_preview']}")
        if length == "long" and item.get("criteria_scores"):
            extras.append(f"criteria: {item['criteria_scores']}")
        if extras:
            line += f" ({'; '.join(extras)})"
        lines.append(line)
    return lines


def _open_question_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- [{item['proposal_id']} / {item['source_id']}] {item['open_question_note']}" for item in items]


def _salience_lines(items: list[dict[str, Any]]) -> list[str]:
    flagged = [item for item in items if item.get("salience_flags")]
    if not flagged:
        return ["- None"]
    return [f"- [{item['proposal_id']} / {item['source_id']}] {', '.join(item['salience_flags'])} - {item['evidence_preview']}" for item in flagged]


def _render_discord(result: dict[str, Any]) -> str:
    lines = []
    for summary in result.get("hypotheses", []):
        lines.extend(
            [
                f"Hypothesis: {summary['hypothesis_id']} - {summary['hypothesis_name']}",
                "",
                "Top support:",
                *_numbered_compact(summary["support_items"]),
                "",
                "Top challenge:",
                *_numbered_compact(summary["challenge_items"]),
                "",
                "Key uncertainty:",
                *_open_question_lines(summary["open_questions"][:1]),
                "",
                "Debate angle:",
                f"- {summary['debate_angle']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _numbered_compact(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["None"]
    return [
        f"{index}. [{item['proposal_id']} / {item['source_id']}] Weight {item['approved_weight_0_5']}, MI5: {item['hypothesis_mi5_label'] or 'blank'} - {item['evidence_preview']}"
        for index, item in enumerate(items[:3], start=1)
    ]


def _render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Debate Summary",
        "",
        f"- Timestamp: `{result['generated_at']}`",
        f"- Overall status: `{result['overall_status']}`",
        f"- Filters: `{json.dumps(result['filters'], sort_keys=True)}`",
        f"- Approved rows considered: `{result['counts']['approved_rows_considered']}`",
        "- No workbook or queue data was modified: `True`",
        "",
        "## Summary",
        "",
        render_debate_summary(result, length="long"),
        "",
    ]
    return "\n".join(lines)


def _error_result(message: str, hypothesis: str | None, all_hypotheses: bool) -> dict[str, Any]:
    return {
        "operation": "debate_summary",
        "generated_at": timestamp_iso(),
        "overall_status": "fail",
        "filters": {"hypothesis": hypothesis or "", "all": all_hypotheses},
        "counts": {"approved_rows_total": 0, "approved_rows_considered": 0, "hypotheses_count": 0},
        "hypotheses": [],
        "warnings": [],
        "errors": [message],
        "no_workbook_or_queue_data_modified": True,
    }
