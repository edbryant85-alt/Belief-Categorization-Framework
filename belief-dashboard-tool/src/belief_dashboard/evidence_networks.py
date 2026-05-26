from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.debate_summaries import HYPOTHESIS_NAMES
from belief_dashboard.source_comparisons import (
    CHALLENGE_CLASSES,
    SUPPORT_CLASSES,
    _classification_for,
    _criteria_flags,
    _dedupe,
    _enrich_approved,
    _filter_approved,
    _float,
    _hypotheses,
    _impact_item,
    _load_data,
    _matches_topic_for_row,
    _preview,
    _rank_key,
)
from belief_dashboard.study_queue import build_study_queue
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


CLUSTER_TYPES = {"all", "hypotheses", "categories", "defeaters", "conflicts", "salience", "uncertainty"}


def build_evidence_clusters(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    topic: str | None = None,
    category: str | None = None,
    source_id: str | None = None,
    cluster_type: str = "all",
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    network_config = config.get("evidence_networks", {})
    selected_hypothesis = (hypothesis or "").upper()
    hypotheses = _hypotheses(config)
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _clusters_error(f"Unknown hypothesis ID: {hypothesis}", cluster_type)
    selected_cluster_type = (cluster_type or "all").lower()
    if selected_cluster_type not in CLUSTER_TYPES:
        return _clusters_error(f"Unknown cluster type: {cluster_type}", selected_cluster_type)

    item_limit = int(limit if limit is not None else network_config.get("default_limit", 25))
    filters = {
        "hypothesis": selected_hypothesis,
        "topic": topic or "",
        "category": category or "",
        "source_id": source_id or "",
        "cluster_type": selected_cluster_type,
        "limit": item_limit,
        "min_weight": min_weight if min_weight is not None else network_config.get("default_min_weight", 0),
        "exported_only": exported_only,
        "include_unexported": include_unexported,
        "length": length,
    }
    data = _load_data(config, base_dir)
    approved = [_enrich_approved(row, data, hypotheses) for row in data["approved"]]
    approved = _apply_network_filters(approved, filters)
    criteria = [
        row for row in data["criteria"]
        if _row_in_scope(row, data, filters)
    ]
    deferred = [row for row in data["deferred"] if _row_in_scope(row, data, filters)]
    claims = [row for row in data["claims"] if _row_in_scope(row, data, filters)]

    hypothesis_clusters = _hypothesis_clusters(approved, hypotheses, selected_hypothesis, item_limit)
    category_clusters = _category_clusters(approved, data, item_limit)
    defeater_clusters = _defeater_clusters(approved, claims, criteria, data, hypotheses, item_limit)
    conflict_clusters = _conflict_clusters(approved, hypotheses, selected_hypothesis, item_limit)
    salience_clusters = _salience_clusters(approved, criteria, data, network_config, item_limit)
    uncertainty_clusters = _uncertainty_clusters(approved, claims, criteria, deferred, data, network_config, item_limit)
    study_priorities = _cluster_study_priorities(
        hypothesis_clusters,
        category_clusters,
        defeater_clusters,
        conflict_clusters,
        salience_clusters,
        uncertainty_clusters,
        limit=item_limit,
    )
    trace = _cluster_trace(
        hypothesis_clusters,
        category_clusters,
        defeater_clusters,
        conflict_clusters,
        salience_clusters,
        uncertainty_clusters,
        cluster_type=selected_cluster_type,
    )
    result = {
        "generated_at": timestamp_iso(generated_at),
        "mode": "evidence_clusters",
        "filters": filters,
        "cluster_type": selected_cluster_type,
        "cluster_summary": _cluster_summary(
            approved,
            hypothesis_clusters,
            category_clusters,
            defeater_clusters,
            conflict_clusters,
            salience_clusters,
            uncertainty_clusters,
        ),
        "hypothesis_clusters": hypothesis_clusters if selected_cluster_type in {"all", "hypotheses"} else [],
        "category_clusters": category_clusters if selected_cluster_type in {"all", "categories"} else [],
        "defeater_clusters": defeater_clusters if selected_cluster_type in {"all", "defeaters"} else [],
        "conflict_clusters": conflict_clusters if selected_cluster_type in {"all", "conflicts"} else [],
        "salience_clusters": salience_clusters if selected_cluster_type in {"all", "salience"} else [],
        "uncertainty_clusters": uncertainty_clusters if selected_cluster_type in {"all", "uncertainty"} else [],
        "study_priorities": study_priorities,
        "discord_section": "",
        "trace_appendix": trace,
        "warnings": [] if approved else ["No approved updates matched the selected cluster filters."],
        "errors": [],
        "overall_status": "pass",
        "no_workbook_or_queue_data_modified": True,
    }
    result["discord_section"] = _clusters_discord(result)
    return result


def build_source_network(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    topic: str | None = None,
    source_id: str | None = None,
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    network_config = config.get("evidence_networks", {})
    selected_hypothesis = (hypothesis or "").upper()
    hypotheses = _hypotheses(config)
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _network_error(f"Unknown hypothesis ID: {hypothesis}")

    item_limit = int(limit if limit is not None else network_config.get("default_limit", 25))
    filters = {
        "hypothesis": selected_hypothesis,
        "topic": topic or "",
        "source_id": source_id or "",
        "limit": item_limit,
        "min_weight": min_weight if min_weight is not None else network_config.get("default_min_weight", 0),
        "exported_only": exported_only,
        "include_unexported": include_unexported,
        "length": length,
    }
    data = _load_data(config, base_dir)
    approved = [_enrich_approved(row, data, hypotheses) for row in data["approved"]]
    approved = _apply_network_filters(approved, filters)
    source_ids = _dedupe([row.get("source_id", "") for row in approved])
    criteria = [row for row in data["criteria"] if row.get("source_id") in set(source_ids) and _row_in_scope(row, data, filters)]
    claims = [row for row in data["claims"] if row.get("source_id") in set(source_ids) and _row_in_scope(row, data, filters)]

    centrality = _source_centrality(source_ids, approved, criteria, data, network_config, item_limit)
    hypothesis_map = _source_to_hypothesis_map(source_ids, approved, hypotheses, selected_hypothesis)
    category_map = _source_to_category_map(source_ids, approved)
    shared_links = _shared_hypothesis_links(source_ids, approved, hypotheses, selected_hypothesis)
    conflicts = _source_conflicts(approved, hypotheses, selected_hypothesis, item_limit)
    priorities = _source_study_priorities(config, base_dir, source_ids, approved, criteria, item_limit, length=length)
    trace = _source_network_trace(source_ids, approved, claims, category_map, hypothesis_map)
    result = {
        "generated_at": timestamp_iso(generated_at),
        "mode": "source_network",
        "filters": filters,
        "source_centrality_summary": centrality,
        "source_to_hypothesis_map": hypothesis_map,
        "source_to_category_map": category_map,
        "shared_hypothesis_links": shared_links,
        "apparent_source_conflicts": conflicts,
        "source_study_priorities": priorities,
        "discord_section": "",
        "trace_appendix": trace,
        "warnings": [] if approved else ["No approved updates matched the selected source-network filters."],
        "errors": [],
        "overall_status": "pass",
        "no_workbook_or_queue_data_modified": True,
    }
    result["discord_section"] = _network_discord(result)
    return result


def render_evidence_clusters(result: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Evidence clusters status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return result["discord_section"]
    lines = [
        "# Evidence Clusters",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Filters: `{json.dumps(result['filters'], sort_keys=True)}`",
        f"- Cluster type: `{result['cluster_type']}`",
        f"- Total records considered: `{result['cluster_summary']['records_considered']}`",
        "- Caveat: This is a read-only clustering of queue records. Apparent tensions are heuristic, not logical contradictions.",
        "- No workbook or queue data was modified.",
        "",
        "## Cluster Summary",
        *_summary_lines(result["cluster_summary"]),
        "",
        "## Hypothesis Clusters",
        *_cluster_lines(result["hypothesis_clusters"], length=length),
        "",
        "## Category Clusters",
        *_cluster_lines(result["category_clusters"], length=length),
        "",
        "## Defeater / Objection Clusters",
        *_cluster_lines(result["defeater_clusters"], length=length),
        "",
        "## Conflict Clusters",
        *_cluster_lines(result["conflict_clusters"], length=length),
        "",
        "## Salience Clusters",
        "- Salience is separate from evidential weight.",
        *_cluster_lines(result["salience_clusters"], length=length),
        "",
        "## Uncertainty / Low-Clarity Clusters",
        *_cluster_lines(result["uncertainty_clusters"], length=length),
        "",
        "## Study Priorities",
        *_priority_lines(result["study_priorities"]),
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


def render_source_network(result: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if result["overall_status"] == "fail":
        return "\n".join(["Source network status: fail", *[f"- {error}" for error in result["errors"]]])
    if style == "discord":
        return result["discord_section"]
    lines = [
        "# Source Network",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Filters: `{json.dumps(result['filters'], sort_keys=True)}`",
        f"- Total sources considered: `{len(result['source_centrality_summary'])}`",
        "- Caveat: This is a read-only network-style summary of queue records. Apparent source conflicts are heuristic.",
        "- No workbook or queue data was modified.",
        "",
        "## Source Centrality Summary",
        *_centrality_lines(result["source_centrality_summary"], length=length),
        "",
        "## Source-to-Hypothesis Map",
        *_hypothesis_map_lines(result["source_to_hypothesis_map"]),
        "",
        "## Source-to-Category Map",
        *_category_map_lines(result["source_to_category_map"]),
        "",
        "## Shared Hypothesis Links",
        *_shared_link_lines(result["shared_hypothesis_links"]),
        "",
        "## Apparent Source Conflicts",
        *_source_conflict_lines(result["apparent_source_conflicts"], length=length),
        "",
        "## Source Study Priorities",
        *_source_priority_lines(result["source_study_priorities"]),
        "",
        "## Discord Copy Section",
        result["discord_section"],
        "",
        "## Trace Appendix",
        *_source_trace_lines(result["trace_appendix"], length=length),
    ]
    if result["warnings"]:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in result["warnings"]]])
    return "\n".join(lines).rstrip()


def write_evidence_network_reports(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    if result["mode"] == "evidence_clusters":
        label = result["filters"].get("hypothesis") or _cluster_label(result["filters"])
        prefix = f"evidence_clusters_{label}"
        markdown = render_evidence_clusters(result, length="long")
    else:
        label = result["filters"].get("hypothesis") or _cluster_label(result["filters"])
        prefix = f"source_network_{label}"
        markdown = render_source_network(result, length="long")
    markdown_path = reports_path / f"{prefix}_{stamp}.md"
    json_path = reports_path / f"{prefix}_{stamp}.json"
    markdown_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _apply_network_filters(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    base = _filter_approved(rows, filters)
    result = []
    for row in base:
        if filters.get("source_id") and row.get("source_id") != filters["source_id"]:
            continue
        if filters.get("category") and filters["category"].lower() not in row.get("category", "").lower():
            continue
        result.append(row)
    return sorted(result, key=_rank_key)


def _row_in_scope(row: dict[str, str], data: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("source_id") and row.get("source_id") != filters["source_id"]:
        return False
    if filters.get("category") and filters["category"].lower() not in row.get("category", "").lower():
        return False
    return _matches_topic_for_row(row, data, filters.get("topic", ""))


def _hypothesis_clusters(rows: list[dict[str, Any]], hypotheses: list[str], selected: str, limit: int) -> list[dict[str, Any]]:
    clusters = []
    for hypothesis in ([selected] if selected else hypotheses):
        items = [row for row in rows if row["hypothesis_impacts"].get(hypothesis, {}).get("mi5_label")]
        if not items:
            continue
        support = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] in SUPPORT_CLASSES]
        challenge = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] in CHALLENGE_CLASSES]
        neutral = [row for row in items if row["hypothesis_impacts"][hypothesis]["classification"] not in SUPPORT_CLASSES | CHALLENGE_CLASSES]
        clusters.append(
            {
                "cluster_id": f"HYP_{hypothesis}",
                "cluster_type": "hypothesis",
                "hypothesis": hypothesis,
                "label": HYPOTHESIS_NAMES.get(hypothesis, hypothesis),
                "record_count": len(items),
                "support_count": len(support),
                "challenge_count": len(challenge),
                "neutral_count": len(neutral),
                "sources": sorted({row["source_id"] for row in items}),
                "top_categories": Counter(row.get("category", "") for row in items if row.get("category")).most_common(5),
                "strongest_items": [_item_trace(row, hypothesis) for row in items[:limit]],
                "apparent_conflicts": len(support) > 0 and len(challenge) > 0,
            }
        )
    return sorted(clusters, key=lambda item: (-item["record_count"], item["cluster_id"]))[:limit]


def _category_clusters(rows: list[dict[str, Any]], data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("category", "") or "Uncategorized"].append(row)
    clusters = []
    for category, items in grouped.items():
        hypotheses = sorted({hyp for row in items for hyp, impact in row["hypothesis_impacts"].items() if impact.get("mi5_label")})
        clusters.append(
            {
                "cluster_id": f"CAT_{_slug(category)}",
                "cluster_type": "category",
                "category": category,
                "record_count": len(items),
                "hypotheses": hypotheses,
                "sources": sorted({row["source_id"] for row in items}),
                "top_weighted_items": [_item_trace(row, hypotheses[0] if hypotheses else "") for row in items[:limit]],
                "unresolved_questions": [
                    _preview(data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}).get("uncertainty_notes", ""))
                    for row in items
                    if data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}).get("uncertainty_notes", "")
                ][:limit],
            }
        )
    return sorted(clusters, key=lambda item: (-item["record_count"], item["cluster_id"]))[:limit]


