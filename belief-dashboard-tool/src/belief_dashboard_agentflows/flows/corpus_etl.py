from __future__ import annotations

import csv
import fnmatch
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard_agentflows.flows.archive_inventory import (
    ArchiveScanLimits,
    is_prophecy_text,
    scan_archive_root,
)
from belief_dashboard_agentflows.flows.corpus_backlog import (
    _detect_generated_batches,
    _detect_qa_reports,
    _detect_validation_reports,
    _read_registered_sources,
)
from belief_dashboard_agentflows.flows.drive_corpus_inventory import (
    GoogleApiDriveInventoryProvider,
    parse_drive_folder_id,
)


SAFE_MODES = {"inventory", "plan", "prepare", "review-pack"}
FUTURE_MODES = {"draft", "append-approved", "export-approved", "drive-stage", "drive-download"}
DEFAULT_OUTPUT_ROOT = Path("reports/agentflow_runs/corpus_etl")
MOSAIC_PLANNING_READ_LIMIT_BYTES = 2 * 1024 * 1024
MOSAIC_DEFAULT_BATCH_SIZE = 25
CANDIDATE_FIELDS = [
    "candidate_id",
    "corpus",
    "name",
    "relative_path",
    "absolute_path_or_archive_uri",
    "file_extension",
    "mime_type_or_inferred_type",
    "size_bytes",
    "modified_time",
    "created_time",
    "sha256",
    "hash_status",
    "content_status",
    "is_supported_text",
    "is_metadata_only",
    "is_large_file",
    "is_prophecy_excluded",
    "detected_source_type",
    "detected_title",
    "detected_author",
    "detected_date",
    "registered_match_status",
    "registered_source_id",
    "registered_match_reason",
    "file_role",
    "review_bucket",
    "cluster_suggestion",
    "source_role_suggestion",
    "recommended_action",
    "duplicate_risk",
    "priority_suggestion",
    "recommended_next_action",
    "warnings",
]


