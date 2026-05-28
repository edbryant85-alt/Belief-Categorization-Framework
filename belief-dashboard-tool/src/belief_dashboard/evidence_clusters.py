from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import QueueSetupError, append_import_log, read_source_dossiers
from belief_dashboard.prompts import HYPOTHESIS_LABELS, PHILOSOPHICAL_SAFEGUARDS
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.sources import read_source_text
from belief_dashboard.utils import timestamp_for_filename


class EvidenceClusterError(ValueError):
    pass


CANDIDATE_ROLES = {"core_argument", "objection", "counter_objection", "theological_application"}


def init_cluster_queues(queue_dir: str | Path, config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    queue_path.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"base_dir": str(queue_path), "force": force, "created": [], "skipped": [], "overwritten": []}
    for queue_name in ["evidence_clusters", "source_cluster_members"]:
        path = queue_path / config["queues"]["files"][queue_name]
        action = _write_csv_template(path, QUEUE_SCHEMAS[queue_name], force=force)
        result[action].append(str(path))
    return result


def create_cluster(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    cluster_id: str,
    title: str,
    core_question: str,
    description: str = "",
    hypotheses: str = "",
    topic_tags: str = "",
    status: str = "active",
    notes: str = "",
    created_on: date | None = None,
) -> dict[str, Any]:
    _require_required(cluster_id, "cluster_id")
    _require_required(title, "title")
    _require_required(core_question, "core_question")
    _validate_allowed(status, "status", config["allowed_values"]["cluster_statuses"])
    queue_path = Path(queue_dir)
    clusters_path = queue_path / config["queues"]["files"]["evidence_clusters"]
    import_log_path = queue_path / config["queues"]["files"]["import_log"]
    _require_queue_file(clusters_path)
    _require_queue_file(import_log_path)
    rows = _read_rows(clusters_path)
    if any((row.get("cluster_id") or "").strip() == cluster_id for row in rows):
        raise EvidenceClusterError(f"cluster_id already exists in evidence_clusters.csv: {cluster_id}")
    today = (created_on or date.today()).isoformat()
    row = {header: "" for header in QUEUE_SCHEMAS["evidence_clusters"]}
    row.update(
        {
            "cluster_id": cluster_id,
            "cluster_title": title,
            "core_question": core_question,
            "description": description,
            "hypotheses_touched": hypotheses,
            "topic_tags": topic_tags,
            "status": status,
            "created_date": today,
            "updated_date": today,
            "notes": notes,
        }
    )
    _append_row(clusters_path, QUEUE_SCHEMAS["evidence_clusters"], row)
    append_import_log(
        import_log_path,
        operation="create_cluster",
        file_path=str(clusters_path),
        status="success",
        message=f"Created evidence cluster {cluster_id}.",
    )
    return {"cluster_id": cluster_id, "cluster_path": str(clusters_path), "row": row}