def _defeater_clusters(rows: list[dict[str, Any]], claims: list[dict[str, str]], criteria: list[dict[str, str]], data: dict[str, Any], hypotheses: list[str], limit: int) -> list[dict[str, Any]]:
    by_hyp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    claim_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in claims}
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}
    for row in rows:
        claim = claim_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}))
        criteria_row = criteria_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}))
        text = " ".join([row.get("category", ""), row.get("notes", ""), row.get("evidence_argument", ""), claim.get("claim_type", ""), claim.get("claim_text", "")]).lower()
        if not (any(term in text for term in ["objection", "defeater", "counterargument", "challenge"]) or _float(criteria_row.get("defeater_strength_0_5")) >= 4):
            continue
        row_hypotheses = [hyp for hyp in hypotheses if row["hypothesis_impacts"].get(hyp, {}).get("mi5_label")]
        for hypothesis in row_hypotheses or ["UNSPECIFIED"]:
            by_hyp[hypothesis].append(row | {"defeater_strength_0_5": criteria_row.get("defeater_strength_0_5", "")})
    clusters = []
    for hypothesis, items in by_hyp.items():
        clusters.append(
            {
                "cluster_id": f"DEF_{hypothesis}",
                "cluster_type": "defeater",
                "hypothesis": hypothesis,
                "record_count": len(items),
                "sources": sorted({row["source_id"] for row in items}),
                "items": [_item_trace(row, hypothesis) | {"defeater_strength_0_5": row.get("defeater_strength_0_5", "")} for row in items[:limit]],
            }
        )
    return sorted(clusters, key=lambda item: (-item["record_count"], item["cluster_id"]))[:limit]


