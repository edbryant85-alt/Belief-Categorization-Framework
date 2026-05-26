from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.debate_summaries import HYPOTHESIS_NAMES, MI5_IMPACT
from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS, MI5_COLUMNS
from belief_dashboard.study_queue import build_study_queue
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


SUPPORT_CLASSES = {"strong_support", "moderate_support"}
CHALLENGE_CLASSES = {"strong_challenge", "moderate_challenge"}
NEUTRAL_CLASSES = {"neutral_mixed"}


def build_source_comparison(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    source_ids: list[str],
    hypothesis: str | None = None,
    topic: str | None = None,
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    comparison_config = config.get("source_comparisons", {})
    selected_sources = _dedupe([item.strip() for item in source_ids if item and item.strip()])
    if len(selected_sources) < 2:
        return _comparison_error("Supply at least two source IDs with --source-id or --sources.", selected_sources)

    hypotheses = _hypotheses(config)
    selected_hypothesis = (hypothesis or "").upper()
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _comparison_error(f"Unknown hypothesis ID: {hypothesis}", selected_sources)

    data = _load_data(config, base_dir)
    missing = [source_id for source_id in selected_sources if source_id not in data["sources"]]
    if missing:
        return _comparison_error(f"Unknown source ID(s): {', '.join(missing)}", selected_sources)

    item_limit = int(limit if limit is not None else comparison_config.get("default_limit", 25))
    filters = {
        "source_ids": selected_sources,
        "hypothesis": selected_hypothesis,
        "topic": topic or "",
        "limit": item_limit,
        "min_weight": min_weight if min_weight is not None else comparison_config.get("default_min_weight", 0),
        "exported_only": exported_only,
        "include_unexported": include_unexported,
        "length": length,
    }
    source_set = set(selected_sources)
    approved = [
        _enrich_approved(row, data, hypotheses)
        for row in data["approved"]
        if row.get("source_id") in source_set
    ]
    approved = _filter_approved(approved, filters)
    claims = [row for row in data["claims"] if row.get("source_id") in source_set and _matches_topic_for_row(row, data, topic or "")]
    criteria = [row for row in data["criteria"] if row.get("source_id") in source_set and _matches_topic_for_row(row, data, topic or "")]
    proposed = [row for row in data["proposed"] if row.get("source_id") in source_set and _matches_topic_for_row(row, data, topic or "")]
    rejected = [row for row in data["rejected"] if row.get("source_id") in source_set and _matches_topic_for_row(row, data, topic or "")]
    deferred = [row for row in data["deferred"] if row.get("source_id") in source_set and _matches_topic_for_row(row, data, topic or "")]

    source_metadata = [_source_metadata(data["sources"][source_id]) for source_id in selected_sources]
    high_level = _high_level_comparison(selected_sources, approved, claims, proposed, rejected, deferred, data)
    impact = _hypothesis_impact_comparison(selected_sources, approved, hypotheses, selected_hypothesis, item_limit)
    conflict_map = _conflict_map(approved, hypotheses, selected_hypothesis, item_limit)
    shared = _shared_themes(selected_sources, approved, claims, data)
    objections = _objections_by_source(selected_sources, approved, claims, criteria, data, item_limit)
    criteria_highlights = _criteria_highlights(criteria, data, comparison_config, item_limit)
    study_priorities = _study_priorities(config, base_dir, selected_sources, item_limit, length=length)
    debate_use = _comparison_debate_use(impact, conflict_map, shared, study_priorities)
    trace = _trace_appendix(selected_sources, approved, proposed, rejected, deferred, data)
    discord = _comparison_discord(selected_sources, conflict_map, shared, study_priorities, trace)

    return {
        "generated_at": timestamp_iso(generated_at),
        "mode": "compare_sources",
        "selected_sources": selected_sources,
        "filters": filters,
        "source_metadata": source_metadata,
        "high_level_comparison": high_level,
        "hypothesis_impact_comparison": impact,
        "conflict_map": conflict_map,
        "shared_themes": shared,
        "objections_defeaters": objections,
        "criteria_highlights": criteria_highlights,
        "study_priorities": study_priorities,
        "debate_use": debate_use,
        "discord_section": discord,
        "trace_appendix": trace,
        "warnings": [] if approved else ["No approved updates matched the selected comparison filters."],
        "errors": [],
        "overall_status": "pass",
        "no_workbook_or_queue_data_modified": True,
    }


def build_source_map(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    topic: str | None = None,
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    comparison_config = config.get("source_comparisons", {})
    selected_hypothesis = (hypothesis or "").upper()
    if not selected_hypothesis and not topic:
        return _map_error('Supply --hypothesis HYPOTHESIS_ID, --topic "topic text", or both.', selected_hypothesis, topic)
    hypotheses = _hypotheses(config)
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _map_error(f"Unknown hypothesis ID: {hypothesis}", selected_hypothesis, topic)

    item_limit = int(limit if limit is not None else comparison_config.get("default_limit", 25))
    filters = {
        "hypothesis": selected_hypothesis,
        "topic": topic or "",
        "limit": item_limit,
        "min_weight": min_weight if min_weight is not None else comparison_config.get("default_min_weight", 0),
        "exported_only": exported_only,
        "include_unexported": include_unexported,
        "length": length,
    }
    data = _load_data(config, base_dir)
    approved = [_enrich_approved(row, data, hypotheses) for row in data["approved"]]
    approved = _filter_approved(approved, filters)
    source_ids = _dedupe([row["source_id"] for row in approved])
    claims = [row for row in data["claims"] if row.get("source_id") in set(source_ids) and _matches_topic_for_row(row, data, topic or "")]
    proposed = [row for row in data["proposed"] if row.get("source_id") in set(source_ids) and _matches_topic_for_row(row, data, topic or "")]
    rejected = [row for row in data["rejected"] if row.get("source_id") in set(source_ids) and _matches_topic_for_row(row, data, topic or "")]
    deferred = [row for row in data["deferred"] if row.get("source_id") in set(source_ids) and _matches_topic_for_row(row, data, topic or "")]

    sources_affecting = _sources_affecting(source_ids, approved, claims, deferred, data)
    ranking = _source_ranking(sources_affecting, approved, selected_hypothesis)
    support, challenge, mixed = _source_groups(ranking, approved, selected_hypothesis)
    conflict_map = _conflict_map(approved, hypotheses, selected_hypothesis, item_limit)
    study_priorities = _study_priorities(config, base_dir, source_ids, item_limit, length=length)
    debate_use = _map_debate_use(ranking, support, challenge, conflict_map, study_priorities)
    trace = _trace_appendix(source_ids, approved, proposed, rejected, deferred, data)
    discord = _map_discord(selected_hypothesis, topic or "", support, challenge, study_priorities)

    return {
        "generated_at": timestamp_iso(generated_at),
        "mode": "source_map",
        "selection": {"hypothesis": selected_hypothesis, "topic": topic or ""},
        "filters": filters,
        "sources_affecting_selection": sources_affecting[:item_limit],
        "source_ranking": ranking[:item_limit],
        "support_sources": support[:item_limit],
        "challenge_sources": challenge[:item_limit],
        "mixed_sources": mixed[:item_limit],
        "conflict_map": conflict_map,
        "study_priorities": study_priorities[:item_limit],
        "debate_use": debate_use,
        "discord_section": discord,
        "trace_appendix": trace,
        "warnings": [] if approved else ["No approved updates matched the selected map filters."],
        "errors": [],
        "overall_status": "pass",
        "no_workbook_or_queue_data_modified": True,
    }


def render_source_comparison(result: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Source comparison status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return result["discord_section"]
    lines = [
        f"# Source Comparison: {' vs '.join(result['selected_sources'])}",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Filters: `{json.dumps(result['filters'], sort_keys=True)}`",
        "- Caveat: This is a read-only comparison of queue records. Apparent conflicts are heuristic, not proven logical contradictions.",
        "- No workbook or queue data was modified.",
        "",
        "## Source Metadata Table",
        *_metadata_table(result["source_metadata"]),
        "",
        "## High-Level Comparison",
        *_high_level_lines(result["high_level_comparison"]),
        "",
        "## Hypothesis Impact Comparison",
        *_impact_comparison_lines(result["hypothesis_impact_comparison"], length=length),
        "",
        "## Conflict Map",
        *_conflict_lines(result["conflict_map"], length=length),
        "",
        "## Shared Themes / Overlap",
        *_shared_lines(result["shared_themes"]),
        "",
        "## Objections / Defeaters by Source",
        *_grouped_lines(result["objections_defeaters"], length=length),
        "",
        "## Criteria Highlights",
        *_criteria_lines(result["criteria_highlights"], length=length),
        "",
        "## Study / Reflection Priorities",
        *_study_lines(result["study_priorities"], length=length),
        "",
        "## Debate Use",
        *_debate_lines(result["debate_use"]),
        "",
        "## Discord Copy Section",
        result["discord_section"],
        "",
        "## Trace Appendix",
        *_trace_lines(result["trace_appendix"], length=length),
    ]
    if result["warnings"]:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in result["warnings"]]])
    return "\n".join(lines).rstrip()


