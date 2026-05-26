from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.debate_summaries import HYPOTHESIS_NAMES
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


UNCERTAINTY_TERMS = ["uncertain", "uncertainty", "open question", "unknown", "needs review", "clarify"]
DEFEATER_TERMS = ["defeater", "objection", "counterargument", "challenge"]
REFLECTION_TEMPLATE_MARKERS = [
    "# Reflection Journal",
    "Use this space for brief process notes, review reflections, and questions to revisit.",
    "## Entries",
]


def build_study_queue(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    all_hypotheses: bool = False,
    topic: str | None = None,
    limit: int | None = None,
    min_priority: float | None = None,
    source_id: str | None = None,
    category: str | None = None,
    include_deferred: bool | None = None,
    include_rejected: bool = False,
    include_reflections: bool | None = None,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    study_config = config.get("study_queue", {})
    hypotheses = [item.upper() for item in config["workbook"].get("hypotheses", HYPOTHESIS_NAMES)]
    selected_hypothesis = (hypothesis or "").upper()
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _error_result(f"Unknown hypothesis ID: {hypothesis}")

    queue_dir = _queue_dir(config, base_dir)
    files = config["queues"]["files"]
    approved = _read_optional_csv(queue_dir / files["approved_updates"])
    deferred = _read_optional_csv(queue_dir / files["deferred_updates"])
    rejected = _read_optional_csv(queue_dir / files["rejected_updates"])
    sources = _index(_read_optional_csv(queue_dir / files["source_dossiers"]), ["source_id"])
    claims = _index(_read_optional_csv(queue_dir / files["extracted_claims"]), ["claim_id", "source_id"])
    criteria = _index(_read_optional_csv(queue_dir / files["criteria_matrix"]), ["claim_id", "source_id"])
    journal = _read_reflection_journal(queue_dir / files["reflection_journal"])

    filters = {
        "hypothesis": selected_hypothesis,
        "all": all_hypotheses,
        "topic": topic or "",
        "limit": limit if limit is not None else study_config.get("default_limit", 25),
        "min_priority": min_priority if min_priority is not None else study_config.get("default_min_priority", 0),
        "source_id": source_id or "",
        "category": category or "",
        "include_deferred": study_config.get("include_deferred_updates", True) if include_deferred is None else include_deferred,
        "include_rejected": include_rejected,
        "include_reflections": study_config.get("include_reflection_journal", True) if include_reflections is None else include_reflections,
        "length": length,
    }
    thresholds = {
        "high_salience": float(study_config.get("high_salience_threshold", 4)),
        "high_uncertainty": float(study_config.get("high_uncertainty_threshold", 4)),
        "high_defeater": float(study_config.get("high_defeater_threshold", 4)),
        "low_clarity": float(study_config.get("low_clarity_threshold", 2)),
    }

    candidates: list[dict[str, Any]] = []
    for row in approved:
        item = _approved_candidate(row, sources, claims, criteria, filters, thresholds, hypotheses)
        if item and _passes_filters(item, filters):
            candidates.append(item)
    if filters["include_deferred"]:
        for row in deferred:
            item = _deferred_candidate(row, sources, claims, filters)
            if item and _passes_filters(item, filters):
                candidates.append(item)
    if filters["include_rejected"]:
        for row in rejected:
            item = _rejected_candidate(row, sources, claims, filters)
            if item and _passes_filters(item, filters):
                candidates.append(item)
    for claim in claims.values():
        item = _claim_candidate(claim, sources, criteria, filters, thresholds)
        if item and _passes_filters(item, filters):
            candidates.append(item)
    if filters["include_reflections"] and journal:
        candidates.append(_reflection_candidate(journal))

    candidates = _dedupe_candidates(candidates)
    candidates.sort(key=_rank_key)
    filtered = [item for item in candidates if item["priority_score"] >= float(filters["min_priority"])]
    limited = filtered[: int(filters["limit"])]
    priority_summary = _priority_summary(filtered)
    unresolved = [item for item in filtered if "high defeater strength" in item["reason_for_study"] or "defeater" in item["reason_for_study"]][: int(filters["limit"])]
    high_salience = [item for item in filtered if any("salience" in value or "moral stakes" in value for value in item["criteria_highlights"])][: int(filters["limit"])]
    low_clarity = [item for item in filtered if "low clarity" in item["reason_for_study"] or "high uncertainty" in item["reason_for_study"]][: int(filters["limit"])]
    deferred_items = [item for item in filtered if item["source_kind"] == "deferred_update"][: int(filters["limit"])]

    return {
        "operation": "study_queue",
        "generated_at": timestamp_iso(generated_at),
        "overall_status": "pass",
        "filters": filters,
        "counts": {
            "candidates_total": len(candidates),
            "candidates_after_min_priority": len(filtered),
            "candidates_shown": len(limited),
        },
        "priority_summary": priority_summary,
        "study_items": limited,
        "unresolved_defeaters": unresolved,
        "high_salience_items": high_salience,
        "low_clarity_items": low_clarity,
        "deferred_items": deferred_items,
        "suggested_study_plan": _study_plan(limited),
        "trace_appendix": _trace_appendix(limited),
        "warnings": [] if filtered else ["No study candidates matched the current filters."],
        "errors": [],
        "no_workbook_or_queue_data_modified": True,
    }


def render_study_queue(result: dict[str, Any], *, style: str = "table", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Study queue status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return _render_discord(result)

    lines = [
        "Study Queue",
        f"Generated: {result['generated_at']}",
        f"Filters: {json.dumps(result['filters'], sort_keys=True)}",
        f"Total study candidates: {result['counts']['candidates_after_min_priority']}",
        "Caveat: This is a study aid, not a belief conclusion.",
        "",
        "Priority Summary:",
        *_summary_lines(result["priority_summary"]),
        "",
        "Top Study Items:",
        *_item_lines(result["study_items"], length=length),
        "",
        "Unresolved Defeaters:",
        *_item_lines(result["unresolved_defeaters"], length=length),
        "",
        "High-Salience Reflection Items:",
        *_item_lines(result["high_salience_items"], length=length),
        "",
        "Low-Clarity / High-Uncertainty Items:",
        *_item_lines(result["low_clarity_items"], length=length),
        "",
        "Deferred Items:",
        *_item_lines(result["deferred_items"], length=length),
        "",
        "Suggested Study Plan:",
        *[f"{index}. {step}" for index, step in enumerate(result["suggested_study_plan"], start=1)],
        "",
        "Trace Appendix:",
        *_appendix_lines(result["trace_appendix"]),
        "",
        "No workbook or queue data was modified.",
    ]
    return "\n".join(lines).rstrip()


def write_study_queue_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    label = _filename_label(result["filters"])
    markdown_path = reports_path / f"study_queue_{label}_{stamp}.md"
    json_path = reports_path / f"study_queue_{label}_{stamp}.json"
    markdown_path.write_text(_render_markdown_report(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _approved_candidate(
    row: dict[str, str],
    sources: dict[tuple[str, ...], dict[str, str]],
    claims: dict[tuple[str, ...], dict[str, str]],
    criteria: dict[tuple[str, ...], dict[str, str]],
    filters: dict[str, Any],
    thresholds: dict[str, float],
    hypotheses: list[str],
) -> dict[str, Any] | None:
    claim = claims.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    source = sources.get((row.get("source_id", ""),), {})
    criteria_row = criteria.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    text = _combined_text(row, source, claim, criteria_row)
    if filters["hypothesis"] and not row.get(f"{filters['hypothesis']}_MI5", ""):
        return None
    reasons = []
    score = _float(row.get("approved_weight_0_5"))
    uncertainty = _float(criteria_row.get("uncertainty_0_5"))
    defeater = _float(criteria_row.get("defeater_strength_0_5"))
    existential = _float(criteria_row.get("existential_salience_0_5"))
    moral = _float(criteria_row.get("moral_stakes_0_5"))
    emotional = _float(criteria_row.get("emotional_salience_0_5"))
    clarity = _float(criteria_row.get("clarity_0_5"))
    if uncertainty >= thresholds["high_uncertainty"] or _contains_any(text, UNCERTAINTY_TERMS):
        reasons.append("high uncertainty")
        score += uncertainty
    if defeater >= thresholds["high_defeater"] or _contains_any(text, DEFEATER_TERMS) or claim.get("claim_type") in {"objection", "defeater", "counter_defeater"}:
        reasons.append("high defeater strength")
        score += defeater
    if max(existential, moral, emotional) >= thresholds["high_salience"]:
        reasons.append("high salience")
        score += max(existential, moral, emotional)
    if clarity and clarity <= thresholds["low_clarity"]:
        reasons.append("low clarity")
        score += 2
    if _conflicting_mi5(row, hypotheses):
        reasons.append("conflicting MI5 impacts")
        score += 1.5
    if filters["hypothesis"] and row.get(f"{filters['hypothesis']}_MI5", ""):
        score += 1
    if filters["topic"] and filters["topic"].lower() in text.lower():
        score += 1
    if not reasons:
        return None
    return _base_item(
        source_kind="approved_update",
        row=row,
        source=source,
        claim=claim,
        criteria_row=criteria_row,
        score=score,
        reason=", ".join(reasons),
        action=_suggest_action(reasons, claim.get("claim_type", "")),
        hypotheses=hypotheses,
    )


def _deferred_candidate(
    row: dict[str, str],
    sources: dict[tuple[str, ...], dict[str, str]],
    claims: dict[tuple[str, ...], dict[str, str]],
    filters: dict[str, Any],
) -> dict[str, Any] | None:
    source = sources.get((row.get("source_id", ""),), {})
    claim = claims.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    if filters["hypothesis"] and filters["hypothesis"] not in _claim_hypothesis_text(claim):
        return None
    score = 4.0 + (1 if filters["topic"] and filters["topic"].lower() in _combined_text(row, source, claim, {}).lower() else 0)
    return _base_item(
        source_kind="deferred_update",
        row=row,
        source=source,
        claim=claim,
        criteria_row={},
        score=score,
        reason="deferred update",
        action="revisit deferred update",
        hypotheses=[],
        uncertainty_notes=row.get("deferral_reason", ""),
    ) | {"revisit_date": row.get("revisit_date", "")}


def _rejected_candidate(
    row: dict[str, str],
    sources: dict[tuple[str, ...], dict[str, str]],
    claims: dict[tuple[str, ...], dict[str, str]],
    filters: dict[str, Any],
) -> dict[str, Any] | None:
    source = sources.get((row.get("source_id", ""),), {})
    claim = claims.get((row.get("claim_id", ""), row.get("source_id", "")), {})
    if filters["hypothesis"] and filters["hypothesis"] not in _claim_hypothesis_text(claim):
        return None
    return _base_item(
        source_kind="rejected_update",
        row=row,
        source=source,
        claim=claim,
        criteria_row={},
        score=2.5,
        reason="rejected update requested for review context",
        action="inspect rejection reason before reconsidering",
        hypotheses=[],
        uncertainty_notes=row.get("rejection_reason", ""),
    )


def _claim_candidate(
    claim: dict[str, str],
    sources: dict[tuple[str, ...], dict[str, str]],
    criteria: dict[tuple[str, ...], dict[str, str]],
    filters: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any] | None:
    claim_type = claim.get("claim_type", "")
    criteria_row = criteria.get((claim.get("claim_id", ""), claim.get("source_id", "")), {})
    text = _combined_text({}, sources.get((claim.get("source_id", ""),), {}), claim, criteria_row)
    if filters["hypothesis"] and filters["hypothesis"] not in _claim_hypothesis_text(claim):
        return None
    if not (claim.get("uncertainty_notes") or claim_type in {"objection", "defeater", "counter_defeater", "personal_reflection"}):
        return None
    score = 3.0 + _float(criteria_row.get("uncertainty_0_5")) + _float(criteria_row.get("defeater_strength_0_5"))
    if claim_type in {"objection", "defeater", "counter_defeater"}:
        score += 2
    return _base_item(
        source_kind="extracted_claim",
        row={"claim_id": claim.get("claim_id", ""), "source_id": claim.get("source_id", ""), "evidence_argument": claim.get("claim_text", "")},
        source=sources.get((claim.get("source_id", ""),), {}),
        claim=claim,
        criteria_row=criteria_row,
        score=score,
        reason=f"claim marked {claim_type or 'uncertain'}",
        action=_suggest_action(["high uncertainty"], claim_type),
        hypotheses=[],
        uncertainty_notes=claim.get("uncertainty_notes", ""),
    ) if _passes_topic_text(text, filters["topic"]) else None


def _reflection_candidate(text: str) -> dict[str, Any]:
    return {
        "study_item_id": "STUDY_REFLECTION_JOURNAL",
        "source_kind": "reflection_journal",
        "priority_score": 3.0,
        "priority_category": "medium",
        "reason_for_study": "reflection journal contains notes",
        "suggested_next_action": "write reflection",
        "hypothesis_ids": [],
        "topic_matches": [],
        "proposal_id": "",
        "claim_id": "",
        "source_id": "",
        "source_title": "",
        "source_book": "",
        "category": "reflection",
        "claim_type": "",
        "approved_weight_0_5": 0.0,
        "relevant_mi5_labels": {},
        "uncertainty_notes": "",
        "criteria_highlights": [],
        "evidence_preview": _preview(text),
        "notes_preview": "",
        "trace_summary": "reflection_journal.md",
    }


def _base_item(
    *,
    source_kind: str,
    row: dict[str, str],
    source: dict[str, str],
    claim: dict[str, str],
    criteria_row: dict[str, str],
    score: float,
    reason: str,
    action: str,
    hypotheses: list[str],
    uncertainty_notes: str = "",
) -> dict[str, Any]:
    proposal_id = row.get("proposal_id", "")
    claim_id = row.get("claim_id", "")
    source_id = row.get("source_id", "")
    mi5 = {hypothesis: row.get(f"{hypothesis}_MI5", "") for hypothesis in hypotheses if row.get(f"{hypothesis}_MI5", "")}
    highlights = _criteria_highlights(criteria_row)
    return {
        "study_item_id": _study_item_id(source_kind, proposal_id, claim_id, source_id),
        "source_kind": source_kind,
        "priority_score": round(score, 2),
        "priority_category": _priority_category(score),
        "reason_for_study": reason,
        "suggested_next_action": action,
        "hypothesis_ids": [key for key, value in mi5.items() if value],
        "topic_matches": [],
        "proposal_id": proposal_id,
        "claim_id": claim_id,
        "source_id": source_id,
        "source_title": source.get("title", ""),
        "source_book": row.get("source_book", ""),
        "category": row.get("category", ""),
        "claim_type": claim.get("claim_type", ""),
        "approved_weight_0_5": _float(row.get("approved_weight_0_5")),
        "relevant_mi5_labels": mi5,
        "uncertainty_notes": uncertainty_notes or claim.get("uncertainty_notes", "") or row.get("notes", ""),
        "criteria_highlights": highlights,
        "evidence_preview": _preview(row.get("evidence_argument", "") or claim.get("claim_text", "")),
        "notes_preview": _preview(row.get("notes", "") or criteria_row.get("notes", "")),
        "trace_summary": f"proposal={proposal_id or 'n/a'} claim={claim_id or 'n/a'} source={source_id or 'n/a'}",
    }


def _passes_filters(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters["source_id"] and item.get("source_id") != filters["source_id"]:
        return False
    if filters["category"] and filters["category"].lower() not in item.get("category", "").lower():
        return False
    if filters["topic"]:
        text = " ".join(str(item.get(key, "")) for key in ["evidence_preview", "notes_preview", "source_title", "source_book", "category", "uncertainty_notes"])
        if filters["topic"].lower() not in text.lower():
            return False
    return True


def _rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (-float(item["priority_score"]), item["study_item_id"])


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = item["study_item_id"]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _priority_category(score: float) -> str:
    if score >= 8:
        return "urgent"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _priority_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["priority_category"] for item in items)
    return {key: counts.get(key, 0) for key in ["urgent", "high", "medium", "low"]}


def _study_plan(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["Add or review approved records, then rerun study-queue."]
    plan = []
    for item in items[:5]:
        plan.append(f"{item['suggested_next_action']}: {item['trace_summary']}")
    return plan


def _trace_appendix(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "study_item_id": item["study_item_id"],
            "proposal_id": item["proposal_id"],
            "claim_id": item["claim_id"],
            "source_id": item["source_id"],
            "source_title": item["source_title"],
            "source_book": item["source_book"],
            "category": item["category"],
            "priority_score": item["priority_score"],
        }
        for item in items
    ]


def _suggest_action(reasons: list[str], claim_type: str) -> str:
    reason_text = " ".join(reasons)
    if "deferred update" in reason_text:
        return "revisit deferred update"
    if "defeater" in reason_text or claim_type in {"objection", "defeater"}:
        return "compare against opposing hypothesis"
    if "low clarity" in reason_text:
        return "clarify definitions"
    if "high salience" in reason_text:
        return "check whether emotional salience is being confused with evidential strength"
    if "uncertainty" in reason_text:
        return "reread source and split into smaller claims"
    return "inspect original claim"


def _criteria_highlights(row: dict[str, str]) -> list[str]:
    labels = []
    mapping = {
        "uncertainty_0_5": "high uncertainty",
        "defeater_strength_0_5": "high defeater strength",
        "existential_salience_0_5": "high existential salience",
        "moral_stakes_0_5": "high moral stakes",
        "emotional_salience_0_5": "high emotional salience",
    }
    for field, label in mapping.items():
        if _float(row.get(field)) >= 4:
            labels.append(label)
    clarity = _float(row.get("clarity_0_5"))
    if clarity and clarity <= 2:
        labels.append("low clarity")
    return labels


def _conflicting_mi5(row: dict[str, str], hypotheses: list[str]) -> bool:
    support = {"Likely / probable", "Highly likely", "Almost certain"}
    challenge = {"Unlikely", "Highly unlikely", "Remote chance"}
    values = {row.get(f"{hypothesis}_MI5", "") for hypothesis in hypotheses}
    return bool(values & support) and bool(values & challenge)


def _combined_text(*rows: dict[str, str]) -> str:
    return " ".join(" ".join(str(value) for value in row.values()) for row in rows)


def _claim_hypothesis_text(claim: dict[str, str]) -> str:
    return " ".join(
        claim.get(field, "")
        for field in ["related_hypotheses", "supports_hypotheses", "undermines_hypotheses", "possible_defeater_for"]
    )


def _contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def _passes_topic_text(text: str, topic: str) -> bool:
    return not topic or topic.lower() in text.lower()


def _study_item_id(source_kind: str, proposal_id: str, claim_id: str, source_id: str) -> str:
    return f"STUDY_{source_kind.upper()}_{proposal_id or claim_id or source_id or 'ITEM'}"


def _summary_lines(summary: dict[str, int]) -> list[str]:
    return [f"- {label}: {summary.get(label, 0)}" for label in ["urgent", "high", "medium", "low"]]


def _item_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = (
            f"- [{item['priority_category'].upper()} {item['priority_score']}] "
            f"{item['proposal_id'] or item['claim_id'] or item['source_id']} / {item['source_id']} - "
            f"{item['reason_for_study']}. Next: {item['suggested_next_action']}."
        )
        if item["trace_summary"]:
            line += f" Trace: {item['trace_summary']}."
        if length == "long":
            line += f" Evidence: {item['evidence_preview']} Notes: {item['notes_preview']}"
        lines.append(line)
    return lines


def _appendix_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item['study_item_id']} | {item['proposal_id']} | {item['claim_id']} | {item['source_id']} | {item['source_title']} | {item['category']} | {item['priority_score']}"
        for item in items
    ]


def _render_discord(result: dict[str, Any]) -> str:
    lines = ["Study Queue - Top Priorities", ""]
    for index, item in enumerate(result["study_items"][:10], start=1):
        lines.extend(
            [
                f"{index}. [{item['priority_category'].upper()}] {item['proposal_id'] or item['claim_id'] or item['source_id']} / {item['source_id']} - {item['evidence_preview']}",
                f"   Why: {item['reason_for_study']}.",
                f"   Next: {item['suggested_next_action']}.",
                "",
            ]
        )
    if not result["study_items"]:
        lines.append("No study candidates matched the current filters.")
    return "\n".join(lines).rstrip()


def _render_markdown_report(result: dict[str, Any]) -> str:
    return render_study_queue(result, length="long") + "\n"


def _filename_label(filters: dict[str, Any]) -> str:
    if filters.get("hypothesis"):
        return str(filters["hypothesis"])
    if filters.get("topic"):
        topic = re.sub(r"[^A-Za-z0-9]+", "_", str(filters["topic"])).strip("_")
        return f"TOPIC_{topic or 'UNKNOWN'}"
    return "GENERAL"


def _read_reflection_journal(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    stripped = "\n".join(line for line in text.splitlines() if line.strip() not in REFLECTION_TEMPLATE_MARKERS).strip()
    return stripped


def _queue_dir(config: dict[str, Any], base_dir: str | Path) -> Path:
    value = Path(config["queues"]["base_dir"])
    return value if value.is_absolute() else Path(base_dir) / value


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _index(rows: list[dict[str, str]], fields: list[str]) -> dict[tuple[str, ...], dict[str, str]]:
    return {tuple(row.get(field, "") for field in fields): row for row in rows}


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


def _error_result(message: str) -> dict[str, Any]:
    return {
        "operation": "study_queue",
        "generated_at": timestamp_iso(),
        "overall_status": "fail",
        "filters": {},
        "counts": {"candidates_total": 0, "candidates_after_min_priority": 0, "candidates_shown": 0},
        "priority_summary": {"urgent": 0, "high": 0, "medium": 0, "low": 0},
        "study_items": [],
        "unresolved_defeaters": [],
        "high_salience_items": [],
        "low_clarity_items": [],
        "deferred_items": [],
        "suggested_study_plan": [],
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "no_workbook_or_queue_data_modified": True,
    }