def _conflict_clusters(rows: list[dict[str, Any]], hypotheses: list[str], selected: str, limit: int) -> list[dict[str, Any]]:
    clusters = []
    for hypothesis in ([selected] if selected else hypotheses):
        support = [row for row in rows if row["hypothesis_impacts"].get(hypothesis, {}).get("classification") in SUPPORT_CLASSES]
        challenge = [row for row in rows if row["hypothesis_impacts"].get(hypothesis, {}).get("classification") in CHALLENGE_CLASSES]
        if not support or not challenge:
            continue
        pairs = []
        count = 1
        for support_row in support:
            for challenge_row in challenge:
                if support_row.get("proposal_id") == challenge_row.get("proposal_id"):
                    continue
                pairs.append(
                    {
                        "cluster_id": f"CONFLICT_{hypothesis}_{count:03d}",
                        "hypothesis": hypothesis,
                        "description": "apparent tension between support and challenge records",
                        "strength": "stronger" if support_row["approved_weight_numeric"] >= 3 and challenge_row["approved_weight_numeric"] >= 3 else "possible",
                        "support_item": _item_trace(support_row, hypothesis),
                        "challenge_item": _item_trace(challenge_row, hypothesis),
                    }
                )
                count += 1
        clusters.append(
            {
                "cluster_id": f"CONFLICT_{hypothesis}",
                "cluster_type": "conflict",
                "hypothesis": hypothesis,
                "record_count": len(pairs),
                "sources": sorted({row["source_id"] for row in support + challenge}),
                "items": pairs[:limit],
            }
        )
    return sorted(clusters, key=lambda item: (-item["record_count"], item["cluster_id"]))[:limit]