def render_source_map(result: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Source map status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return result["discord_section"]
    title = result["selection"].get("hypothesis") or f"TOPIC {result['selection'].get('topic', '')}"
    lines = [
        f"# Source Map: {title}",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Filters: `{json.dumps(result['filters'], sort_keys=True)}`",
        "- Caveat: This is a read-only summary of queue records. Apparent conflicts are heuristic, not proven logical contradictions.",
        "- No workbook or queue data was modified.",
        "",
        "## Sources Affecting This Hypothesis/Topic",
        *_sources_affecting_lines(result["sources_affecting_selection"]),
        "",
        "## Source Ranking",
        *_ranking_lines(result["source_ranking"], length=length),
        "",
        "## Support Sources",
        *_ranking_lines(result["support_sources"], length=length),
        "",
        "## Challenge Sources",
        *_ranking_lines(result["challenge_sources"], length=length),
        "",
        "## Mixed / Ambiguous Sources",
        *_ranking_lines(result["mixed_sources"], length=length),
        "",
        "## Conflict Map",
        *_conflict_lines(result["conflict_map"], length=length),
        "",
        "## Study Priorities",
        *_study_lines(result["study_priorities"], length=length),
        "",
        "## Debate Use",
        *_debate_lines(result["debate_use"]),
        "",
        "## Discord Copy Section",
        result["discord_section"],
        "",
        "## Trace Appendix",
        *_trace_lines(result["trace_appendix"], length=length),
    ]
    if result["warnings"]:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in result["warnings"]]])
    return "\n".join(lines).rstrip()


