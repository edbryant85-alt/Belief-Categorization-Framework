from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SAFE_MODES = ("inventory", "plan", "report")
DEFAULT_CORPORA = ("mosaic", "youtube", "reasonable_faith", "general_theology")
EXCLUDED_CORPORA = ("prophecy",)
PROPHECY_MARKERS = ("prophecy", "prophetic", "eschat", "revelation_study")
REPORT_DIR = Path("reports/agentflow_runs/corpus_backlog")
SOURCE_EXTENSIONS = {".md", ".txt", ".json"}
GENERATED_BATCH_SUFFIXES = (
    "_extracted_claims.csv",
    "_criteria_matrix.csv",
    "_proposed_updates.csv",
)


@dataclass(frozen=True)
class CorpusDefinition:
    name: str
    likely_paths: tuple[str, ...]
    docs: tuple[str, ...] = ()
    source_id: str | None = None
    known_batches: tuple[str, ...] = ()
    known_packet_count: int | None = None
    source_type: str | None = None


CORPUS_REGISTRY: dict[str, CorpusDefinition] = {
    "mosaic": CorpusDefinition(
        name="mosaic",
        likely_paths=(
            "data/raw_sources/clusters/mosaic",
            "data/raw_sources/mosaic",
            "data/external/mosaic",
            "source_packets/mosaic/batch_001",
        ),
        docs=("docs/mosaic_sermon_workflow.md",),
        known_batches=("batch_001",),
    ),
    "youtube": CorpusDefinition(
        name="youtube",
        likely_paths=(
            "data/raw_sources/youtube_test_batch",
            "data/raw_sources/youtube",
            "data/raw_sources/clusters/*/youtube",
        ),
    ),
    "reasonable_faith": CorpusDefinition(
        name="reasonable_faith",
        likely_paths=(
            "reports/prompt_packets/SRC0018*.md",
            "reports/source_packet_cycles/SRC0018*.json",
            "reports/source_packet_cycles/SRC0018*.md",
            "data/manual_imports/generated_batches/SRC0018_intro_apologetics",
        ),
        source_id="SRC0018",
        known_packet_count=116,
        source_type="book",
    ),
    "general_theology": CorpusDefinition(
        name="general_theology",
        likely_paths=(
            "data/raw_sources/clusters/christian_apologetics",
            "data/raw_sources/clusters/*/articles",
            "data/raw_sources/clusters/*/books",
            "data/raw_sources/clusters/*/youtube",
        ),
    ),
}