def _salience_clusters(rows: list[dict[str, Any]], criteria: list[dict[str, str]], data: dict[str, Any], config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}
    items = []
    for row in rows:
        criteria_row = criteria_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}))
        flags = [flag for flag in _criteria_flags(criteria_row, config) if "salience" in flag or "moral stakes" in flag]
        if flags:
            items.append(_item_trace(row, "") | {"criteria_flags": flags})
    if not items:
        return []
    return [
        {
            "cluster_id": "SALIENCE_001",
            "cluster_type": "salience",
            "record_count": len(items),
            "sources": sorted({item["source_id"] for item in items}),
            "note": "Salience is separate from evidential weight.",
            "items": items[:limit],
        }
    ]


def _uncertainty_clusters(rows: list[dict[str, Any]], claims: list[dict[str, str]], criteria: list[dict[str, str]], deferred: list[dict[str, str]], data: dict[str, Any], config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}
    claim_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in claims}
    items = []
    for row in rows:
        criteria_row = criteria_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}))
        claim = claim_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["claim_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {}))
        flags = _criteria_flags(criteria_row, config)
        if "high uncertainty" in flags or "low clarity" in flags or claim.get("uncertainty_notes"):
            items.append(_item_trace(row, "") | {"criteria_flags": flags, "uncertainty_notes": claim.get("uncertainty_notes", "")})
    for row in deferred:
        items.append(
            {
                "source_id": row.get("source_id", ""),
                "claim_id": row.get("claim_id", ""),
                "proposal_id": row.get("proposal_id", ""),
                "category": "",
                "weight": 0,
                "mi5_label": "",
                "evidence_preview": _preview(row.get("evidence_argument", "")),
                "uncertainty_notes": row.get("deferral_reason", ""),
            }
        )
    if not items:
        return []
    return [
        {
            "cluster_id": "UNCERTAINTY_001",
            "cluster_type": "uncertainty",
            "record_count": len(items),
            "sources": sorted({item["source_id"] for item in items}),
            "items": items[:limit],
        }
    ]


def _cluster_summary(approved: list[dict[str, Any]], hypotheses: list[dict[str, Any]], categories: list[dict[str, Any]], defeaters: list[dict[str, Any]], conflicts: list[dict[str, Any]], salience: list[dict[str, Any]], uncertainty: list[dict[str, Any]]) -> dict[str, Any]:
    all_clusters = hypotheses + categories + defeaters + conflicts + salience + uncertainty
    return {
        "records_considered": len(approved),
        "cluster_count": len(all_clusters),
        "largest_clusters": _cluster_refs(sorted(all_clusters, key=lambda item: (-item.get("record_count", 0), item["cluster_id"]))[:5]),
        "highest_weight_clusters": _cluster_refs(sorted(all_clusters, key=lambda item: (-_cluster_max_weight(item), item["cluster_id"]))[:5]),
        "highest_uncertainty_clusters": _cluster_refs(uncertainty[:5]),
        "highest_defeater_clusters": _cluster_refs(defeaters[:5]),
        "high_salience_clusters": _cluster_refs(salience[:5]),
    }


def _cluster_study_priorities(*cluster_groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    clusters = [cluster for group in cluster_groups for cluster in group]
    priority_types = {"conflict": 5, "defeater": 4, "uncertainty": 3, "salience": 2, "hypothesis": 1, "category": 1}
    ranked = sorted(clusters, key=lambda item: (-priority_types.get(item.get("cluster_type", ""), 0), -item.get("record_count", 0), item["cluster_id"]))
    return [
        {
            "cluster_id": item["cluster_id"],
            "cluster_type": item.get("cluster_type", ""),
            "reason": _priority_reason(item),
            "suggested_next_action": "review trace rows and compare source contexts",
        }
        for item in ranked[:limit]
    ]


def _cluster_trace(*cluster_groups: list[dict[str, Any]], cluster_type: str) -> list[dict[str, Any]]:
    clusters = [cluster for group in cluster_groups for cluster in group]
    if cluster_type != "all":
        singular = {
            "hypotheses": "hypothesis",
            "categories": "category",
            "defeaters": "defeater",
            "conflicts": "conflict",
            "salience": "salience",
            "uncertainty": "uncertainty",
        }.get(cluster_type, cluster_type)
        clusters = [cluster for cluster in clusters if cluster.get("cluster_type") == singular]
    traces = []
    for cluster in clusters:
        items = cluster.get("items") or cluster.get("strongest_items") or cluster.get("top_weighted_items") or []
        for item in items:
            if "support_item" in item:
                for nested in [item["support_item"], item["challenge_item"]]:
                    traces.append(_cluster_trace_row(cluster, nested))
            else:
                traces.append(_cluster_trace_row(cluster, item))
    return sorted(traces, key=lambda item: (item["cluster_id"], item["source_id"], item["proposal_id"]))


def _source_centrality(source_ids: list[str], rows: list[dict[str, Any]], criteria: list[dict[str, str]], data: dict[str, Any], config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    criteria_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in criteria}
    centrality_min = int(config.get("centrality_min_count", 2) or 2)
    results = []
    for source_id in source_ids:
        source_rows = [row for row in rows if row["source_id"] == source_id]
        hypotheses = sorted({hyp for row in source_rows for hyp, impact in row["hypothesis_impacts"].items() if impact.get("mi5_label")})
        weights = [row["approved_weight_numeric"] for row in source_rows]
        flags = []
        for row in source_rows:
            flags.extend(_criteria_flags(criteria_index.get((row.get("claim_id", ""), row.get("source_id", "")), data["criteria_index"].get((row.get("claim_id", ""), row.get("source_id", "")), {})), config))
        results.append(
            {
                "source_id": source_id,
                "title": data["sources"].get(source_id, {}).get("title", ""),
                "approved_rows": len(source_rows),
                "hypotheses_touched": hypotheses,
                "hypothesis_count": len(hypotheses),
                "total_weight": round(sum(weights), 2),
                "max_weight": max(weights, default=0),
                "high_uncertainty_items": flags.count("high uncertainty"),
                "high_defeater_items": flags.count("high defeater strength"),
                "high_salience_items": sum(1 for flag in flags if "salience" in flag or "moral stakes" in flag),
                "centrality_note": "central" if len(source_rows) >= centrality_min else "peripheral",
            }
        )
    return sorted(results, key=lambda item: (-item["approved_rows"], -item["hypothesis_count"], -item["total_weight"], item["source_id"]))[:limit]


def _source_to_hypothesis_map(source_ids: list[str], rows: list[dict[str, Any]], hypotheses: list[str], selected: str) -> list[dict[str, Any]]:
    result = []
    for source_id in source_ids:
        entries = []
        for hypothesis in ([selected] if selected else hypotheses):
            items = [row for row in rows if row["source_id"] == source_id and row["hypothesis_impacts"].get(hypothesis, {}).get("mi5_label")]
            if not items:
                continue
            entries.append(
                {
                    "hypothesis": hypothesis,
                    "support": sum(1 for row in items if _classification_for(row, hypothesis) in SUPPORT_CLASSES),
                    "challenge": sum(1 for row in items if _classification_for(row, hypothesis) in CHALLENGE_CLASSES),
                    "mixed": sum(1 for row in items if _classification_for(row, hypothesis) not in SUPPORT_CLASSES | CHALLENGE_CLASSES),
                }
            )
        result.append({"source_id": source_id, "hypotheses": entries})
    return result


def _source_to_category_map(source_ids: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"source_id": source_id, "top_categories": Counter(row.get("category", "") for row in rows if row["source_id"] == source_id and row.get("category")).most_common(5)}
        for source_id in source_ids
    ]


def _shared_hypothesis_links(source_ids: list[str], rows: list[dict[str, Any]], hypotheses: list[str], selected: str) -> list[dict[str, Any]]:
    links = []
    for hypothesis in ([selected] if selected else hypotheses):
        linked = sorted({row["source_id"] for row in rows if row["hypothesis_impacts"].get(hypothesis, {}).get("mi5_label")})
        if len(linked) >= 2:
            links.append({"hypothesis": hypothesis, "source_ids": linked, "relationship": _relationship_for(hypothesis, linked, rows)})
    return links


def _source_conflicts(rows: list[dict[str, Any]], hypotheses: list[str], selected: str, limit: int) -> list[dict[str, Any]]:
    conflicts = []
    for hypothesis in ([selected] if selected else hypotheses):
        support_sources = {row["source_id"]: row for row in rows if _classification_for(row, hypothesis) in SUPPORT_CLASSES}
        challenge_sources = {row["source_id"]: row for row in rows if _classification_for(row, hypothesis) in CHALLENGE_CLASSES}
        for source_id, support_row in support_sources.items():
            for challenger_id, challenge_row in challenge_sources.items():
                if source_id == challenger_id:
                    continue
                conflicts.append(
                    {
                        "hypothesis": hypothesis,
                        "description": "source-level disagreement: one source supports while another challenges",
                        "support_source_id": source_id,
                        "challenge_source_id": challenger_id,
                        "support_item": _item_trace(support_row, hypothesis),
                        "challenge_item": _item_trace(challenge_row, hypothesis),
                    }
                )
    return sorted(conflicts, key=lambda item: (item["hypothesis"], item["support_source_id"], item["challenge_source_id"]))[:limit]


def _source_study_priorities(config: dict[str, Any], base_dir: str | Path, source_ids: list[str], rows: list[dict[str, Any]], criteria: list[dict[str, str]], limit: int, *, length: str) -> list[dict[str, Any]]:
    items = []
    for source_id in source_ids:
        study = build_study_queue(config, base_dir, source_id=source_id, limit=limit, include_deferred=True, include_reflections=False, length=length)
        if study.get("overall_status") == "pass" and study.get("study_items"):
            top = study["study_items"][0]
            items.append(
                {
                    "source_id": source_id,
                    "reason": top.get("reason_for_study", ""),
                    "suggested_next_action": top.get("suggested_next_action", ""),
                    "priority_score": top.get("priority_score", 0),
                    "proposal_id": top.get("proposal_id", ""),
                    "claim_id": top.get("claim_id", ""),
                }
            )
    return sorted(items, key=lambda item: (-float(item["priority_score"]), item["source_id"]))[:limit]


def _source_network_trace(source_ids: list[str], rows: list[dict[str, Any]], claims: list[dict[str, str]], category_map: list[dict[str, Any]], hypothesis_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    category_index = {row["source_id"]: row["top_categories"] for row in category_map}
    hypothesis_index = {row["source_id"]: [item["hypothesis"] for item in row["hypotheses"]] for row in hypothesis_map}
    return [
        {
            "source_id": source_id,
            "claim_ids": sorted({row.get("claim_id", "") for row in claims if row.get("source_id") == source_id and row.get("claim_id")}),
            "proposal_ids": sorted({row.get("proposal_id", "") for row in rows if row.get("source_id") == source_id and row.get("proposal_id")}),
            "hypotheses_touched": hypothesis_index.get(source_id, []),
            "top_categories": category_index.get(source_id, []),
            "review_statuses": ["approved"],
        }
        for source_id in source_ids
    ]


def _item_trace(row: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    if hypothesis:
        impact = row["hypothesis_impacts"].get(hypothesis, {})
        mi5 = impact.get("mi5_label", "")
    else:
        labels = [(hyp, impact.get("mi5_label", "")) for hyp, impact in row["hypothesis_impacts"].items() if impact.get("mi5_label")]
        hypothesis = labels[0][0] if labels else ""
        mi5 = labels[0][1] if labels else ""
    return {
        "source_id": row.get("source_id", ""),
        "claim_id": row.get("claim_id", ""),
        "proposal_id": row.get("proposal_id", ""),
        "category": row.get("category", ""),
        "hypothesis": hypothesis,
        "weight": row.get("approved_weight_numeric", 0),
        "mi5_label": mi5,
        "evidence_preview": _preview(row.get("evidence_argument", "")),
    }


def _cluster_trace_row(cluster: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": cluster["cluster_id"],
        "source_id": item.get("source_id", ""),
        "claim_id": item.get("claim_id", ""),
        "proposal_id": item.get("proposal_id", ""),
        "category": item.get("category", ""),
        "hypothesis": item.get("hypothesis", cluster.get("hypothesis", "")),
        "weight": item.get("weight", ""),
        "mi5_label": item.get("mi5_label", ""),
    }


def _cluster_refs(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"cluster_id": item["cluster_id"], "record_count": item.get("record_count", 0)} for item in clusters]


def _cluster_max_weight(cluster: dict[str, Any]) -> float:
    items = cluster.get("items") or cluster.get("strongest_items") or cluster.get("top_weighted_items") or []
    weights = []
    for item in items:
        if "support_item" in item:
            weights.extend([item["support_item"].get("weight", 0), item["challenge_item"].get("weight", 0)])
        else:
            weights.append(item.get("weight", 0))
    return max(weights, default=0)


def _priority_reason(cluster: dict[str, Any]) -> str:
    if cluster.get("cluster_type") == "conflict":
        return "apparent support/challenge tension"
    if cluster.get("cluster_type") == "defeater":
        return "defeater or objection records cluster here"
    if cluster.get("cluster_type") == "uncertainty":
        return "high uncertainty, low clarity, or deferred records"
    if cluster.get("cluster_type") == "salience":
        return "high salience needs evidential separation"
    return "large or recurring evidence cluster"


def _relationship_for(hypothesis: str, source_ids: list[str], rows: list[dict[str, Any]]) -> str:
    classes = {_classification_for(row, hypothesis) for row in rows if row["source_id"] in set(source_ids)}
    if classes & SUPPORT_CLASSES and classes & CHALLENGE_CLASSES:
        return "mixed support/challenge"
    if classes & SUPPORT_CLASSES:
        return "mostly support"
    if classes & CHALLENGE_CLASSES:
        return "mostly challenge"
    return "mixed/neutral"


def _summary_lines(summary: dict[str, Any]) -> list[str]:
    return [
        f"- Number of clusters: {summary['cluster_count']}",
        f"- Largest clusters: {summary['largest_clusters']}",
        f"- Highest-weight clusters: {summary['highest_weight_clusters']}",
        f"- Highest-uncertainty clusters: {summary['highest_uncertainty_clusters']}",
        f"- Highest-defeater clusters: {summary['highest_defeater_clusters']}",
        f"- High-salience clusters: {summary['high_salience_clusters']}",
    ]


def _cluster_lines(clusters: list[dict[str, Any]], *, length: str) -> list[str]:
    if not clusters:
        return ["- None"]
    lines = []
    for cluster in clusters:
        line = f"- {cluster['cluster_id']} ({cluster.get('cluster_type', '')}): records={cluster.get('record_count', 0)} sources={', '.join(cluster.get('sources', [])) or 'None'}"
        if cluster.get("apparent_conflicts"):
            line += " apparent conflicts=yes"
        if cluster.get("note"):
            line += f" note={cluster['note']}"
        lines.append(line)
        if length == "long":
            for item in (cluster.get("items") or cluster.get("strongest_items") or cluster.get("top_weighted_items") or [])[:5]:
                if "support_item" in item:
                    lines.append(f"  - {item['cluster_id']}: {item['support_item']['proposal_id']} vs {item['challenge_item']['proposal_id']}")
                else:
                    lines.append(f"  - {item.get('proposal_id', '')} / {item.get('claim_id', '')}: {item.get('evidence_preview', '')}")
    return lines


def _priority_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item['cluster_id']}: {item['reason']}. Next: {item['suggested_next_action']}." for item in items]


def _trace_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item['cluster_id']} | {item['source_id']} | {item['claim_id']} | {item['proposal_id']} | {item['category']} | {item['hypothesis']} | {item['weight']} | {item['mi5_label']}"
        for item in items
    ]