def write_source_comparison_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    if result["mode"] == "compare_sources":
        label = "_".join(result["selected_sources"])
        prefix = f"source_comparison_{label}"
        markdown = render_source_comparison(result, length="long")
    else:
        selection = result["selection"]
        label = selection.get("hypothesis") or f"TOPIC_{_slug(selection.get('topic', ''))}"
        prefix = f"source_map_{label}"
        markdown = render_source_map(result, length="long")
    markdown_path = reports_path / f"{prefix}_{stamp}.md"
    json_path = reports_path / f"{prefix}_{stamp}.json"
    markdown_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _load_data(config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    queue_dir = _queue_dir(config, base_dir)
    files = config["queues"]["files"]
    source_rows = _read_optional_csv(queue_dir / files["source_dossiers"])
    claim_rows = _read_optional_csv(queue_dir / files["extracted_claims"])
    criteria_rows = _read_optional_csv(queue_dir / files["criteria_matrix"])
    return {
        "sources": {row.get("source_id", ""): row for row in source_rows},
        "claims": claim_rows,
        "criteria": criteria_rows,
        "proposed": _read_optional_csv(queue_dir / files["proposed_updates"]),
        "approved": _read_optional_csv(queue_dir / files["approved_updates"]),
        "rejected": _read_optional_csv(queue_dir / files["rejected_updates"]),
        "deferred": _read_optional_csv(queue_dir / files["deferred_updates"]),
        "claim_index": {(row.get("claim_id", ""), row.get("source_id", "")): row for row in claim_rows},
        "criteria_index": {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria_rows},
    }


def _enrich_approved(row: dict[str, str], data: dict[str, Any], hypotheses: list[str]) -> dict[str, Any]:
    source = data["sources"].get(row.get("source_id", ""), {})
    claim = data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})
    criteria = data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})
    impacts = {}
    for hypothesis in hypotheses:
        mi5 = (row.get(f"{hypothesis}_MI5") or "").strip()
        classification, strength = MI5_IMPACT.get(mi5, ("neutral_mixed", 2))
        impacts[hypothesis] = {"mi5_label": mi5, "classification": classification, "impact_strength": strength}
    return {
        **row,
        "approved_weight_numeric": _float(row.get("approved_weight_0_5")),
        "source_title": source.get("title", ""),
        "source_type": source.get("source_type", ""),
        "claim_text": claim.get("claim_text", ""),
        "claim_type": claim.get("claim_type", ""),
        "criteria_notes": criteria.get("notes", ""),
        "criteria_scores": {field: criteria.get(field, "") for field in CRITERIA_SCORE_FIELDS if criteria.get(field, "")},
        "criteria_flags": _criteria_flags(criteria, {}),
        "hypothesis_impacts": impacts,
        "topic_text": _topic_text(row, source, claim, criteria),
    }


def _filter_approved(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if float(filters.get("min_weight", 0) or 0) and row["approved_weight_numeric"] < float(filters["min_weight"]):
            continue
        if filters.get("exported_only") and (row.get("export_status") or "").strip() != "exported":
            continue
        hypothesis = filters.get("hypothesis") or ""
        if hypothesis and not row["hypothesis_impacts"].get(hypothesis, {}).get("mi5_label"):
            continue
        topic = filters.get("topic") or ""
        if topic and topic.lower() not in row.get("topic_text", "").lower():
            continue
        result.append(row)
    return sorted(result, key=_rank_key)


def _rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    strongest = max((impact["impact_strength"] for impact in row.get("hypothesis_impacts", {}).values() if impact.get("mi5_label")), default=0)
    return (-row.get("approved_weight_numeric", 0), -strongest, _reverse_date_key(row.get("approved_date", "")), row.get("source_id", ""), row.get("proposal_id", ""))


def _reverse_date_key(value: str) -> str:
    if not value:
        return "9999-99-99"
    return "".join(str(9 - int(char)) if char.isdigit() else char for char in value)


def _high_level_comparison(
    source_ids: list[str],
    approved: list[dict[str, Any]],
    claims: list[dict[str, str]],
    proposed: list[dict[str, str]],
    rejected: list[dict[str, str]],
    deferred: list[dict[str, str]],
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for source_id in source_ids:
        approved_rows = [row for row in approved if row.get("source_id") == source_id]
        categories = Counter(row.get("category", "") for row in approved_rows if row.get("category"))
        hyp_counts = Counter()
        for row in approved_rows:
            for hypothesis, impact in row["hypothesis_impacts"].items():
                if impact.get("mi5_label"):
                    hyp_counts[hypothesis] += 1
        rows.append(
            {
                "source_id": source_id,
                "title": data["sources"].get(source_id, {}).get("title", ""),
                "approved_rows": len(approved_rows),
                "claims": sum(1 for row in claims if row.get("source_id") == source_id),
                "proposed": sum(1 for row in proposed if row.get("source_id") == source_id),
                "rejected": sum(1 for row in rejected if row.get("source_id") == source_id),
                "deferred": sum(1 for row in deferred if row.get("source_id") == source_id),
                "top_categories": categories.most_common(5),
                "top_hypotheses": hyp_counts.most_common(5),
            }
        )
    return rows


def _hypothesis_impact_comparison(
    source_ids: list[str],
    approved: list[dict[str, Any]],
    hypotheses: list[str],
    selected_hypothesis: str,
    limit: int,
) -> list[dict[str, Any]]:
    result = []
    for hypothesis in ([selected_hypothesis] if selected_hypothesis else hypotheses):
        source_summaries = []
        for source_id in source_ids:
            items = [row for row in approved if row.get("source_id") == source_id and row["hypothesis_impacts"].get(hypothesis, {}).get("mi5_label")]
            support = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] in SUPPORT_CLASSES]
            challenge = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] in CHALLENGE_CLASSES]
            neutral = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] in NEUTRAL_CLASSES]
            source_summaries.append(
                {
                    "source_id": source_id,
                    "approved_rows": len(items),
                    "support": len(support),
                    "challenge": len(challenge),
                    "neutral_mixed": len(neutral),
                    "representative_weight": round(sum(row["approved_weight_numeric"] for row in items) / len(items), 2) if items else 0,
                    "strongest_support": [_impact_item(row, hypothesis) for row in support[:limit]][:1],
                    "strongest_challenge": [_impact_item(row, hypothesis) for row in challenge[:limit]][:1],
                }
            )
        if any(item["approved_rows"] for item in source_summaries):
            result.append({"hypothesis_id": hypothesis, "hypothesis_name": HYPOTHESIS_NAMES.get(hypothesis, hypothesis), "sources": source_summaries})
    return result