def run_corpus_etl(
    *,
    archive_root: str | Path | None = None,
    drive_folder_id: str | None = None,
    drive_folder_url: str | None = None,
    corpus: str,
    mode: str,
    background_safe: bool = False,
    max_sources: int | None = None,
    max_depth: int = 10,
    max_files: int = 5000,
    large_file_threshold_mb: int = 25,
    hash_threshold_mb: int = 10,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    overwrite: bool = False,
    run_id: str | None = None,
    json_only: bool = False,
    markdown_only: bool = False,
    project_dir: str | Path = ".",
) -> dict[str, Any]:
    if not archive_root and not drive_folder_id and not drive_folder_url:
        raise ValueError("Provide one of --archive-root, --drive-folder-id, or --drive-folder-url.")
    if is_prophecy_text(corpus):
        raise PermissionError("Prophecy corpora are explicitly excluded from corpus-etl.")

    project_path = Path(project_dir)
    run_started_at = datetime.now().isoformat(timespec="seconds")
    output_dir = _run_output_dir(project_path / output_root, corpus=corpus, mode=mode, run_id=run_id, overwrite=overwrite)
    warnings: list[str] = []
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    unsupported_files: list[dict[str, Any]] = []
    prophecy_exclusions: list[dict[str, Any]] = []
    status = "passed"
    refusal_reason = ""
    limits = {
        "max_sources": max_sources,
        "max_depth": max_depth,
        "max_files": max_files,
        "large_file_threshold_mb": large_file_threshold_mb,
        "hash_threshold_mb": hash_threshold_mb,
        "truncated_by_max_files": False,
        "truncated_by_max_sources": False,
        "truncated_by_depth": False,
    }

    if mode in FUTURE_MODES:
        status = "failed"
        refusal_reason = (
            f"Mode {mode} is documented for future use but is not implemented in the safe MVP. "
            "Run inventory, plan, prepare, or review-pack instead."
        )
        if background_safe:
            refusal_reason = f"Background-safe mode refuses future or mutating mode {mode}. " + refusal_reason
        warnings.append(refusal_reason)
    elif mode not in SAFE_MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    registered_sources = _read_registered_sources(project_path)
    existing_state = _existing_state(project_path, registered_sources)

    if not refusal_reason:
        if archive_root:
            scan = scan_archive_root(
                archive_root,
                corpus=corpus,
                limits=ArchiveScanLimits(
                    max_sources=max_sources,
                    max_depth=max_depth,
                    max_files=max_files,
                    large_file_threshold_mb=large_file_threshold_mb,
                    hash_threshold_mb=hash_threshold_mb,
                ),
            )
            candidates = _match_registered(scan.candidates, registered_sources)
            unsupported_files = scan.unsupported_files
            prophecy_exclusions = scan.prophecy_exclusions
            warnings.extend(scan.warnings)
            errors.extend(scan.errors)
            limits["truncated_by_max_files"] = scan.truncated_by_max_files
            limits["truncated_by_max_sources"] = scan.truncated_by_max_sources
            limits["truncated_by_depth"] = scan.truncated_by_depth
            root_path = Path(archive_root).expanduser()
            if not root_path.exists():
                status = "unavailable"
            elif scan.errors:
                status = "failed"
        else:
            status = "unavailable"
            parsed_id = drive_folder_id or parse_drive_folder_id(drive_folder_url or "")
            provider = GoogleApiDriveInventoryProvider()
            provider_status = provider.status()
            warnings.append(
                "Drive corpus-etl is metadata-only future compatibility for the MVP; no files were downloaded. "
                f"Parsed folder ID: {parsed_id or 'unavailable'}. Provider available: {str(provider_status.available).lower()}. "
                f"{provider_status.reason}"
            )

    counts = _counts(candidates, unsupported_files, prophecy_exclusions, errors, warnings)
    mosaic_planning = _mosaic_planning(corpus, mode, candidates, warnings) if not refusal_reason else _empty_mosaic_planning()
    recommendations = _recommended_next_batches(corpus, candidates, existing_state, mode, mosaic_planning)
    review_inbox = _human_review_inbox(candidates, unsupported_files, existing_state, recommendations, mosaic_planning) if mode == "review-pack" and not refusal_reason else []
    next_safe_steps = _next_safe_steps(status, mode, bool(archive_root), refusal_reason=refusal_reason)
    report: dict[str, Any] = {
        "title": "Corpus ETL Report",
        "flow": "corpus-etl",
        "status": status,
        "command": "corpus-etl",
        "command_invocation": _command_invocation(
            archive_root=archive_root,
            drive_folder_id=drive_folder_id,
            drive_folder_url=drive_folder_url,
            corpus=corpus,
            mode=mode,
            background_safe=background_safe,
            max_sources=max_sources,
            max_depth=max_depth,
            max_files=max_files,
            large_file_threshold_mb=large_file_threshold_mb,
            hash_threshold_mb=hash_threshold_mb,
            output_root=output_root,
            run_id=run_id,
            overwrite=overwrite,
        ),
        "working_directory": str(project_path.resolve()),
        "git_branch": _git(project_path, ["branch", "--show-current"]) or "unknown",
        "git_status_summary": _git_status_summary(project_path),
        "mode": mode,
        "corpus": corpus,
        "archive_root": str(archive_root or ""),
        "drive_folder_id": drive_folder_id or "",
        "drive_folder_url": drive_folder_url or "",
        "run_dir": str(output_dir),
        "background_safe": background_safe,
        "limits": limits,
        "counts": counts,
        "existing_state": existing_state,
        "candidate_sources": candidates,
        "unsupported_files": unsupported_files,
        "output_files": {},
        "mutations": _mutation_summary(),
        "prophecy_exclusions": prophecy_exclusions,
        "warnings": warnings,
        "errors": errors,
        "recommended_next_batches": recommendations,
        "mosaic_planning": mosaic_planning,
        "recommended_registration_batches": mosaic_planning.get("recommended_registration_batches", []),
        "manifest_files_used": mosaic_planning.get("manifest_files_used", []),
        "batch_support_files_used": mosaic_planning.get("batch_support_files_used", []),
        "human_review_inbox": review_inbox,
        "next_safe_steps": next_safe_steps,
        "run_started_at": run_started_at,
        "refusal_reason": refusal_reason,
    }
    paths = _write_outputs(output_dir, report, candidates, json_only=json_only, markdown_only=markdown_only)
    report["output_files"] = {key: str(value) for key, value in paths.items()}
    if not json_only and "markdown_report" in paths:
        paths["markdown_report"].write_text(render_corpus_etl_markdown(report), encoding="utf-8")
    if not markdown_only and "json_report" in paths:
        paths["json_report"].write_text(json.dumps(_json_payload(report), indent=2) + "\n", encoding="utf-8")
    return report