def _centrality_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = f"- {item['source_id']} {item['title']}: approved={item['approved_rows']} hypotheses={item['hypothesis_count']} total_weight={item['total_weight']} max_weight={item['max_weight']} {item['centrality_note']}"
        if length == "long":
            line += f" uncertainty={item['high_uncertainty_items']} defeaters={item['high_defeater_items']} salience={item['high_salience_items']}"
        lines.append(line)
    return lines


def _hypothesis_map_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item['source_id']}: {item['hypotheses']}" for item in items]


def _category_map_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item['source_id']}: {item['top_categories']}" for item in items]


def _shared_link_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item['hypothesis']}: {', '.join(item['source_ids'])} ({item['relationship']})" for item in items]


def _source_conflict_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = f"- {item['hypothesis']}: {item['support_source_id']} supports while {item['challenge_source_id']} challenges"
        if length == "long":
            line += f" ({item['support_item']['proposal_id']} vs {item['challenge_item']['proposal_id']})"
        lines.append(line)
    return lines


def _source_priority_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item['source_id']}: {item['reason']}. Next: {item['suggested_next_action']}." for item in items]


def _source_trace_lines(items: list[dict[str, Any]], *, length: str) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item['source_id']} | claims={', '.join(item['claim_ids']) or 'None'} | proposals={', '.join(item['proposal_ids']) or 'None'} | hypotheses={', '.join(item['hypotheses_touched']) or 'None'} | categories={item['top_categories']} | statuses={', '.join(item['review_statuses'])}"
        for item in items
    ]