def _conflict_map(approved: list[dict[str, Any]], hypotheses: list[str], selected_hypothesis: str, limit: int) -> list[dict[str, Any]]:
    conflicts = []
    for hypothesis in ([selected_hypothesis] if selected_hypothesis else hypotheses):
        support = [row for row in approved if row["hypothesis_impacts"].get(hypothesis, {}).get("classification") in SUPPORT_CLASSES]
        challenge = [row for row in approved if row["hypothesis_impacts"].get(hypothesis, {}).get("classification") in CHALLENGE_CLASSES]
        for support_row in support:
            for challenge_row in challenge:
                if support_row.get("source_id") == challenge_row.get("source_id"):
                    continue
                conflicts.append(
                    {
                        "hypothesis_id": hypothesis,
                        "description": "Apparent conflict: one source supports this hypothesis while another challenges it.",
                        "strength": "stronger" if support_row["approved_weight_numeric"] >= 3 and challenge_row["approved_weight_numeric"] >= 3 else "possible",
                        "support_item": _impact_item(support_row, hypothesis),
                        "challenge_item": _impact_item(challenge_row, hypothesis),
                    }
                )
    conflicts.sort(key=lambda item: (-min(item["support_item"]["weight"], item["challenge_item"]["weight"]), item["hypothesis_id"], item["support_item"]["source_id"]))
    return conflicts[:limit]


def _shared_themes(source_ids: list[str], approved: list[dict[str, Any]], claims: list[dict[str, str]], data: dict[str, Any]) -> dict[str, Any]:
    by_source_hypotheses: dict[str, set[str]] = {source_id: set() for source_id in source_ids}
    by_source_categories: dict[str, set[str]] = {source_id: set() for source_id in source_ids}
    by_source_claim_types: dict[str, set[str]] = {source_id: set() for source_id in source_ids}
    for row in approved:
        source_id = row.get("source_id", "")
        by_source_categories.setdefault(source_id, set()).add(row.get("category", ""))
        for hypothesis, impact in row["hypothesis_impacts"].items():
            if impact.get("mi5_label"):
                by_source_hypotheses.setdefault(source_id, set()).add(hypothesis)
    for claim in claims:
        by_source_claim_types.setdefault(claim.get("source_id", ""), set()).add(claim.get("claim_type", ""))
    return {
        "shared_hypotheses": sorted(_intersection([values - {""} for values in by_source_hypotheses.values()])),
        "shared_categories": sorted(_intersection([values - {""} for values in by_source_categories.values()])),
        "shared_claim_types": sorted(_intersection([values - {""} for values in by_source_claim_types.values()])),
        "note": "Topic overlap is simple category/claim-type/hypothesis overlap, not semantic search.",
    }