def run_corpus_backlog(
    *,
    corpora: list[str] | None = None,
    mode: str = "inventory",
    background_safe: bool = False,
    exclude_corpora: list[str] | None = None,
    project_dir: str | Path = ".",
) -> dict[str, Any]:
    project_path = Path(project_dir)
    if mode not in SAFE_MODES:
        raise ValueError(f"Unsupported safe mode: {mode}. Implemented modes: {', '.join(SAFE_MODES)}.")
    if not background_safe:
        raise PermissionError("corpus-backlog-runner requires --background-safe.")

    selected = _normalize_corpora(corpora)
    excluded = tuple(sorted(set(EXCLUDED_CORPORA).union(exclude_corpora or [])))
    _validate_corpora(selected, excluded)

    registered_sources = _read_registered_sources(project_path)
    clusters = _read_clusters(project_path)
    source_memberships = _read_source_cluster_members(project_path)
    generated_batches = _detect_generated_batches(project_path)
    packet_plans = _detect_packet_plans(project_path)
    validation_reports = _detect_validation_reports(project_path)
    qa_reports = _detect_qa_reports(project_path)

    corpus_reports = []
    all_unregistered = []
    for corpus_name in selected:
        definition = CORPUS_REGISTRY[corpus_name]
        candidates = _discover_candidates(project_path, definition)
        registered = _registered_for_corpus(definition, registered_sources)
        unregistered = [] if definition.source_id else _unregistered_candidates(candidates, registered_sources)
        existing_batches = _generated_batches_for_corpus(definition, generated_batches)
        existing_plans = _packet_plans_for_corpus(definition, packet_plans)
        corpus_clusters = _clusters_for_corpus(definition, clusters, source_memberships)
        state = {
            "corpus": corpus_name,
            "mode": mode,
            "known_batches": list(definition.known_batches),
            "known_packet_count": definition.known_packet_count,
            "candidate_files": candidates,
            "registered_sources": registered,
            "unregistered_candidates": unregistered,
            "clusters": corpus_clusters,
            "packet_plans": existing_plans,
            "generated_batches": existing_batches,
            "docs": _existing_docs(project_path, definition),
        }
        corpus_reports.append(state)
        all_unregistered.extend(unregistered)

    selected_generated_batches = _dedupe_dicts(_flatten("generated_batches", corpus_reports), "path")
    selected_packet_plans = _dedupe_dicts(_flatten("packet_plans", corpus_reports), "path")
    inbox = _build_human_review_inbox(selected_generated_batches, validation_reports, qa_reports)
    recommendations = _recommend_next_batches(selected, corpus_reports, selected_generated_batches, selected_packet_plans, inbox)
    status = "passed"

    report: dict[str, Any] = {
        "title": "Corpus Backlog Report",
        "flow": "corpus-backlog-runner",
        "status": status,
        "mode": mode,
        "corpora": selected,
        "excluded_corpora": list(excluded),
        "run_started_at": datetime.now().isoformat(timespec="seconds"),
        "registered_sources": _flatten("registered_sources", corpus_reports),
        "unregistered_candidates": all_unregistered,
        "clusters": _dedupe_dicts(_flatten("clusters", corpus_reports), "cluster_id", "path"),
        "packet_plans": selected_packet_plans,
        "generated_batches": selected_generated_batches,
        "validation_reports": validation_reports,
        "qa_reports": qa_reports,
        "human_review_inbox": inbox,
        "recommended_next_batches": recommendations,
        "corpus_details": corpus_reports,
        "safety": {
            "queues_mutated": False,
            "workbook_mutated": False,
            "real_append": False,
            "proposal_review_mutated": False,
            "committed": False,
            "pushed": False,
        },
    }
    paths = write_corpus_backlog_reports(project_path, report)
    report["report_paths"] = {key: str(value) for key, value in paths.items()}
    return report


def write_corpus_backlog_reports(project_path: Path, report: dict[str, Any]) -> dict[str, Path]:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    output_dir = project_path / REPORT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"corpus_backlog_report_{timestamp}.md"
    json_path = output_dir / f"corpus_backlog_report_{timestamp}.json"
    markdown_path.write_text(render_corpus_backlog_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"markdown": markdown_path, "json": json_path}


def render_corpus_backlog_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Corpus Backlog Report",
        "",
        "## Run Summary",
        "",
        f"- Flow: `{report['flow']}`",
        f"- Status: `{report['status']}`",
        f"- Mode: `{report['mode']}`",
        f"- Corpora included: {', '.join(report['corpora']) or 'None'}",
        "",
        "## Explicit Out Of Scope",
        "",
        "- Prophecy files excluded.",
        "- Prophecy documents were not registered, triaged, packetized, staged, or clustered.",
        "",
        "## Registered Sources",
        "",
        *_source_lines(report.get("registered_sources", [])),
        "",
        "## Unregistered Candidates",
        "",
        *_candidate_lines(report.get("unregistered_candidates", [])),
        "",
        "## Existing Clusters Detected",
        "",
        *_cluster_lines(report.get("clusters", [])),
        "",
        "## Existing Packet Maps Detected",
        "",
        *_path_lines(report.get("packet_plans", []), label_keys=("source_id", "packet_count")),
        "",
        "## Existing Generated CSV Batches Detected",
        "",
        *_batch_lines(report.get("generated_batches", [])),
        "",
        "## Existing Validation And QA Status",
        "",
        f"- Validation reports discovered: {len(report.get('validation_reports', []))}",
        f"- QA reports discovered: {len(report.get('qa_reports', []))}",
        "",
        "## Recommended Next Processing Batches",
        "",
        *_recommendation_lines(report.get("recommended_next_batches", [])),
        "",
        "## Human Review Inbox",
        "",
        *_inbox_lines(report.get("human_review_inbox", [])),
        "",
        "## Safety Summary",
        "",
    ]
    for key, value in report["safety"].items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines).rstrip() + "\n"