def _clusters_discord(result: dict[str, Any]) -> str:
    summary = result["cluster_summary"]
    conflicts = result.get("conflict_clusters", [])
    priorities = result.get("study_priorities", [])
    lines = ["Evidence Clusters", "", "Top clusters:"]
    for index, cluster in enumerate(summary["largest_clusters"][:3], start=1):
        lines.append(f"{index}. {cluster['cluster_id']} - {cluster['record_count']} records.")
    lines.extend(["", "Biggest tension:"])
    if conflicts:
        cluster = conflicts[0]
        lines.append(f"- {cluster['hypothesis']} has support and challenge records across {', '.join(cluster['sources'])}.")
    else:
        lines.append("- None")
    lines.extend(["", "Study priority:"])
    lines.append(f"- Review {priorities[0]['cluster_id']}." if priorities else "- None")
    return "\n".join(lines).rstrip()


def _network_discord(result: dict[str, Any]) -> str:
    central = result.get("source_centrality_summary", [])
    conflicts = result.get("apparent_source_conflicts", [])
    priorities = result.get("source_study_priorities", [])
    lines = ["Source Network", "", "Most central sources:"]
    for index, item in enumerate(central[:3], start=1):
        lines.append(f"{index}. {item['source_id']} - touches {', '.join(item['hypotheses_touched']) or 'no hypotheses'}; {item['approved_rows']} approved rows.")
    lines.extend(["", "Apparent source conflict:"])
    if conflicts:
        item = conflicts[0]
        lines.append(f"- {item['support_source_id']} supports {item['hypothesis']}, while {item['challenge_source_id']} challenges {item['hypothesis']}.")
    else:
        lines.append("- None")
    lines.extend(["", "Study priority:"])
    lines.append(f"- {priorities[0]['source_id']} has {priorities[0]['reason']}." if priorities else "- None")
    return "\n".join(lines).rstrip()