def _objections_by_source(
    source_ids: list[str],
    approved: list[dict[str, Any]],
    claims: list[dict[str, str]],
    criteria: list[dict[str, str]],
    data: dict[str, Any],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}
    result: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in source_ids}
    claim_ids = set()
    for claim in claims:
        text = " ".join([claim.get("claim_type", ""), claim.get("claim_text", ""), claim.get("uncertainty_notes", "")]).lower()
        criteria_row = criteria_index.get((claim.get("claim_id", ""), claim.get("source_id", "")), {})
        if any(term in text for term in ["objection", "defeater", "counterargument", "challenge"]) or _float(criteria_row.get("defeater_strength_0_5")) >= 4:
            claim_ids.add((claim.get("claim_id", ""), claim.get("source_id", "")))
            result.setdefault(claim.get("source_id", ""), []).append(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "source_id": claim.get("source_id", ""),
                    "claim_type": claim.get("claim_type", ""),
                    "reason": "objection/defeater claim or high defeater criteria",
                    "preview": _preview(claim.get("claim_text", "")),
                }
            )
    for row in approved:
        key = (row.get("claim_id", ""), row.get("source_id", ""))
        if key in claim_ids:
            continue
        text = " ".join([row.get("category", ""), row.get("notes", ""), row.get("evidence_argument", "")]).lower()
        if any(term in text for term in ["objection", "defeater", "counterargument", "challenge"]) or "high defeater strength" in row.get("criteria_flags", []):
            result.setdefault(row.get("source_id", ""), []).append(
                {
                    "proposal_id": row.get("proposal_id", ""),
                    "claim_id": row.get("claim_id", ""),
                    "source_id": row.get("source_id", ""),
                    "reason": "approved row references objection/defeater or high defeater criteria",
                    "preview": _preview(row.get("evidence_argument", "")),
                }
            )
    return {source_id: items[:limit] for source_id, items in result.items()}


def _criteria_highlights(rows: list[dict[str, str]], data: dict[str, Any], config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    highlights = []
    for row in rows:
        flags = _criteria_flags(row, config)
        if not flags:
            continue
        claim = data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})
        highlights.append(
            {
                "source_id": row.get("source_id", ""),
                "claim_id": row.get("claim_id", ""),
                "claim_preview": _preview(claim.get("claim_text", "")),
                "highlights": flags,
                "scores": {field: row.get(field, "") for field in CRITERIA_SCORE_FIELDS if row.get(field, "")},
                "salience_note": "Salience is separate from evidential strength.",
            }
        )
    return highlights[:limit]


def _study_priorities(config: dict[str, Any], base_dir: str | Path, source_ids: list[str], limit: int, *, length: str) -> list[dict[str, Any]]:
    items = []
    for source_id in source_ids:
        study = build_study_queue(config, base_dir, source_id=source_id, limit=limit, include_deferred=True, include_reflections=False, length=length)
        if study.get("overall_status") == "pass":
            items.extend(study.get("study_items", []))
    items.sort(key=lambda item: (-float(item.get("priority_score", 0)), item.get("source_id", ""), item.get("proposal_id", ""), item.get("claim_id", "")))
    return items[:limit]