def _normalize_corpora(corpora: list[str] | None) -> list[str]:
    if not corpora:
        return list(DEFAULT_CORPORA)
    normalized: list[str] = []
    for item in corpora:
        if item == "all":
            normalized.extend(DEFAULT_CORPORA)
        else:
            normalized.append(item)
    return list(dict.fromkeys(normalized))


def _validate_corpora(selected: list[str], excluded: tuple[str, ...]) -> None:
    unknown = [name for name in selected if name not in CORPUS_REGISTRY]
    if unknown:
        raise ValueError(f"Unknown corpus/corpora: {', '.join(unknown)}")
    blocked = [name for name in selected if name in excluded]
    if blocked:
        raise PermissionError(f"Excluded corpus requested: {', '.join(blocked)}")


def _read_registered_sources(project_path: Path) -> list[dict[str, Any]]:
    return _read_queue_csv(project_path / "data/queues/source_dossiers.csv")


def _read_clusters(project_path: Path) -> list[dict[str, Any]]:
    return _read_queue_csv(project_path / "data/queues/evidence_clusters.csv")


def _read_source_cluster_members(project_path: Path) -> list[dict[str, Any]]:
    return _read_queue_csv(project_path / "data/queues/source_cluster_members.csv")


def _read_queue_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _discover_candidates(project_path: Path, definition: CorpusDefinition) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for pattern in definition.likely_paths:
        matches = sorted(project_path.glob(pattern))
        for match in matches:
            if _is_prophecy_project_path(project_path, match):
                continue
            if match.is_file() and match.suffix.lower() in SOURCE_EXTENSIONS:
                candidates.append(_candidate(project_path, match, definition.name))
            elif match.is_dir():
                for path in sorted(match.rglob("*")):
                    if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS and not _is_prophecy_project_path(project_path, path):
                        candidates.append(_candidate(project_path, path, definition.name))
    return _dedupe_dicts(candidates, "path")