def _cluster_label(filters: dict[str, Any]) -> str:
    if filters.get("source_id"):
        return filters["source_id"]
    if filters.get("topic"):
        return f"TOPIC_{_slug(filters['topic'])}"
    if filters.get("category"):
        return f"CAT_{_slug(filters['category'])}"
    return "ALL"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_") or "UNKNOWN"


def _clusters_error(message: str, cluster_type: str) -> dict[str, Any]:
    return {
        "generated_at": timestamp_iso(),
        "mode": "evidence_clusters",
        "filters": {},
        "cluster_type": cluster_type,
        "cluster_summary": {"records_considered": 0, "cluster_count": 0},
        "hypothesis_clusters": [],
        "category_clusters": [],
        "defeater_clusters": [],
        "conflict_clusters": [],
        "salience_clusters": [],
        "uncertainty_clusters": [],
        "study_priorities": [],
        "discord_section": "",
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "overall_status": "fail",
        "no_workbook_or_queue_data_modified": True,
    }


def _network_error(message: str) -> dict[str, Any]:
    return {
        "generated_at": timestamp_iso(),
        "mode": "source_network",
        "filters": {},
        "source_centrality_summary": [],
        "source_to_hypothesis_map": [],
        "source_to_category_map": [],
        "shared_hypothesis_links": [],
        "apparent_source_conflicts": [],
        "source_study_priorities": [],
        "discord_section": "",
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "overall_status": "fail",
        "no_workbook_or_queue_data_modified": True,
    }