def add_source_to_cluster(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    cluster_id: str,
    source_id: str,
    role: str,
    subtopic: str = "",
    relevance: int | float | str = 0,
    priority: int | float | str = 0,
    status: str = "active",
    notes: str = "",
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    _validate_membership_inputs(config, role=role, relevance=relevance, priority=priority, status=status)
    cluster = find_cluster(queue_path, config, cluster_id)
    source = _find_source(queue_path, config, source_id)
    members_path = queue_path / config["queues"]["files"]["source_cluster_members"]
    import_log_path = queue_path / config["queues"]["files"]["import_log"]
    _require_queue_file(members_path)
    _require_queue_file(import_log_path)
    existing = _read_rows(members_path)
    if not allow_duplicate and any(
        (row.get("cluster_id") or "").strip() == cluster_id and (row.get("source_id") or "").strip() == source_id
        for row in existing
    ):
        raise EvidenceClusterError(f"Membership already exists for {cluster_id} + {source_id}.")
    row = {header: "" for header in QUEUE_SCHEMAS["source_cluster_members"]}
    row.update(
        {
            "cluster_id": cluster_id,
            "source_id": source_id,
            "source_role": role,
            "subtopic": subtopic,
            "relevance_0_5": _score_text(relevance),
            "priority_0_5": _score_text(priority),
            "status": status,
            "notes": notes,
        }
    )
    _append_row(members_path, QUEUE_SCHEMAS["source_cluster_members"], row)
    append_import_log(
        import_log_path,
        operation="add_source_to_cluster",
        file_path=str(members_path),
        status="success",
        message=f"Added {source_id} to cluster {cluster_id}.",
    )
    return {"cluster": cluster, "source": source, "membership_path": str(members_path), "row": row}


def bulk_add_sources_to_cluster(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    cluster_id: str,
    source_type: str | None = None,
    source_folder: str | Path | None = None,
    source_ids: list[str] | None = None,
    role: str,
    subtopic: str = "",
    relevance: int | float | str = 0,
    priority: int | float | str = 0,
    status: str = "active",
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    find_cluster(queue_path, config, cluster_id)
    _validate_membership_inputs(config, role=role, relevance=relevance, priority=priority, status=status)
    dossiers = read_source_dossiers(queue_path / config["queues"]["files"]["source_dossiers"])
    selected_ids = {item.strip() for item in source_ids or [] if item.strip()}
    folder_text = str(Path(source_folder)) if source_folder else ""
    candidates = []
    for dossier in dossiers:
        if selected_ids and dossier.get("source_id") not in selected_ids:
            continue
        if source_type and (dossier.get("source_type") or "") != source_type:
            continue
        if folder_text and not str(dossier.get("original_file_path") or "").startswith(folder_text):
            continue
        candidates.append(dossier)

    result = {"cluster_id": cluster_id, "considered": len(candidates), "added": [], "skipped": [], "failed": []}
    for dossier in candidates:
        try:
            added = add_source_to_cluster(
                queue_path,
                config,
                cluster_id=cluster_id,
                source_id=dossier["source_id"],
                role=role,
                subtopic=subtopic,
                relevance=relevance,
                priority=priority,
                status=status,
                allow_duplicate=allow_duplicate,
            )
        except EvidenceClusterError as exc:
            message = str(exc)
            if "Membership already exists" in message:
                result["skipped"].append({"source_id": dossier["source_id"], "reason": message})
            else:
                result["failed"].append({"source_id": dossier["source_id"], "reason": message})
            continue
        result["added"].append({"source_id": added["source"]["source_id"], "title": added["source"].get("title", "")})
    return result


def build_cluster_summary(queue_dir: str | Path, config: dict[str, Any], *, cluster_id: str) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    cluster = find_cluster(queue_path, config, cluster_id)
    members = _cluster_members(queue_path, config, cluster_id)
    dossiers = _dossiers_by_id(queue_path, config)
    enriched = [_enrich_member(member, dossiers) for member in members]
    by_role = Counter(row.get("source_role") or "(blank)" for row in members)
    by_status = Counter(row.get("status") or "(blank)" for row in members)
    by_type = Counter(row.get("source_type") or "(blank)" for row in enriched)
    top_priority = sorted(enriched, key=lambda row: (-_score(row.get("priority_0_5")), -_score(row.get("relevance_0_5")), row.get("source_id", "")))[:10]
    selected = [row for row in enriched if row.get("status") == "selected_for_extraction"]
    return {
        "cluster": cluster,
        "source_count": len(enriched),
        "counts_by_source_role": dict(sorted(by_role.items())),
        "counts_by_source_type": dict(sorted(by_type.items())),
        "counts_by_status": dict(sorted(by_status.items())),
        "top_priority_sources": top_priority,
        "selected_for_extraction": selected,
        "sources": enriched,
        "recommended_next_command": f"python -m belief_dashboard.cli generate-cluster-triage-packet --cluster-id {cluster_id}",
    }


def list_clusters(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    status: str | None = None,
    topic: str | None = None,
    hypothesis: str | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    clusters = _read_rows(queue_path / config["queues"]["files"]["evidence_clusters"])
    members = _read_rows(queue_path / config["queues"]["files"]["source_cluster_members"])
    source_counts = Counter(row.get("cluster_id") or "" for row in members)
    topic_text = (topic or "").lower().strip()
    hypothesis_text = (hypothesis or "").lower().strip()
    rows = []
    for row in clusters:
        haystack = " ".join([row.get("cluster_title", ""), row.get("description", ""), row.get("topic_tags", "")]).lower()
        hypotheses = (row.get("hypotheses_touched") or "").lower()
        if status and row.get("status") != status:
            continue
        if topic_text and topic_text not in haystack:
            continue
        if hypothesis_text and hypothesis_text not in hypotheses:
            continue
        enriched = dict(row)
        enriched["source_count"] = source_counts[row.get("cluster_id") or ""]
        rows.append(enriched)
    return {"rows": rows, "cluster_count": len(rows)}


def generate_cluster_triage_packet(
    queue_dir: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    cluster_id: str,
    max_sources: int | None = None,
    max_chars_per_source: int | None = None,
    include_role: str | None = None,
    output_path: str | Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    summary = build_cluster_summary(queue_dir, config, cluster_id=cluster_id)
    sources = summary["sources"]
    if include_role:
        sources = [row for row in sources if row.get("source_role") == include_role]
    limit = max_sources if max_sources is not None else int(config.get("evidence_clusters", {}).get("max_sources", 25))
    max_chars = max_chars_per_source if max_chars_per_source is not None else int(config.get("evidence_clusters", {}).get("max_characters_per_source", 2500))
    selected = sources[:limit]
    blocks = []
    for row in selected:
        path_text = row.get("original_file_path", "")
        source_text = ""
        warning = ""
        if path_text and Path(path_text).exists():
            raw_text = read_source_text(Path(path_text))
            source_text = raw_text[:max_chars]
            truncated = len(raw_text) > max_chars
        else:
            truncated = False
            warning = f"Registered source file not found: {path_text}"
        blocks.append({"member": row, "source_text": source_text, "truncated": truncated, "warning": warning})

    markdown = render_cluster_triage_packet(summary, blocks, config)
    out_path = Path(output_path) if output_path else Path(output_dir) / f"cluster_triage_{cluster_id}_{timestamp_for_filename(generated_at)}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return {
        "cluster_id": cluster_id,
        "prompt_packet_path": str(out_path),
        "source_count": len(selected),
        "characters_included": sum(len(block["source_text"]) for block in blocks),
    }


def render_cluster_triage_packet(summary: dict[str, Any], source_blocks: list[dict[str, Any]], config: dict[str, Any]) -> str:
    cluster = summary["cluster"]
    lines = [
        "# Evidence Cluster Triage Prompt Packet",
        "",
        "I am using a local belief-dashboard workflow. Please triage this evidence cluster before any full claim extraction or workbook updates.",
        "Return a cluster-level research map, not extracted_claims, criteria_matrix, or proposed_updates rows.",
        "",
        "## Cluster Metadata",
        f"- Cluster ID: {cluster.get('cluster_id', '')}",
        f"- Title: {cluster.get('cluster_title', '')}",
        f"- Core question: {cluster.get('core_question', '')}",
        f"- Description: {cluster.get('description', '')}",
        f"- Hypotheses touched: {cluster.get('hypotheses_touched', '')}",
        f"- Topic tags: {cluster.get('topic_tags', '')}",
        f"- Status: {cluster.get('status', '')}",
        "",
        "## Task",
        "Please return:",
        "1. cluster overview;",
        "2. major subtopics;",
        "3. source role recommendations;",
        "4. likely duplicate/background sources;",
        "5. likely sources for full claim extraction;",
        "6. major arguments;",
        "7. major objections;",
        "8. theological implications;",
        "9. unresolved questions;",
        "10. recommended next processing actions.",
        "",
        "Do not produce claim extraction rows in this pass.",
        "",
        "## Hypotheses",
        *[f"- {key} - {label}" for key, label in HYPOTHESIS_LABELS.items()],
        "",
        "## Philosophical Safeguards",
        *[f"- {item}" for item in PHILOSOPHICAL_SAFEGUARDS],
        "",
        "## Member Sources",
    ]
    for block in source_blocks:
        member = block["member"]
        lines.extend(
            [
                "",
                f"### {member.get('source_id', '')} - {member.get('title', '')}",
                f"- Source type: {member.get('source_type', '')}",
                f"- Source role: {member.get('source_role', '')}",
                f"- Subtopic: {member.get('subtopic', '')}",
                f"- Relevance: {member.get('relevance_0_5', '')}",
                f"- Priority: {member.get('priority_0_5', '')}",
                f"- Membership status: {member.get('status', '')}",
                f"- Original file path: {member.get('original_file_path', '')}",
                f"- Truncated: {block['truncated']}",
            ]
        )
        if block["warning"]:
            lines.append(f"- Warning: {block['warning']}")
        lines.extend(["", "```text", block["source_text"], "```"])
    lines.append("")
    return "\n".join(lines)


def cluster_candidates_for_extraction(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    cluster_id: str,
    min_priority: int | float | None = None,
) -> dict[str, Any]:
    threshold = min_priority
    if threshold is None:
        threshold = float(config.get("evidence_clusters", {}).get("default_candidate_min_priority", 4))
    high_relevance = float(config.get("evidence_clusters", {}).get("high_relevance_threshold", 4))
    summary = build_cluster_summary(queue_dir, config, cluster_id=cluster_id)
    rows = []
    for row in summary["sources"]:
        priority = _score(row.get("priority_0_5"))
        relevance = _score(row.get("relevance_0_5"))
        role = row.get("source_role") or ""
        if row.get("status") == "selected_for_extraction" or priority >= float(threshold) or (role in CANDIDATE_ROLES and relevance >= high_relevance):
            candidate = dict(row)
            candidate["suggested_next_command"] = f"python -m belief_dashboard.cli generate-prompt-packet --source-id {row.get('source_id', '')}"
            rows.append(candidate)
    rows.sort(key=lambda row: (-_score(row.get("priority_0_5")), -_score(row.get("relevance_0_5")), row.get("source_id", "")))
    return {"cluster_id": cluster_id, "min_priority": threshold, "rows": rows}


def write_cluster_summary_reports(summary: dict[str, Any], reports_dir: str | Path) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename()
    cluster_id = summary["cluster"]["cluster_id"]
    markdown_path = reports_path / f"cluster_summary_{cluster_id}_{stamp}.md"
    json_path = reports_path / f"cluster_summary_{cluster_id}_{stamp}.json"
    markdown_path.write_text(render_cluster_summary(summary), encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_cluster_summary(summary: dict[str, Any]) -> str:
    cluster = summary["cluster"]
    lines = [
        "# Evidence Cluster Summary",
        "",
        f"- Cluster ID: `{cluster.get('cluster_id', '')}`",
        f"- Title: {cluster.get('cluster_title', '')}",
        f"- Status: `{cluster.get('status', '')}`",
        f"- Source count: {summary['source_count']}",
        f"- Recommended next command: `{summary['recommended_next_command']}`",
        "",
        "## Counts By Source Role",
        *_counter_lines(summary["counts_by_source_role"]),
        "",
        "## Counts By Source Type",
        *_counter_lines(summary["counts_by_source_type"]),
        "",
        "## Counts By Status",
        *_counter_lines(summary["counts_by_status"]),
        "",
        "## Top Priority Sources",
    ]
    lines.extend(_source_lines(summary["top_priority_sources"]))
    lines.extend(["", "## Selected For Extraction"])
    lines.extend(_source_lines(summary["selected_for_extraction"]))
    lines.append("")
    return "\n".join(lines)


def find_cluster(queue_dir: str | Path, config: dict[str, Any], cluster_id: str) -> dict[str, str]:
    clusters_path = Path(queue_dir) / config["queues"]["files"]["evidence_clusters"]
    _require_queue_file(clusters_path)
    for row in _read_rows(clusters_path):
        if (row.get("cluster_id") or "").strip() == cluster_id:
            return row
    raise EvidenceClusterError(f"cluster_id not found in evidence_clusters.csv: {cluster_id}")


def _cluster_members(queue_dir: Path, config: dict[str, Any], cluster_id: str) -> list[dict[str, str]]:
    members_path = queue_dir / config["queues"]["files"]["source_cluster_members"]
    _require_queue_file(members_path)
    return [row for row in _read_rows(members_path) if (row.get("cluster_id") or "").strip() == cluster_id]


def _dossiers_by_id(queue_dir: Path, config: dict[str, Any]) -> dict[str, dict[str, str]]:
    rows = read_source_dossiers(queue_dir / config["queues"]["files"]["source_dossiers"])
    return {row.get("source_id", ""): row for row in rows}


def _find_source(queue_dir: Path, config: dict[str, Any], source_id: str) -> dict[str, str]:
    dossiers = _dossiers_by_id(queue_dir, config)
    if source_id not in dossiers:
        raise EvidenceClusterError(f"source_id not found in source_dossiers.csv: {source_id}")
    return dossiers[source_id]


def _enrich_member(member: dict[str, str], dossiers: dict[str, dict[str, str]]) -> dict[str, str]:
    source = dossiers.get(member.get("source_id", ""), {})
    enriched = dict(member)
    for field in ["source_type", "title", "author_or_speaker", "original_file_path", "url", "short_summary"]:
        enriched[field] = source.get(field, "")
    return enriched


def _validate_membership_inputs(
    config: dict[str, Any],
    *,
    role: str,
    relevance: int | float | str,
    priority: int | float | str,
    status: str,
) -> None:
    _validate_allowed(role, "source_role", config["allowed_values"]["source_cluster_roles"])
    _validate_allowed(status, "status", config["allowed_values"]["source_cluster_member_statuses"])
    _validate_score(relevance, "relevance_0_5")
    _validate_score(priority, "priority_0_5")


def _validate_allowed(value: str, field: str, allowed: list[str]) -> None:
    if value not in allowed:
        raise EvidenceClusterError(f"{field} has invalid value '{value}'. Allowed values: {', '.join(allowed)}.")


def _validate_score(value: int | float | str, field: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceClusterError(f"{field} must be numeric from 0 to 5.") from exc
    if number < 0 or number > 5:
        raise EvidenceClusterError(f"{field} must be between 0 and 5.")


def _require_required(value: str, field: str) -> None:
    if not value.strip():
        raise EvidenceClusterError(f"{field} is required.")


def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _score_text(value: int | float | str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _write_csv_template(path: Path, headers: list[str], *, force: bool) -> str:
    if path.exists() and not force:
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
    return "overwritten" if existed else "created"


def _require_queue_file(path: Path) -> None:
    if not path.exists():
        raise QueueSetupError(f"Required queue file not found: {path}. Run: python -m belief_dashboard.cli init-cluster-queues")


def _read_rows(path: Path) -> list[dict[str, str]]:
    _require_queue_file(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_row(path: Path, headers: list[str], row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writerow({header: row.get(header, "") for header in headers})


def _counter_lines(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- None"]
    return [f"- `{key}`: {value}" for key, value in counts.items()]


def _source_lines(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- `{row.get('source_id', '')}` {row.get('title', '')} | role `{row.get('source_role', '')}` | priority {row.get('priority_0_5', '')}"
        for row in rows
    ]