def _sources_affecting(source_ids: list[str], approved: list[dict[str, Any]], claims: list[dict[str, str]], deferred: list[dict[str, str]], data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source_id in source_ids:
        source = data["sources"].get(source_id, {})
        approved_rows = [row for row in approved if row.get("source_id") == source_id]
        rows.append(
            {
                "source_id": source_id,
                "title": source.get("title", ""),
                "source_type": source.get("source_type", ""),
                "author_or_speaker": source.get("author_or_speaker", ""),
                "approved_rows": len(approved_rows),
                "claims": sum(1 for row in claims if row.get("source_id") == source_id),
                "unresolved_deferred_items": sum(1 for row in deferred if row.get("source_id") == source_id),
                "strongest_weight": max((row["approved_weight_numeric"] for row in approved_rows), default=0),
            }
        )
    return rows


def _source_ranking(sources: list[dict[str, Any]], approved: list[dict[str, Any]], hypothesis: str) -> list[dict[str, Any]]:
    ranked = []
    for source in sources:
        source_rows = [row for row in approved if row.get("source_id") == source["source_id"]]
        support = [row for row in source_rows if _classification_for(row, hypothesis) in SUPPORT_CLASSES]
        challenge = [row for row in source_rows if _classification_for(row, hypothesis) in CHALLENGE_CLASSES]
        neutral = [row for row in source_rows if _classification_for(row, hypothesis) in NEUTRAL_CLASSES]
        uncertainty = sum(1 for row in source_rows if "high uncertainty" in row.get("criteria_flags", []))
        defeater = sum(1 for row in source_rows if "high defeater strength" in row.get("criteria_flags", []))
        ranked.append(
            {
                **source,
                "support_rows": len(support),
                "challenge_rows": len(challenge),
                "neutral_mixed_rows": len(neutral),
                "high_uncertainty_rows": uncertainty,
                "high_defeater_rows": defeater,
                "strongest_support": [_impact_item(row, hypothesis) for row in support[:1]],
                "strongest_challenge": [_impact_item(row, hypothesis) for row in challenge[:1]],
                "ranking_score": len(source_rows) * 10 + source["strongest_weight"] + len(support) + len(challenge) + uncertainty + defeater,
            }
        )
    ranked.sort(key=lambda item: (-item["approved_rows"], -item["strongest_weight"], -(item["support_rows"] + item["challenge_rows"]), -item["high_uncertainty_rows"], -item["high_defeater_rows"], item["source_id"]))
    return ranked


def _source_groups(ranking: list[dict[str, Any]], approved: list[dict[str, Any]], hypothesis: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    support = []
    challenge = []
    mixed = []
    for row in ranking:
        if row["support_rows"] and row["challenge_rows"]:
            mixed.append(row)
        elif row["support_rows"] > row["challenge_rows"]:
            support.append(row)
        elif row["challenge_rows"] > row["support_rows"]:
            challenge.append(row)
        else:
            mixed.append(row)
    return support, challenge, mixed


def _comparison_debate_use(impact: list[dict[str, Any]], conflicts: list[dict[str, Any]], shared: dict[str, Any], study: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "strongest_agreement": f"Shared hypotheses: {', '.join(shared.get('shared_hypotheses', [])) or 'none recorded'}.",
        "strongest_disagreement": conflicts[0]["description"] if conflicts else "No apparent support/challenge conflict found.",
        "most_important_unresolved_question": study[0].get("reason_for_study", "No source-specific study priority found.") if study else "No source-specific study priority found.",
        "best_follow_up_question": study[0].get("suggested_next_action", "Compare the strongest approved rows and reread source contexts.") if study else "Compare the strongest approved rows and reread source contexts.",
    }


def _map_debate_use(ranking: list[dict[str, Any]], support: list[dict[str, Any]], challenge: list[dict[str, Any]], conflicts: list[dict[str, Any]], study: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "best_source_to_cite_first": _source_label(support[0]) if support else _source_label(ranking[0]) if ranking else "None",
        "strongest_counter_source": _source_label(challenge[0]) if challenge else "None",
        "most_important_unresolved_comparison": conflicts[0]["description"] if conflicts else "No apparent conflict found.",
        "best_question_to_ask_next": study[0].get("suggested_next_action", "Inspect source ranking and trace appendix.") if study else "Inspect source ranking and trace appendix.",
    }


def _comparison_discord(source_ids: list[str], conflicts: list[dict[str, Any]], shared: dict[str, Any], study: list[dict[str, Any]], trace: list[dict[str, Any]]) -> str:
    lines = [f"Source Comparison - {' vs '.join(source_ids)}", "", "Agreement:", f"- Both touch {', '.join(shared.get('shared_hypotheses', [])) or 'no shared hypothesis in matching rows'}.", "", "Tension:"]
    if conflicts:
        item = conflicts[0]
        lines.append(f"- {item['support_item']['source_id']} supports {item['hypothesis_id']}: {item['support_item']['proposal_id']}, Weight {item['support_item']['weight']}, MI5 {item['support_item']['mi5_label']}.")
        lines.append(f"- {item['challenge_item']['source_id']} challenges {item['hypothesis_id']}: {item['challenge_item']['proposal_id']}, Weight {item['challenge_item']['weight']}, MI5 {item['challenge_item']['mi5_label']}.")
    else:
        lines.append("- No apparent support/challenge conflict found.")
    lines.extend(["", "Study priority:"])
    lines.append(f"- {study[0]['reason_for_study']}: {study[0]['suggested_next_action']}." if study else "- None")
    lines.extend(["", "Trace:"])
    by_source = defaultdict(list)
    for row in trace:
        if row.get("proposal_id"):
            by_source[row["source_id"]].append(f"{row['proposal_id']}, {row['claim_id']}")
    for source_id in source_ids:
        lines.append(f"{source_id}: {'; '.join(by_source[source_id]) or 'No proposals'}")
    return "\n".join(lines).rstrip()


def _map_discord(hypothesis: str, topic: str, support: list[dict[str, Any]], challenge: list[dict[str, Any]], study: list[dict[str, Any]]) -> str:
    title = hypothesis or f"Topic: {topic}"
    lines = [f"Source Map - {title}", "", "Top support source:"]
    lines.append(f"- {_source_label(support[0])}, {support[0]['approved_rows']} approved rows." if support else "- None")
    lines.extend(["", "Top challenge source:"])
    lines.append(f"- {_source_label(challenge[0])}, {challenge[0]['approved_rows']} approved rows." if challenge else "- None")
    lines.extend(["", "Most important unresolved issue:"])
    lines.append(f"- {study[0].get('proposal_id') or study[0].get('claim_id')}, {study[0].get('reason_for_study')}." if study else "- None")
    return "\n".join(lines).rstrip()


def _trace_appendix(source_ids: list[str], approved: list[dict[str, Any]], proposed: list[dict[str, str]], rejected: list[dict[str, str]], deferred: list[dict[str, str]], data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    source_set = set(source_ids)
    for status, items in [("approved", approved), ("proposed", proposed), ("rejected", rejected), ("deferred", deferred)]:
        for row in items:
            if row.get("source_id") not in source_set:
                continue
            source = data["sources"].get(row.get("source_id", ""), {})
            rows.append(
                {
                    "source_id": row.get("source_id", ""),
                    "source_title": source.get("title", ""),
                    "claim_id": row.get("claim_id", ""),
                    "proposal_id": row.get("proposal_id", ""),
                    "review_status": status,
                    "category": row.get("category", ""),
                    "weight": row.get("approved_weight_0_5", "") or row.get("suggested_weight_0_5", ""),
                    "source_book": row.get("source_book", ""),
                    "mi5_labels": {column: row.get(column, "") for column in MI5_COLUMNS if row.get(column, "")},
                }
            )
    return sorted(rows, key=lambda item: (item["source_id"], item["proposal_id"], item["review_status"]))


def _impact_item(row: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    impact = row["hypothesis_impacts"].get(hypothesis, {"mi5_label": "", "classification": "neutral_mixed", "impact_strength": 0})
    return {
        "source_id": row.get("source_id", ""),
        "source_title": row.get("source_title", ""),
        "proposal_id": row.get("proposal_id", ""),
        "claim_id": row.get("claim_id", ""),
        "category": row.get("category", ""),
        "weight": row.get("approved_weight_numeric", 0),
        "mi5_label": impact.get("mi5_label", ""),
        "classification": impact.get("classification", ""),
        "evidence_preview": _preview(row.get("evidence_argument", "")),
    }


def _classification_for(row: dict[str, Any], hypothesis: str) -> str:
    if hypothesis:
        return row["hypothesis_impacts"].get(hypothesis, {}).get("classification", "neutral_mixed")
    labels = [impact["classification"] for impact in row["hypothesis_impacts"].values() if impact.get("mi5_label")]
    if any(label in SUPPORT_CLASSES for label in labels):
        return "moderate_support"
    if any(label in CHALLENGE_CLASSES for label in labels):
        return "moderate_challenge"
    return "neutral_mixed"


def _criteria_flags(row: dict[str, str], config: dict[str, Any]) -> list[str]:
    high_salience = float(config.get("high_salience_threshold", 4) or 4)
    high_defeater = float(config.get("high_defeater_threshold", 4) or 4)
    high_uncertainty = float(config.get("high_uncertainty_threshold", 4) or 4)
    labels = []
    mapping = {
        "relevance_0_5": (4, "high relevance"),
        "reliability_0_5": (4, "high reliability"),
        "argument_strength_0_5": (4, "high argument strength"),
        "explanatory_power_0_5": (4, "high explanatory power"),
        "uncertainty_0_5": (high_uncertainty, "high uncertainty"),
        "defeater_strength_0_5": (high_defeater, "high defeater strength"),
        "existential_salience_0_5": (high_salience, "high existential salience"),
        "moral_stakes_0_5": (high_salience, "high moral stakes"),
        "emotional_salience_0_5": (high_salience, "high emotional salience"),
    }
    for field, (threshold, label) in mapping.items():
        if _float(row.get(field)) >= threshold:
            labels.append(label)
    if _float(row.get("clarity_0_5")) and _float(row.get("clarity_0_5")) <= 2:
        labels.append("low clarity")
    return labels


def _matches_topic_for_row(row: dict[str, str], data: dict[str, Any], topic: str) -> bool:
    if not topic:
        return True
    source = data["sources"].get(row.get("source_id", ""), {})
    claim = data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})
    criteria = data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})
    return topic.lower() in _topic_text(row, source, claim, criteria).lower()