def render_corpus_etl_markdown(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    output_files = report.get("output_files", {})
    mutations = report.get("mutations", {})
    existing = report.get("existing_state", {})
    lines = [
        "# Corpus ETL Report",
        "",
        "## Run Summary",
        "",
        f"- Status: `{report.get('status', '')}`",
        f"- Command: `{report.get('command_invocation', '')}`",
        f"- Working directory: `{report.get('working_directory', '')}`",
        f"- Git branch: `{report.get('git_branch', '')}`",
        f"- Git status summary: `{report.get('git_status_summary', '')}`",
        f"- Archive root: `{report.get('archive_root') or 'not used'}`",
        f"- Drive folder ID: `{report.get('drive_folder_id') or 'not used'}`",
        f"- Drive folder URL: `{report.get('drive_folder_url') or 'not used'}`",
        f"- Corpus: `{report.get('corpus', '')}`",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Background-safe: `{str(report.get('background_safe', False)).lower()}`",
        "",
        "## Safety Summary",
        "",
        "- This controller writes metadata reports/manifests only.",
        "- It does not register sources, append imports, review proposals, export workbooks, promote, roll back, commit, or push.",
    ]
    for key, value in mutations.items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    lines.extend(
        [
            "",
            "## Candidate Source Counts",
            "",
            f"- Candidate files: `{counts.get('candidate_files', 0)}`",
            f"- Supported text files: `{counts.get('supported_text_files', 0)}`",
            f"- Metadata-only files: `{counts.get('metadata_only_files', 0)}`",
            f"- Metadata-only large files: `{counts.get('large_files', 0)}`",
            f"- Already registered: `{counts.get('already_registered', 0)}`",
            f"- Unregistered candidates: `{counts.get('unregistered_candidates', 0)}`",
            f"- Unsupported files: `{counts.get('unsupported_files', 0)}`",
            f"- Prophecy-excluded files: `{counts.get('prophecy_excluded', 0)}`",
            "",
            "## Review Bucket Counts",
            "",
            *_count_lines(counts.get("review_bucket_counts", {})),
            "",
            "## File Role Counts",
            "",
            *_count_lines(counts.get("file_role_counts", {})),
            "",
            "## Existing Generated Batches",
            "",
            *_batch_lines(existing.get("generated_batches", [])),
            "",
            "## Existing Validation State",
            "",
            f"- Validation ready: `{len(existing.get('validation_ready', []))}`",
            f"- Validation failed: `{len(existing.get('validation_failed', []))}`",
            "",
            "## Existing Proposals Awaiting Review",
            "",
            *_proposal_lines(existing.get("proposals_awaiting_review", [])),
            "",
            "## Recommended Next Batches",
            "",
            *_recommendation_lines(report.get("recommended_next_batches", [])),
            "",
            "## Mosaic Planning",
            "",
            *_mosaic_planning_lines(report.get("mosaic_planning", {})),
        ]
    )
    if report.get("mode") == "review-pack":
        lines.extend(["", "## Human Review Inbox Summary", "", *_inbox_lines(report.get("human_review_inbox", []))])
    lines.extend(
        [
            "",
            "## Prophecy Excluded",
            "",
            *_excluded_lines(report.get("prophecy_exclusions", [])),
            "",
            "## Output Paths",
            "",
        ]
    )
    lines.extend([f"- {key}: `{value}`" for key, value in output_files.items()] or ["- Output paths pending."])
    lines.extend(["", "## Warnings", "", *_bullet_lines(report.get("warnings", []))])
    lines.extend(["", "## Errors", "", *_bullet_lines(report.get("errors", []))])
    lines.extend(["", "## Next Safe Commands", "", *_bullet_lines(report.get("next_safe_steps", []))])
    lines.extend(
        [
            "",
            "## Explicit Confirmation",
            "",
            "- no raw archive copied: `true`",
            "- no queues mutated: `true`",
            "- no imports mutated: `true`",
            "- no proposals mutated: `true`",
            "- no workbook mutated: `true`",
            "- no commit: `true`",
            "- no push: `true`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(
    output_dir: Path,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    json_only: bool,
    markdown_only: bool,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if not json_only:
        paths["markdown_report"] = output_dir / "corpus_etl_report.md"
    if not markdown_only:
        paths["json_report"] = output_dir / "corpus_etl_report.json"
    if candidates and not json_only:
        paths["candidate_sources_csv"] = output_dir / "candidate_sources.csv"
        _write_candidate_csv(paths["candidate_sources_csv"], candidates)
    if report.get("mode") == "review-pack" and not json_only:
        paths["human_review_inbox"] = output_dir / "human_review_inbox.md"
        paths["human_review_inbox"].write_text(render_human_review_inbox(report), encoding="utf-8")
    report["output_files"] = {key: str(value) for key, value in paths.items()}
    return paths


def render_human_review_inbox(report: dict[str, Any]) -> str:
    lines = [
        "# Corpus ETL Human Review Inbox",
        "",
        f"- Corpus: `{report.get('corpus', '')}`",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Candidate files: `{report.get('counts', {}).get('candidate_files', 0)}`",
        f"- Unregistered candidates: `{report.get('counts', {}).get('unregistered_candidates', 0)}`",
        f"- Likely duplicate candidates: `{len([c for c in report.get('candidate_sources', []) if c.get('duplicate_risk') == 'possible'])}`",
        "",
        "## Recommended Mosaic Registration Batch",
        "",
        *_mosaic_registration_batch_lines(report.get("recommended_registration_batches", [])),
        "",
        "## Sources Needing Registration",
        "",
        *_inbox_lines(_inbox_bucket(report, "sources_needing_registration")),
        "",
        "## Artifacts Available For Validation",
        "",
        *_inbox_lines(_inbox_bucket(report, "artifacts_available_for_validation")),
        "",
        "## Manifests/Indexes Available For Planning",
        "",
        *_inbox_lines(_inbox_bucket(report, "manifests_available_for_planning")),
        "",
        "## Support Files Detected",
        "",
        *_inbox_lines(_inbox_bucket(report, "support_files_detected")),
        "",
        "## Unknown / Needs Manual Review",
        "",
        *_inbox_lines(_inbox_bucket(report, "unknown_review_needed")),
        "",
        "## Unsupported / Ignored",
        "",
        *_inbox_lines(_inbox_bucket(report, "unsupported_or_ignored")),
        "",
        "## Likely Duplicate Candidates",
        "",
        *_candidate_lines([item for item in report.get("candidate_sources", []) if item.get("duplicate_risk") == "possible"]),
        "",
        "## Next Recommended Action",
        "",
        *_recommendation_lines(report.get("recommended_next_batches", [])),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _write_candidate_csv(path: Path, candidates: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: candidate.get(field, "") for field in CANDIDATE_FIELDS})


def _match_registered(candidates: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for candidate in candidates:
        match = _registered_match(candidate, sources)
        candidate["registered_match_status"] = "matched" if match else "unmatched"
        candidate["registered_source_id"] = match.get("source_id", "") if match else ""
        candidate["registered_match_reason"] = match.get("_match_reason", "") if match else ""
        candidate["duplicate_risk"] = "possible" if match else "low"
        _classify_candidate(candidate, matched=bool(match))
    return candidates


def _classify_candidate(candidate: dict[str, Any], *, matched: bool) -> None:
    role, bucket, action, next_action = _candidate_role(candidate, matched=matched)
    candidate["file_role"] = role
    candidate["review_bucket"] = bucket
    candidate["recommended_action"] = action
    candidate["recommended_next_action"] = next_action


def _candidate_role(candidate: dict[str, Any], *, matched: bool) -> tuple[str, str, str, str]:
    rel = str(candidate.get("relative_path", "")).replace("\\", "/")
    rel_lower = rel.lower()
    name_lower = str(candidate.get("name", "")).lower()
    extension = str(candidate.get("file_extension", "")).lower()
    corpus = str(candidate.get("corpus", "")).lower()

    if matched:
        return (
            "registerable_source",
            "sources_ready_for_extraction",
            "already registered; inspect existing source state before extraction",
            "use existing source ID and guarded packet/workspace commands",
        )

    if _is_mosaic_source_packet(rel_lower):
        return (
            "registerable_source",
            "sources_needing_registration",
            "register as Mosaic sermon source packet through guarded registration workflow",
            "register selected source through existing guarded workflow",
        )

    if _matches_any(name_lower, ("*_extracted_claims.csv", "*_criteria_matrix.csv", "*_proposed_updates.csv")):
        return (
            "processing_artifact",
            "artifacts_available_for_validation",
            "validate/clean/import only through existing guarded manual-import workflow; do not register as a source",
            "validate artifact through existing guarded manual-import workflow",
        )

    if _matches_any(name_lower, ("*manifest*.csv", "*manifest*.md", "*streams_index*.csv", "*stream_urls*.txt", "*source_registry_seed*.csv")):
        return (
            "manifest_or_index",
            "manifests_available_for_planning",
            "use for planning/source mapping; do not register as source unless explicitly reviewed",
            "use for planning/source mapping only",
        )

    if _matches_any(name_lower, ("*source_triage_rows*.csv",)):
        return (
            "batch_support",
            "support_files_detected",
            "use as batch support; do not register directly as source unless explicitly reviewed",
            "review as batch support only",
        )

    if rel_lower.startswith("input_batches/") or "/input_batches/" in rel_lower:
        return (
            "batch_support",
            "support_files_detected",
            "use as batch support; do not register directly as source unless explicitly reviewed",
            "review as batch support only",
        )

    if name_lower in {"combined_youtube_watchlist.md", "combined_youtube_transcript_input.csv", "combined_youtube_all_entries.csv"}:
        return (
            "manifest_or_index",
            "manifests_available_for_planning",
            "use for planning/source mapping; do not register as source unless explicitly reviewed",
            "use for planning/source mapping only",
        )

    if "dan" in rel_lower and "mcclellan" in rel_lower and ("watch_history" in rel_lower or "watch history" in rel_lower or "titles" in rel_lower):
        return (
            "manifest_or_index",
            "manifests_available_for_planning",
            "use for planning/source mapping; do not register as source unless explicitly reviewed",
            "use for planning/source mapping only",
        )

    if extension in {".md", ".txt"}:
        action = "needs human review before registration"
        if corpus == "mosaic":
            action = "register as Mosaic sermon source packet through guarded registration workflow"
        return (
            "registerable_source",
            "sources_needing_registration",
            action,
            "register selected source through existing guarded workflow",
        )

    if candidate.get("is_metadata_only"):
        return (
            "metadata_only",
            "unknown_review_needed",
            "metadata only; inspect manually before any registration decision",
            "inspect metadata and decide whether a source document is available",
        )

    if extension in {".csv", ".json", ".jsonl"}:
        return (
            "manifest_or_index",
            "manifests_available_for_planning",
            "use for planning/source mapping; do not register as source unless explicitly reviewed",
            "use for planning/source mapping only",
        )

    return (
        "unknown_review_needed",
        "unknown_review_needed",
        "needs manual review before any source registration decision",
        "inspect manually before selecting a guarded workflow",
    )


def _is_mosaic_source_packet(relative_path: str) -> bool:
    return fnmatch.fnmatch(relative_path, "*/mosaic_source_packets/src-mosaic-*.md") or fnmatch.fnmatch(relative_path, "mosaic_source_packets/src-mosaic-*.md")


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


def _registered_match(candidate: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_path = str(candidate.get("absolute_path_or_archive_uri", "")).lower()
    rel_path = str(candidate.get("relative_path", "")).lower()
    title = str(candidate.get("detected_title", "")).lower()
    sha256 = str(candidate.get("sha256", "")).lower()
    for row in sources:
        haystack = " ".join(str(row.get(key, "")) for key in row.keys()).lower()
        if sha256 and sha256 in haystack:
            matched = dict(row)
            matched["_match_reason"] = "sha256"
            return matched
        if candidate_path and candidate_path in haystack:
            matched = dict(row)
            matched["_match_reason"] = "absolute path"
            return matched
        if rel_path and rel_path in haystack:
            matched = dict(row)
            matched["_match_reason"] = "relative path"
            return matched
        row_title = str(row.get("title", "")).lower()
        if title and row_title and (title == row_title or title in row_title or row_title in title):
            matched = dict(row)
            matched["_match_reason"] = "title similarity"
            return matched
    return None


def _existing_state(project_path: Path, registered_sources: list[dict[str, Any]]) -> dict[str, Any]:
    batches = _detect_generated_batches(project_path)
    validation_reports = _detect_validation_reports(project_path)
    qa_reports = _detect_qa_reports(project_path)
    validation_ready = [item for item in [*validation_reports, *qa_reports] if item.get("status") in {"pass", "passed", "ready"}]
    validation_failed = [item for item in [*validation_reports, *qa_reports] if item.get("status") in {"failed", "blocked", "needs_cleanup"}]
    proposals = _read_proposals_awaiting_review(project_path)
    return {
        "registered_sources": len(registered_sources),
        "generated_batches": batches,
        "validation_ready": validation_ready,
        "validation_failed": validation_failed,
        "proposals_awaiting_review": proposals,
    }


def _read_proposals_awaiting_review(project_path: Path) -> list[dict[str, Any]]:
    path = project_path / "data/queues/proposed_updates.csv"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("review_status", "proposed") in {"", "proposed", "needs_review"}:
                rows.append(
                    {
                        "proposal_id": row.get("proposal_id", ""),
                        "source_id": row.get("source_id", ""),
                        "claim_id": row.get("claim_id", ""),
                        "review_status": row.get("review_status", ""),
                        "category": row.get("category", ""),
                    }
                )
    return rows[:100]


def _counts(
    candidates: list[dict[str, Any]],
    unsupported_files: list[dict[str, Any]],
    prophecy_exclusions: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    already_registered = len([item for item in candidates if item.get("registered_match_status") == "matched"])
    review_bucket_counts = _value_counts(candidates, "review_bucket")
    file_role_counts = _value_counts(candidates, "file_role")
    if unsupported_files:
        review_bucket_counts["unsupported_or_ignored"] = review_bucket_counts.get("unsupported_or_ignored", 0) + len(unsupported_files)
        file_role_counts["unsupported_or_ignored"] = file_role_counts.get("unsupported_or_ignored", 0) + len(unsupported_files)
    return {
        "candidate_files": len(candidates),
        "supported_text_files": len([item for item in candidates if item.get("is_supported_text")]),
        "metadata_only_files": len([item for item in candidates if item.get("is_metadata_only")]),
        "large_files": len([item for item in candidates if item.get("is_large_file")]),
        "already_registered": already_registered,
        "unregistered_candidates": len(candidates) - already_registered,
        "unsupported_files": len(unsupported_files),
        "prophecy_excluded": len(prophecy_exclusions),
        "errors": len(errors),
        "warnings": len(warnings),
        "review_bucket_counts": review_bucket_counts,
        "file_role_counts": file_role_counts,
    }


def _recommended_next_batches(
    corpus: str,
    candidates: list[dict[str, Any]],
    existing_state: dict[str, Any],
    mode: str,
    mosaic_planning: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    repair_count = len(existing_state.get("validation_failed", []))
    if repair_count:
        recommendations.append(
            {
                "corpus": corpus,
                "batch_id": "repair_existing_validation_failures",
                "priority": 0,
                "recommended_action": f"repair {repair_count} failed or blocked validation/QA item(s) before new append consideration",
            }
        )
    mosaic_batches = (mosaic_planning or {}).get("recommended_registration_batches", [])
    if mosaic_batches:
        first_batch = mosaic_batches[0]
        recommendations.append(
            {
                "corpus": corpus,
                "batch_id": first_batch.get("batch_id", "mosaic_registration_batch"),
                "priority": 1,
                "recommended_action": (
                    f"review and register {len(first_batch.get('source_packets', []))} Mosaic source packet(s) "
                    "through existing guarded registration workflow; do not register artifacts"
                ),
            }
        )
    unregistered = [item for item in candidates if item.get("review_bucket") == "sources_needing_registration"]
    if unregistered:
        recommendations.append(
            {
                "corpus": corpus,
                "batch_id": "registration_review",
                "priority": 2 if mosaic_batches else 1,
                "recommended_action": f"review {len(unregistered)} unregistered candidate(s); register selected sources through existing guarded workflows",
            }
        )
    ready_batches = [batch for batch in existing_state.get("generated_batches", []) if batch.get("file_count") == 3]
    if ready_batches:
        recommendations.append(
            {
                "corpus": corpus,
                "batch_id": "generated_batch_review",
                "priority": 2,
                "recommended_action": f"human-review {len(ready_batches)} generated batch(es), then run validate-import and append-import --dry-run only",
            }
        )
    if not recommendations and mode in SAFE_MODES:
        recommendations.append(
            {
                "corpus": corpus,
                "batch_id": "no_action_detected",
                "priority": 9,
                "recommended_action": "no immediate batch action detected; review candidate manifest and existing state",
            }
        )
    return sorted(recommendations, key=lambda row: int(row.get("priority", 99)))


def _human_review_inbox(
    candidates: list[dict[str, Any]],
    unsupported_files: list[dict[str, Any]],
    existing_state: dict[str, Any],
    recommendations: list[dict[str, Any]],
    mosaic_planning: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    inbox: list[dict[str, Any]] = []
    for batch in existing_state.get("generated_batches", []):
        file_count = int(batch.get("file_count", 0) or 0)
        if file_count == 3:
            bucket = "append_after_confirmation" if batch.get("validation_status") == "validation_logs_detected" else "batches_ready_for_human_review"
            action = "human review before any real append"
        else:
            bucket = "batches_needing_repair"
            action = "repair generated batch before validation"
        inbox.append(
            {
                "bucket": bucket,
                "label": batch.get("batch_id", ""),
                "path": batch.get("path", ""),
                "state": batch.get("state", ""),
                "recommended_action": action,
            }
        )
    for batch in (mosaic_planning or {}).get("recommended_registration_batches", []):
        evidence = [*batch.get("manifest_files_used", []), *batch.get("batch_support_files_used", [])]
        inbox.append(
            {
                "bucket": "recommended_mosaic_registration_batch",
                "label": batch.get("batch_id", "mosaic_registration_batch"),
                "path": ", ".join(packet.get("relative_path", "") for packet in batch.get("source_packets", [])[:10]),
                "state": batch.get("selection_reason", ""),
                "recommended_action": (
                    f"register {len(batch.get('source_packets', []))} Mosaic source packet(s) through guarded registration workflow; "
                    f"evidence={', '.join(evidence) if evidence else 'candidate packet order'}"
                ),
            }
        )
    for item in candidates[:100]:
        bucket = item.get("review_bucket", "unknown_review_needed")
        if bucket == "sources_ready_for_extraction":
            continue
        inbox.append(
            {
                "bucket": bucket,
                "file_role": item.get("file_role", "unknown_review_needed"),
                "label": item.get("detected_title", item.get("name", "")),
                "path": item.get("relative_path", ""),
                "state": item.get("registered_match_status", ""),
                "recommended_action": item.get("recommended_action", ""),
            }
        )
    for item in unsupported_files[:100]:
        inbox.append(
            {
                "bucket": "unsupported_or_ignored",
                "file_role": "unsupported_or_ignored",
                "label": item.get("name", ""),
                "path": item.get("relative_path", ""),
                "state": item.get("reason", "unsupported_file_type"),
                "recommended_action": "unsupported file type ignored by corpus-etl; do not register directly as source unless explicitly reviewed",
            }
        )
    for recommendation in recommendations:
        inbox.append(
            {
                "bucket": "next_recommended_action",
                "label": recommendation.get("batch_id", ""),
                "path": "",
                "state": "recommendation",
                "recommended_action": recommendation.get("recommended_action", ""),
            }
        )
    return inbox


def _mosaic_planning(corpus: str, mode: str, candidates: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    planning = _empty_mosaic_planning()
    if corpus.lower() != "mosaic" or mode not in {"plan", "review-pack"}:
        return planning
    planning["enabled"] = True

    packet_candidates = _mosaic_packet_candidates(candidates)
    artifacts = [item for item in candidates if item.get("review_bucket") == "artifacts_available_for_validation"]
    manifest_candidates = [
        item
        for item in candidates
        if item.get("review_bucket") == "manifests_available_for_planning" and _is_mosaic_planning_manifest(str(item.get("relative_path", "")))
    ]
    support_candidates = [
        item
        for item in candidates
        if item.get("review_bucket") == "support_files_detected" and _is_mosaic_batch_support(str(item.get("relative_path", "")))
    ]
    planning["manifest_files_detected"] = [_planning_file_record(item) for item in manifest_candidates]
    planning["batch_support_files_detected"] = [_planning_file_record(item) for item in support_candidates]
    planning["artifacts_available_for_validation"] = [_planning_file_record(item) for item in artifacts]

    manifest_rows_by_packet: dict[str, dict[str, str]] = {}
    explicit_batch_packet_ids: list[str] = []

    for item in manifest_candidates:
        rows = _read_planning_rows(item, warnings)
        if rows or str(item.get("file_extension", "")).lower() == ".txt":
            planning["manifest_files_used"].append(str(item.get("relative_path", "")))
        for row in rows:
            packet_id = _row_packet_id(row)
            if packet_id:
                manifest_rows_by_packet[packet_id] = row

    for item in support_candidates:
        rows = _read_planning_rows(item, warnings)
        if rows or str(item.get("file_extension", "")).lower() == ".txt":
            planning["batch_support_files_used"].append(str(item.get("relative_path", "")))
        for row in rows:
            packet_id = _row_packet_id(row)
            if packet_id and packet_id not in explicit_batch_packet_ids:
                explicit_batch_packet_ids.append(packet_id)

    selected_ids = [packet_id for packet_id in explicit_batch_packet_ids if packet_id in packet_candidates]
    selection_reason = "batch support file mapping"
    batch_id = "mosaic_batch1_registration"
    if not selected_ids:
        selected_ids = sorted(packet_candidates.keys(), key=_mosaic_packet_sort_key)[:MOSAIC_DEFAULT_BATCH_SIZE]
        selection_reason = "next chronological packet batch"
        batch_id = "mosaic_next_chronological_registration"

    source_packets = [_packet_plan_record(packet_candidates[packet_id], manifest_rows_by_packet.get(packet_id, {})) for packet_id in selected_ids]
    if source_packets:
        planning["recommended_registration_batches"].append(
            {
                "batch_id": batch_id,
                "corpus": "mosaic",
                "selection_reason": selection_reason,
                "source_packets": source_packets,
                "manifest_files_used": list(dict.fromkeys(planning["manifest_files_used"])),
                "batch_support_files_used": list(dict.fromkeys(planning["batch_support_files_used"])),
                "artifacts_available_for_validation": planning["artifacts_available_for_validation"],
                "recommended_action": "register listed Mosaic source packets through existing guarded registration workflow; do not register processing artifacts",
                "next_safe_commands": [
                    "Review human_review_inbox.md and candidate_sources.csv.",
                    "Register only the listed Mosaic source packets through the existing guarded registration workflow.",
                    "Validate processing artifacts only through the existing guarded manual-import workflow.",
                ],
            }
        )
    return planning


def _empty_mosaic_planning() -> dict[str, Any]:
    return {
        "enabled": False,
        "manifest_files_detected": [],
        "batch_support_files_detected": [],
        "manifest_files_used": [],
        "batch_support_files_used": [],
        "artifacts_available_for_validation": [],
        "recommended_registration_batches": [],
    }


def _mosaic_packet_candidates(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    packets: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if item.get("review_bucket") != "sources_needing_registration":
            continue
        packet_id = _packet_id_from_text(f"{item.get('relative_path', '')} {item.get('name', '')}")
        if packet_id:
            packets[packet_id] = item
    return packets


def _is_mosaic_planning_manifest(relative_path: str) -> bool:
    name = Path(relative_path).name.lower()
    return name in {"mosaic_source_packet_manifest.csv", "mosaic_streams_index.csv"} or fnmatch.fnmatch(name, "*stream_urls*.txt")


def _is_mosaic_batch_support(relative_path: str) -> bool:
    rel = relative_path.replace("\\", "/").lower()
    name = Path(rel).name
    return name == "mosaic_batch1_source_triage_rows.csv" or rel.startswith("input_batches/") or "/input_batches/" in rel


def _planning_file_record(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "relative_path": candidate.get("relative_path", ""),
        "file_role": candidate.get("file_role", ""),
        "review_bucket": candidate.get("review_bucket", ""),
        "recommended_action": candidate.get("recommended_action", ""),
    }


def _read_planning_rows(candidate: dict[str, Any], warnings: list[str]) -> list[dict[str, str]]:
    extension = str(candidate.get("file_extension", "")).lower()
    path_text = str(candidate.get("absolute_path_or_archive_uri", ""))
    path = Path(path_text)
    if extension != ".csv":
        return []
    if not path.exists() or not path.is_file():
        warnings.append(f"Mosaic planning file unavailable for metadata parse: {candidate.get('relative_path', '')}")
        return []
    try:
        if path.stat().st_size > MOSAIC_PLANNING_READ_LIMIT_BYTES:
            warnings.append(f"Mosaic planning file skipped because it exceeds safe metadata parse limit: {candidate.get('relative_path', '')}")
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [{str(key or "").strip(): str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        warnings.append(f"Mosaic planning file could not be parsed: {candidate.get('relative_path', '')}: {exc}")
        return []


def _row_packet_id(row: dict[str, str]) -> str:
    for key, value in row.items():
        key_lower = key.lower()
        if key_lower in {"source_id", "packet_id", "source_packet_id", "id"} or "path" in key_lower or "source" in key_lower:
            packet_id = _packet_id_from_text(value)
            if packet_id:
                return packet_id
    return _packet_id_from_text(" ".join(row.values()))


def _packet_id_from_text(value: str) -> str:
    match = re.search(r"SRC-MOSAIC-\d{4}", value, flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _mosaic_packet_sort_key(packet_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", packet_id)
    return (int(match.group(1)) if match else 999999, packet_id)


def _packet_plan_record(candidate: dict[str, Any], manifest_row: dict[str, str]) -> dict[str, Any]:
    packet_id = _packet_id_from_text(f"{candidate.get('relative_path', '')} {candidate.get('name', '')}")
    return {
        "source_id": packet_id,
        "relative_path": candidate.get("relative_path", ""),
        "detected_title": candidate.get("detected_title", ""),
        "manifest_title": manifest_row.get("title", "") or manifest_row.get("sermon_title", ""),
        "manifest_url": manifest_row.get("url", "") or manifest_row.get("youtube_url", "") or manifest_row.get("stream_url", ""),
    }


def _json_payload(report: dict[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    payload.pop("candidate_sources", None)
    payload["output_files"] = report.get("output_files", {})
    return payload


def _value_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown_review_needed")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _count_lines(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["- None"]
    return [f"- {key}: `{value}`" for key, value in sorted(counts.items())]


def _inbox_bucket(report: dict[str, Any], bucket: str) -> list[dict[str, Any]]:
    return [item for item in report.get("human_review_inbox", []) if item.get("bucket") == bucket]


def _mosaic_registration_batch_lines(batches: list[dict[str, Any]]) -> list[str]:
    if not batches:
        return ["- None"]
    lines: list[str] = []
    for batch in batches:
        lines.append(
            f"- `{batch.get('batch_id', '')}` reason=`{batch.get('selection_reason', '')}` "
            f"packet_count=`{len(batch.get('source_packets', []))}` action=`{batch.get('recommended_action', '')}`"
        )
        evidence = [*batch.get("manifest_files_used", []), *batch.get("batch_support_files_used", [])]
        lines.append(f"  - Evidence: {', '.join(f'`{item}`' for item in evidence) if evidence else 'candidate packet order'}")
        for packet in batch.get("source_packets", [])[:50]:
            lines.append(f"  - `{packet.get('source_id', '')}` path=`{packet.get('relative_path', '')}`")
        if batch.get("artifacts_available_for_validation"):
            artifact_paths = [f"`{item.get('relative_path', '')}`" for item in batch.get("artifacts_available_for_validation", [])[:25]]
            lines.append(f"  - Artifacts available for validation: {', '.join(artifact_paths)}")
        for command in batch.get("next_safe_commands", []):
            lines.append(f"  - Next safe step: {command}")
    return lines


def _mosaic_planning_lines(planning: dict[str, Any]) -> list[str]:
    if not planning or not planning.get("enabled"):
        return ["- Not applicable"]
    lines = [
        f"- Manifest files detected: `{len(planning.get('manifest_files_detected', []))}`",
        f"- Batch support files detected: `{len(planning.get('batch_support_files_detected', []))}`",
        f"- Manifest files used: `{len(planning.get('manifest_files_used', []))}`",
        f"- Batch support files used: `{len(planning.get('batch_support_files_used', []))}`",
        f"- Artifacts available for validation: `{len(planning.get('artifacts_available_for_validation', []))}`",
        "",
        "### Recommended Registration Batches",
        "",
        *_mosaic_registration_batch_lines(planning.get("recommended_registration_batches", [])),
    ]
    return lines


def _run_output_dir(output_root: Path, *, corpus: str, mode: str, run_id: str | None, overwrite: bool) -> Path:
    resolved_run_id = run_id or f"{corpus}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = output_root / resolved_run_id
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        output_dir = output_root / f"{resolved_run_id}_{datetime.now().strftime('%f')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _command_invocation(**kwargs: Any) -> str:
    parts = ["python -m belief_dashboard_agentflows.cli corpus-etl"]
    if kwargs.get("archive_root"):
        parts.extend(["--archive-root", str(kwargs["archive_root"])])
    if kwargs.get("drive_folder_id"):
        parts.extend(["--drive-folder-id", str(kwargs["drive_folder_id"])])
    if kwargs.get("drive_folder_url"):
        parts.extend(["--drive-folder-url", str(kwargs["drive_folder_url"])])
    parts.extend(["--corpus", str(kwargs["corpus"]), "--mode", str(kwargs["mode"])])
    if kwargs.get("background_safe"):
        parts.append("--background-safe")
    for key, flag in [
        ("max_sources", "--max-sources"),
        ("max_depth", "--max-depth"),
        ("max_files", "--max-files"),
        ("large_file_threshold_mb", "--large-file-threshold-mb"),
        ("hash_threshold_mb", "--hash-threshold-mb"),
    ]:
        if kwargs.get(key) is not None:
            parts.extend([flag, str(kwargs[key])])
    if kwargs.get("run_id"):
        parts.extend(["--run-id", str(kwargs["run_id"])])
    if kwargs.get("overwrite"):
        parts.append("--overwrite")
    return " ".join(parts)


def _mutation_summary() -> dict[str, bool]:
    return {
        "raw_archive_copied": False,
        "queues_mutated": False,
        "imports_mutated": False,
        "proposals_mutated": False,
        "workbook_mutated": False,
        "committed": False,
        "pushed": False,
    }


def _next_safe_steps(status: str, mode: str, used_archive_root: bool, *, refusal_reason: str) -> list[str]:
    if refusal_reason:
        return ["Use inventory, plan, prepare, or review-pack for the safe MVP.", "Keep real append/export/proposal decisions in the native human-controlled CLI."]
    if status == "unavailable":
        if used_archive_root:
            return ["Provide an archive root that exists in this runtime environment.", "Do not copy the full archive into Git."]
        return ["Configure a future Drive metadata provider or run against a synced local archive root.", "Do not download raw Drive files in the MVP."]
    steps = [
        "Review corpus_etl_report.md and candidate_sources.csv.",
        "Register selected sources manually or through existing guarded registration workflows.",
        "Use packet/workspace, extraction QA, validate-import, and append-import --dry-run before any human-approved real append.",
    ]
    if mode == "review-pack":
        steps.insert(0, "Review human_review_inbox.md first.")
    return steps


def _git(project_path: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=project_path, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_status_summary(project_path: Path) -> str:
    output = _git(project_path, ["status", "--short"])
    if not output:
        return "clean"
    return f"{len(output.splitlines())} changed/untracked path(s)"


def _batch_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None detected"]
    return [f"- `{item.get('batch_id', '')}` state=`{item.get('state', '')}` path=`{item.get('path', '')}`" for item in items[:50]]


def _proposal_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None detected"]
    return [f"- `{item.get('proposal_id', '')}` source=`{item.get('source_id', '')}` status=`{item.get('review_status', '')}`" for item in items[:50]]


def _recommendation_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- Priority {item.get('priority', '')}: `{item.get('batch_id', '')}` - {item.get('recommended_action', '')}" for item in items]


def _inbox_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- `{item.get('label', '')}` [{item.get('bucket', '')}] {item.get('recommended_action', '')} {item.get('path', '')}".rstrip() for item in items[:100]]


def _excluded_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None detected"]
    return [f"- `{item.get('relative_path', '')}` reason=`{item.get('reason', '')}`" for item in items[:100]]


def _candidate_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None detected"]
    return [f"- `{item.get('relative_path', '')}` title=`{item.get('detected_title', '')}` action=`{item.get('recommended_action', '')}`" for item in items[:100]]


def _bullet_lines(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