def _candidate(project_path: Path, path: Path, corpus_name: str) -> dict[str, Any]:
    return {
        "corpus": corpus_name,
        "path": _relative(project_path, path),
        "filename": path.name,
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _registered_for_corpus(definition: CorpusDefinition, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if definition.source_id:
        return [_source_summary(row, definition.name) for row in sources if row.get("source_id") == definition.source_id]
    terms = _corpus_terms(definition.name)
    matched = []
    for row in sources:
        haystack = " ".join(str(row.get(key, "")) for key in ("source_type", "title", "original_file_path", "context")).lower()
        if any(term in haystack for term in terms):
            matched.append(_source_summary(row, definition.name))
    return matched


def _source_summary(row: dict[str, Any], corpus_name: str) -> dict[str, Any]:
    return {
        "corpus": corpus_name,
        "source_id": row.get("source_id", ""),
        "source_type": row.get("source_type", ""),
        "title": row.get("title", ""),
        "author_or_speaker": row.get("author_or_speaker", ""),
        "processing_status": row.get("processing_status", ""),
        "original_file_path": row.get("original_file_path", ""),
    }


def _corpus_terms(corpus_name: str) -> tuple[str, ...]:
    if corpus_name == "youtube":
        return ("youtube", "transcript", "watch")
    if corpus_name == "mosaic":
        return ("mosaic", "sermon")
    if corpus_name == "general_theology":
        return ("apologetic", "theology", "christian", "philosophy", "religion")
    return (corpus_name,)


def _unregistered_candidates(candidates: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registered_text = {
        str(row.get("original_file_path", "")).lower()
        for row in sources
        if row.get("original_file_path")
    }
    registered_titles = {str(row.get("title", "")).lower() for row in sources if row.get("title")}
    unregistered = []
    for candidate in candidates:
        path_text = candidate["path"].lower()
        stem_text = Path(candidate["filename"]).stem.lower()
        if path_text in registered_text or any(path_text.endswith(text) for text in registered_text):
            continue
        if stem_text in registered_titles:
            continue
        unregistered.append(candidate)
    return unregistered


def _detect_generated_batches(project_path: Path) -> list[dict[str, Any]]:
    roots = [
        project_path / "data/manual_imports/generated_batches",
        project_path / "data/external/mosaic/manual_import",
    ]
    batches: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
            if _is_prophecy_project_path(project_path, directory):
                continue
            csv_files = sorted(path for path in directory.glob("*.csv") if any(path.name.endswith(suffix) for suffix in GENERATED_BATCH_SUFFIXES))
            if not csv_files:
                continue
            batch = {
                "batch_id": directory.name,
                "path": _relative(project_path, directory),
                "corpus": _infer_corpus_from_path(directory),
                "csv_files": [_relative(project_path, path) for path in csv_files],
                "file_count": len(csv_files),
                "has_extracted_claims": any(path.name.endswith("_extracted_claims.csv") for path in csv_files),
                "has_criteria_matrix": any(path.name.endswith("_criteria_matrix.csv") for path in csv_files),
                "has_proposed_updates": any(path.name.endswith("_proposed_updates.csv") for path in csv_files),
                "validation_status": _validation_status_for_batch(project_path, directory),
                "human_review_report": _human_review_report_for_batch(project_path, directory),
            }
            batch["state"] = _batch_state(batch)
            batches.append(batch)
    return _dedupe_dicts(batches, "path")


def _batch_state(batch: dict[str, Any]) -> str:
    if batch.get("human_review_report"):
        return "needs_human_review_or_edits"
    if batch.get("file_count") == 3:
        return "ready_for_validation_and_human_review"
    return "needs_repair"


def _detect_packet_plans(project_path: Path) -> list[dict[str, Any]]:
    plans = []
    root = project_path / "reports/source_packet_cycles"
    if not root.exists():
        return plans
    for path in sorted(root.glob("*packet_cycle_plan*.json")):
        if _is_prophecy_project_path(project_path, path):
            continue
        data: dict[str, Any] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
        plans.append(
            {
                "path": _relative(project_path, path),
                "source_id": data.get("source_id", _source_id_from_text(path.name)),
                "source_title": data.get("source_title", ""),
                "packet_count": data.get("packet_count"),
                "classification_summary": data.get("classification_summary", {}),
            }
        )
    return plans


def _packet_plans_for_corpus(definition: CorpusDefinition, plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if definition.source_id:
        return [plan for plan in plans if plan.get("source_id") == definition.source_id]
    return [plan for plan in plans if definition.name in plan.get("path", "").lower()]


def _generated_batches_for_corpus(definition: CorpusDefinition, batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if definition.source_id:
        return [batch for batch in batches if definition.source_id.lower() in batch.get("path", "").lower()]
    return [batch for batch in batches if batch.get("corpus") == definition.name or definition.name in batch.get("path", "").lower()]


def _clusters_for_corpus(
    definition: CorpusDefinition,
    clusters: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = {definition.source_id} if definition.source_id else set()
    terms = _corpus_terms(definition.name)
    cluster_ids = {
        row.get("cluster_id", "")
        for row in memberships
        if row.get("source_id") in source_ids or any(term in str(row).lower() for term in terms)
    }
    matched = []
    for row in clusters:
        haystack = " ".join(str(value) for value in row.values()).lower()
        if row.get("cluster_id") in cluster_ids or any(term in haystack for term in terms):
            matched.append(
                {
                    "cluster_id": row.get("cluster_id", ""),
                    "cluster_title": row.get("cluster_title", ""),
                    "status": row.get("status", ""),
                    "path": "data/queues/evidence_clusters.csv",
                }
            )
    return matched


def _detect_validation_reports(project_path: Path) -> list[dict[str, Any]]:
    root = project_path / "reports/manual_imports"
    if not root.exists():
        return []
    reports = []
    for path in sorted(root.glob("*validation*.json")):
        if not _is_prophecy_project_path(project_path, path):
            reports.append({"path": _relative(project_path, path), "status": _json_status(path)})
    return reports


def _detect_qa_reports(project_path: Path) -> list[dict[str, Any]]:
    root = project_path / "reports/agentflow_runs"
    if not root.exists():
        return []
    reports = []
    for path in sorted(root.rglob("*qa*.json")):
        if not _is_prophecy_project_path(project_path, path):
            reports.append({"path": _relative(project_path, path), "status": _json_status(path)})
    return reports


def _validation_status_for_batch(project_path: Path, directory: Path) -> str:
    logs_dir = project_path / "reports/agentflow_runs" / directory.name / "logs"
    if not logs_dir.exists():
        matching = list((project_path / "reports/agentflow_runs").glob(f"*{directory.name}*/logs/validate_*.log"))
    else:
        matching = list(logs_dir.glob("validate_*.log"))
    if len(matching) >= 3:
        return "validation_logs_detected"
    return "not_discovered"


def _human_review_report_for_batch(project_path: Path, directory: Path) -> str:
    candidates = sorted((project_path / "reports/agentflow_runs").glob(f"*{directory.name}*/*human_review_report.md"))
    if candidates:
        return _relative(project_path, candidates[-1])
    candidates = sorted((project_path / "reports/agentflow_runs").glob(f"*/*{directory.name}*human*review*.md"))
    return _relative(project_path, candidates[-1]) if candidates else ""


def _build_human_review_inbox(
    generated_batches: list[dict[str, Any]],
    validation_reports: list[dict[str, Any]],
    qa_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inbox = []
    for batch in generated_batches:
        state = batch.get("state", "")
        action = "review"
        if batch.get("file_count", 0) < 3:
            action = "repair"
        elif batch.get("validation_status") == "validation_logs_detected":
            action = "human_review"
        inbox.append(
            {
                "batch_id": batch.get("batch_id", ""),
                "path": batch.get("path", ""),
                "corpus": batch.get("corpus", ""),
                "state": state,
                "recommended_action": action,
                "ready_for_append_after_human_confirmation": bool(batch.get("file_count") == 3 and batch.get("validation_status") == "validation_logs_detected"),
                "human_review_report": batch.get("human_review_report", ""),
            }
        )
    for report in [*validation_reports, *qa_reports]:
        if report.get("status") in {"failed", "blocked", "needs_cleanup"}:
            inbox.append(
                {
                    "batch_id": Path(report.get("path", "")).stem,
                    "path": report.get("path", ""),
                    "corpus": _infer_corpus_from_path(Path(report.get("path", ""))),
                    "state": report.get("status", ""),
                    "recommended_action": "repair",
                    "ready_for_append_after_human_confirmation": False,
                    "human_review_report": "",
                }
            )
    return _dedupe_dicts(inbox, "path", "batch_id")


def _recommend_next_batches(
    selected: list[str],
    corpus_reports: list[dict[str, Any]],
    generated_batches: list[dict[str, Any]],
    packet_plans: list[dict[str, Any]],
    inbox: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations = []
    if "reasonable_faith" in selected:
        intro_batch = next((batch for batch in generated_batches if "SRC0018_intro_apologetics" in batch.get("path", "")), None)
        if intro_batch:
            recommendations.append(
                {
                    "corpus": "reasonable_faith",
                    "batch_id": intro_batch["batch_id"],
                    "priority": 1,
                    "recommended_action": "human-review existing intro/apologetics generated batch before any append",
                    "path": intro_batch["path"],
                }
            )
        elif any(plan.get("source_id") == "SRC0018" for plan in packet_plans):
            recommendations.append(
                {
                    "corpus": "reasonable_faith",
                    "batch_id": "next_packet_cycle_group",
                    "priority": 1,
                    "recommended_action": "select the next packet-cycle batch from the SRC0018 plan; do not process all packets unattended",
                    "path": "reports/source_packet_cycles/",
                }
            )
    if "mosaic" in selected:
        mosaic_report = next((item for item in corpus_reports if item["corpus"] == "mosaic"), None)
        if mosaic_report and (mosaic_report.get("generated_batches") or mosaic_report.get("candidate_files")):
            recommendations.append(
                {
                    "corpus": "mosaic",
                    "batch_id": "batch_001",
                    "priority": 2,
                    "recommended_action": "review staged Mosaic Batch 1 as lived_belief_baseline intake before extraction selection",
                    "path": "data/external/mosaic/",
                }
            )
    if "youtube" in selected:
        youtube_report = next((item for item in corpus_reports if item["corpus"] == "youtube"), None)
        unregistered_count = len(youtube_report.get("unregistered_candidates", [])) if youtube_report else 0
        recommendations.append(
            {
                "corpus": "youtube",
                "batch_id": "youtube_triage_backlog",
                "priority": 3,
                "recommended_action": f"triage registered and unregistered YouTube transcript/watch-history candidates before extraction; unregistered candidates detected: {unregistered_count}",
                "path": "data/raw_sources/",
            }
        )
    repair_items = [item for item in inbox if item.get("recommended_action") == "repair"]
    if repair_items:
        recommendations.append(
            {
                "corpus": "all",
                "batch_id": "repair_inbox",
                "priority": 0,
                "recommended_action": f"repair {len(repair_items)} generated batch/report item(s) before append consideration",
                "path": "reports/agentflow_runs/corpus_backlog/",
            }
        )
    return sorted(recommendations, key=lambda row: int(row.get("priority", 99)))


def _existing_docs(project_path: Path, definition: CorpusDefinition) -> list[str]:
    return [_relative(project_path, project_path / doc) for doc in definition.docs if (project_path / doc).exists()]


def _infer_corpus_from_path(path: Path) -> str:
    text = path.as_posix().lower()
    if "mosaic" in text:
        return "mosaic"
    if "youtube" in text or "transcript" in text:
        return "youtube"
    if "src0018" in text or "reasonable" in text:
        return "reasonable_faith"
    if "christian_apologetics" in text or "theology" in text or "apologetic" in text:
        return "general_theology"
    return "unknown"


def _json_status(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unknown"
    return str(data.get("status", "unknown"))


def _source_id_from_text(text: str) -> str:
    for part in text.replace("-", "_").split("_"):
        if part.startswith("SRC") and len(part) >= 7:
            return part
    return ""


def _is_prophecy_path(path: Path) -> bool:
    text = path.as_posix().lower()
    return any(marker in text for marker in PROPHECY_MARKERS)


def _is_prophecy_project_path(project_path: Path, path: Path) -> bool:
    try:
        scoped = path.resolve().relative_to(project_path.resolve())
    except ValueError:
        scoped = path
    return _is_prophecy_path(scoped)


def _relative(project_path: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_path.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _flatten(key: str, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for report in reports:
        values.extend(report.get(key, []))
    return values


def _dedupe_dicts(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for row in rows:
        identity = tuple(row.get(key, "") for key in keys)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _source_lines(sources: list[dict[str, Any]]) -> list[str]:
    if not sources:
        return ["- None detected"]
    return [
        f"- `{source.get('source_id', '')}` [{source.get('corpus', '')}] {source.get('title', '')} ({source.get('source_type', '')}; {source.get('processing_status', '')})"
        for source in sources
    ]


def _candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return ["- None detected"]
    return [f"- [{item.get('corpus', '')}] `{item.get('path', '')}`" for item in candidates[:100]]


def _cluster_lines(clusters: list[dict[str, Any]]) -> list[str]:
    if not clusters:
        return ["- None detected"]
    return [f"- `{item.get('cluster_id', '')}` {item.get('cluster_title', '')} ({item.get('status', '')})" for item in clusters]


def _path_lines(items: list[dict[str, Any]], *, label_keys: tuple[str, ...]) -> list[str]:
    if not items:
        return ["- None detected"]
    lines = []
    for item in items:
        labels = ", ".join(f"{key}={item.get(key, '')}" for key in label_keys if item.get(key) not in {None, ""})
        lines.append(f"- `{item.get('path', '')}`{f' ({labels})' if labels else ''}")
    return lines


def _batch_lines(batches: list[dict[str, Any]]) -> list[str]:
    if not batches:
        return ["- None detected"]
    return [
        f"- `{batch.get('batch_id', '')}` [{batch.get('corpus', '')}] {batch.get('file_count', 0)} CSV(s), state={batch.get('state', '')}, path=`{batch.get('path', '')}`"
        for batch in batches
    ]


def _recommendation_lines(recommendations: list[dict[str, Any]]) -> list[str]:
    if not recommendations:
        return ["- None"]
    return [
        f"- Priority {item.get('priority', '')}: [{item.get('corpus', '')}] `{item.get('batch_id', '')}` - {item.get('recommended_action', '')}"
        for item in recommendations
    ]


def _inbox_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- `{item.get('batch_id', '')}` [{item.get('corpus', '')}] {item.get('recommended_action', '')}; state={item.get('state', '')}; append_after_human_confirmation={str(item.get('ready_for_append_after_human_confirmation', False)).lower()}"
        for item in items
    ]