def _topic_text(row: dict[str, str], source: dict[str, str], claim: dict[str, str], criteria: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("evidence_argument", ""),
            row.get("category", ""),
            row.get("source_book", ""),
            row.get("notes", ""),
            source.get("title", ""),
            source.get("short_summary", ""),
            claim.get("claim_text", ""),
            claim.get("source_context", ""),
            criteria.get("notes", ""),
        ]
    )


def _source_metadata(source: dict[str, str]) -> dict[str, str]:
    return {
        "source_id": source.get("source_id", ""),
        "title": source.get("title", ""),
        "source_type": source.get("source_type", ""),
        "author_or_speaker": source.get("author_or_speaker", ""),
        "date_added": source.get("date_added", ""),
        "relevant_hypotheses": source.get("relevant_hypotheses", ""),
        "processing_status": source.get("processing_status", ""),
    }


def _metadata_table(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {row['source_id']} | {row['title']} | {row['source_type']} | {row['author_or_speaker']} | {row['date_added']} | {row['relevant_hypotheses']} | {row['processing_status']}"
        for row in rows
    ]


def _high_level_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {row['source_id']}: approved={row['approved_rows']} claims={row['claims']} proposed={row['proposed']} rejected={row['rejected']} deferred={row['deferred']} categories={row['top_categories']} hypotheses={row['top_hypotheses']}"
        for row in rows
    ]


def _impact_comparison_lines(rows: list[dict[str, Any]], *, length: str) -> list[str]:
    if not rows:
        return ["- None"]
    lines = []
    for summary in rows:
        lines.append(f"- {summary['hypothesis_id']} - {summary['hypothesis_name']}")
        for source in summary["sources"]:
            lines.append(f"  - {source['source_id']}: support={source['support']} challenge={source['challenge']} mixed={source['neutral_mixed']} avg/representative weight={source['representative_weight']}")
            if length == "long":
                for item in source["strongest_support"] + source["strongest_challenge"]:
                    lines.append(f"    - {item['proposal_id']} / {item['claim_id']} {item['classification']} Weight {item['weight']} MI5 {item['mi5_label']} - {item['evidence_preview']}")
    return lines


def _conflict_lines(conflicts: list[dict[str, Any]], *, length: str) -> list[str]:
    if not conflicts:
        return ["- None"]
    lines = []
    for item in conflicts:
        support = item["support_item"]
        challenge = item["challenge_item"]
        line = f"- Potential tension on {item['hypothesis_id']} ({item['strength']}): {support['source_id']} {support['proposal_id']} {support['mi5_label']} vs {challenge['source_id']} {challenge['proposal_id']} {challenge['mi5_label']}"
        if length == "long":
            line += f" | Support: {support['evidence_preview']} | Challenge: {challenge['evidence_preview']}"
        lines.append(line)
    return lines


def _shared_lines(shared: dict[str, Any]) -> list[str]:
    return [
        f"- Shared hypotheses: {', '.join(shared.get('shared_hypotheses', [])) or 'None'}",
        f"- Shared categories: {', '.join(shared.get('shared_categories', [])) or 'None'}",
        f"- Shared claim types: {', '.join(shared.get('shared_claim_types', [])) or 'None'}",
        f"- Note: {shared.get('note', '')}",
    ]


def _grouped_lines(grouped: dict[str, list[dict[str, Any]]], *, length: str) -> list[str]:
    lines = []
    for source_id, items in grouped.items():
        lines.append(f"- {source_id}:")
        if not items:
            lines.append("  - None")
        for item in items:
            line = f"  - {item.get('proposal_id') or item.get('claim_id')} - {item.get('reason')}"
            if length == "long":
                line += f" - {item.get('preview', '')}"
            lines.append(line)
    return lines or ["- None"]


def _criteria_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = ["- Salience is listed separately from evidential strength."]
    for item in items:
        line = f"- {item['source_id']} / {item['claim_id']}: {', '.join(item['highlights'])}"
        if length == "long":
            line += f" scores={item['scores']} claim={item['claim_preview']}"
        lines.append(line)
    return lines


def _study_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = f"- [{item.get('priority_category', '').upper()} {item.get('priority_score')}] {item.get('source_id')} {item.get('proposal_id') or item.get('claim_id')} - {item.get('reason_for_study')}. Next: {item.get('suggested_next_action')}."
        if length == "long":
            line += f" Trace: {item.get('trace_summary')} Evidence: {item.get('evidence_preview')}"
        lines.append(line)
    return lines


def _debate_lines(debate_use: dict[str, str]) -> list[str]:
    return [f"- {key.replace('_', ' ').title()}: {value}" for key, value in debate_use.items()]


def _sources_affecting_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {row['source_id']} | {row['title']} | {row['source_type']} | {row['author_or_speaker']} | approved={row['approved_rows']} claims={row['claims']} unresolved/deferred={row['unresolved_deferred_items']}"
        for row in rows
    ]


def _ranking_lines(rows: list[dict[str, Any]], *, length: str) -> list[str]:
    if not rows:
        return ["- None"]
    lines = []
    for row in rows:
        line = f"- {row['source_id']} {row['title']}: approved={row['approved_rows']} strongest_weight={row['strongest_weight']} support={row['support_rows']} challenge={row['challenge_rows']} mixed={row['neutral_mixed_rows']}"
        if length == "long":
            line += f" uncertainty={row['high_uncertainty_rows']} defeaters={row['high_defeater_rows']}"
        lines.append(line)
    return lines


def _trace_lines(rows: list[dict[str, Any]], *, length: str) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {row['source_id']} | {row['claim_id']} | {row['proposal_id']} | {row['review_status']} | {row['category']} | {row['weight']} | {row['mi5_labels']} | {row['source_book'] or row['source_title']}"
        for row in rows
    ]


def _queue_dir(config: dict[str, Any], base_dir: str | Path) -> Path:
    value = Path(config["queues"]["base_dir"])
    return value if value.is_absolute() else Path(base_dir) / value


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _hypotheses(config: dict[str, Any]) -> list[str]:
    return [item.upper() for item in config["workbook"].get("hypotheses", HYPOTHESIS_NAMES)]


def _intersection(sets: list[set[str]]) -> set[str]:
    if not sets:
        return set()
    result = sets[0]
    for values in sets[1:]:
        result = result & values
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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


def _source_label(row: dict[str, Any]) -> str:
    return f"{row.get('source_id', '')}, {row.get('title', '')}".strip(", ")


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_") or "UNKNOWN"


def _comparison_error(message: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "generated_at": timestamp_iso(),
        "mode": "compare_sources",
        "selected_sources": source_ids,
        "filters": {},
        "source_metadata": [],
        "high_level_comparison": [],
        "hypothesis_impact_comparison": [],
        "conflict_map": [],
        "shared_themes": {},
        "objections_defeaters": {},
        "criteria_highlights": [],
        "study_priorities": [],
        "debate_use": {},
        "discord_section": "",
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "overall_status": "fail",
        "no_workbook_or_queue_data_modified": True,
    }


def _map_error(message: str, hypothesis: str, topic: str | None) -> dict[str, Any]:
    return {
        "generated_at": timestamp_iso(),
        "mode": "source_map",
        "selection": {"hypothesis": hypothesis, "topic": topic or ""},
        "filters": {},
        "sources_affecting_selection": [],
        "source_ranking": [],
        "support_sources": [],
        "challenge_sources": [],
        "mixed_sources": [],
        "conflict_map": [],
        "study_priorities": [],
        "debate_use": {},
        "discord_section": "",
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "overall_status": "fail",
        "no_workbook_or_queue_data_modified": True,
    }
