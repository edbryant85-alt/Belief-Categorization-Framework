from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import (
    DuplicateSourceError,
    QueueSetupError,
    append_import_log,
    find_source_dossier,
    read_source_dossiers,
    register_source,
)
from belief_dashboard.prompts import HYPOTHESIS_LABELS, PHILOSOPHICAL_SAFEGUARDS
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.sources import SourceRegistrationError, read_source_text
from belief_dashboard.utils import timestamp_for_filename


def bulk_register_sources(
    raw_sources_dir: str | Path,
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    source_type: str = "youtube_transcript",
    pattern: str = "*",
    recursive: bool = False,
    limit: int | None = None,
    author: str = "",
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    root = Path(raw_sources_dir)
    result: dict[str, Any] = {
        "raw_sources_dir": str(root),
        "source_type": source_type,
        "pattern": pattern,
        "recursive": recursive,
        "files_considered": 0,
        "registered": [],
        "skipped": [],
        "errors": [],
    }
    if not root.exists():
        result["errors"].append(f"Raw sources directory not found: {root}")
        return result

    candidates = sorted(path for path in (root.rglob(pattern) if recursive else root.glob(pattern)) if path.is_file())
    supported = {extension.lower() for extension in config["sources"]["supported_extensions"]}
    for path in candidates:
        if limit is not None and result["files_considered"] >= limit:
            break
        if path.suffix.lower() not in supported:
            continue
        result["files_considered"] += 1
        try:
            registered = register_source(
                path,
                queue_dir,
                config,
                source_type=source_type,
                author=author,
                allow_duplicate=allow_duplicate,
            )
        except DuplicateSourceError as exc:
            result["skipped"].append({"file_path": str(path), "reason": str(exc)})
            continue
        except (QueueSetupError, SourceRegistrationError) as exc:
            result["errors"].append(f"{path}: {exc}")
            continue
        result["registered"].append(
            {
                "source_id": registered["source_id"],
                "file_path": str(path),
                "title": registered["row"]["title"],
            }
        )
    return result


def generate_triage_prompt_packet(
    queue_dir: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    source_ids: list[str] | None = None,
    limit: int | None = None,
    include_triaged: bool = False,
    max_characters_per_source: int | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    selected = _selected_dossiers(
        queue_path,
        config,
        source_ids=source_ids,
        limit=limit,
        include_triaged=include_triaged,
    )
    if not selected:
        raise SourceRegistrationError("No sources matched the triage packet selection.")

    max_chars = max_characters_per_source or int(config["source_triage"]["max_characters_per_source"])
    source_blocks = []
    for dossier in selected:
        source_path = Path(dossier["original_file_path"])
        if not source_path.exists():
            raise FileNotFoundError(f"Registered source file no longer exists: {source_path}")
        source_text = read_source_text(source_path)
        included = source_text[:max_chars]
        source_blocks.append(
            {
                "source_id": dossier["source_id"],
                "dossier": dossier,
                "source_text": included,
                "characters_included": len(included),
                "truncated": len(source_text) > max_chars,
            }
        )

    source_label = "batch" if len(selected) > 1 else selected[0]["source_id"]
    output_path = Path(output_dir) / f"source_triage_{source_label}_{timestamp_for_filename(generated_at)}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_triage_prompt_packet(source_blocks, config), encoding="utf-8")

    append_import_log(
        queue_path / config["queues"]["files"]["import_log"],
        operation="generate_triage_prompt_packet",
        file_path=str(output_path),
        status="success",
        message=f"Generated triage prompt packet for {len(source_blocks)} source(s).",
        logged_at=generated_at,
    )
    return {
        "prompt_packet_path": str(output_path),
        "source_ids": [block["source_id"] for block in source_blocks],
        "source_count": len(source_blocks),
        "characters_included": sum(block["characters_included"] for block in source_blocks),
        "truncated_source_count": sum(1 for block in source_blocks if block["truncated"]),
    }


def render_triage_prompt_packet(source_blocks: list[dict[str, Any]], config: dict[str, Any]) -> str:
    actions = ", ".join(config["allowed_values"]["triage_actions"])
    statuses = ", ".join(config["allowed_values"]["triage_statuses"])
    lines = [
        "# Batch Source Triage Prompt Packet",
        "",
        "I am using a local belief-dashboard workflow. Please triage these sources before any full claim extraction. Return exactly one CSV-ready row per source using the source_triage schema.",
        "",
        "The workbook is the approved evidence ledger, not the intake desk. Most short transcripts should be archived, clustered, or studied later unless they clearly deserve full extraction.",
        "",
        "## Triage Task",
        "- Decide whether each source deserves full extraction now, later study, clustering with related sources, archival, or skipping.",
        "- Prefer conservative triage. Do not extract detailed claim rows here.",
        "- Preserve source IDs exactly.",
        "- Use priority_0_5 for triage priority, not evidential weight.",
        f"- Allowed triage_status values: {statuses}.",
        f"- Allowed recommended_action values: {actions}.",
        "",
        "## Hypotheses",
        *[f"- {key} - {label}" for key, label in HYPOTHESIS_LABELS.items()],
        "",
        "## Philosophical Safeguards",
        *[f"- {item}" for item in PHILOSOPHICAL_SAFEGUARDS],
        "",
        "## Return Format",
        "Return CSV-ready markdown table rows matching this schema:",
        ", ".join(QUEUE_SCHEMAS["source_triage"]),
        "",
        "Use recommended_action=full_extraction only when a source is likely to produce dashboard-worthy evidence rows.",
        "",
        "## Sources",
    ]
    for block in source_blocks:
        dossier = block["dossier"]
        lines.extend(
            [
                "",
                f"### {block['source_id']} - {dossier.get('title', '')}",
                f"- Source type: {dossier.get('source_type', '')}",
                f"- Author or speaker: {dossier.get('author_or_speaker', '')}",
                f"- URL: {dossier.get('url', '')}",
                f"- Original file path: {dossier.get('original_file_path', '')}",
                f"- Truncated: {block['truncated']}",
                "",
                "```text",
                block["source_text"],
                "```",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def build_triage_summary(
    queue_dir: str | Path,
    config: dict[str, Any],
    *,
    min_priority: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_dir)
    triage_rows = _read_rows(queue_path / config["queues"]["files"]["source_triage"])
    dossiers = {
        row.get("source_id", ""): row
        for row in read_source_dossiers(queue_path / config["queues"]["files"]["source_dossiers"])
    }
    min_candidate_priority = (
        min_priority
        if min_priority is not None
        else int(config["source_triage"]["default_candidate_min_priority"])
    )
    candidates = [
        _enrich_triage_row(row, dossiers)
        for row in triage_rows
        if (row.get("recommended_action") or "").strip() == "full_extraction"
        and _priority(row) >= min_candidate_priority
    ]
    candidates.sort(key=lambda row: (-_priority(row), row.get("source_id", "")))
    if limit is not None:
        candidates = candidates[:limit]
    return {
        "queue_dir": str(queue_path),
        "triaged_source_count": len(triage_rows),
        "by_status": dict(sorted(Counter((row.get("triage_status") or "(blank)") for row in triage_rows).items())),
        "by_recommended_action": dict(sorted(Counter((row.get("recommended_action") or "(blank)") for row in triage_rows).items())),
        "candidate_min_priority": min_candidate_priority,
        "full_extraction_candidates": candidates,
    }


def write_triage_summary_reports(
    summary: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"source_triage_summary_{stamp}.md"
    json_path = reports_path / f"source_triage_summary_{stamp}.json"
    markdown_path.write_text(render_triage_summary(summary), encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def render_triage_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Source Triage Summary",
        "",
        f"- Queue directory: `{summary['queue_dir']}`",
        f"- Triaged source count: `{summary['triaged_source_count']}`",
        f"- Candidate min priority: `{summary['candidate_min_priority']}`",
        "",
        "## By Status",
    ]
    lines.extend(f"- `{status}`: {count}" for status, count in summary["by_status"].items())
    lines.extend(["", "## By Recommended Action"])
    lines.extend(f"- `{action}`: {count}" for action, count in summary["by_recommended_action"].items())
    lines.extend(["", "## Full Extraction Candidates", "| source_id | priority | title | action |", "| --- | --- | --- | --- |"])
    for row in summary["full_extraction_candidates"]:
        lines.append(f"| {row['source_id']} | {row['priority_0_5']} | {row['title']} | {row['recommended_action']} |")
    lines.append("")
    return "\n".join(lines)


def _selected_dossiers(
    queue_dir: Path,
    config: dict[str, Any],
    *,
    source_ids: list[str] | None,
    limit: int | None,
    include_triaged: bool,
) -> list[dict[str, str]]:
    if source_ids:
        return [find_source_dossier(source_id, queue_dir, config) for source_id in source_ids]
    dossiers = read_source_dossiers(queue_dir / config["queues"]["files"]["source_dossiers"])
    triaged_ids = set()
    if not include_triaged:
        triaged_ids = {
            row.get("source_id", "")
            for row in _read_rows(queue_dir / config["queues"]["files"]["source_triage"])
        }
    selected = [row for row in dossiers if include_triaged or row.get("source_id", "") not in triaged_ids]
    return selected[:limit] if limit is not None else selected


def _enrich_triage_row(row: dict[str, str], dossiers: dict[str, dict[str, str]]) -> dict[str, str]:
    dossier = dossiers.get(row.get("source_id", ""), {})
    enriched = dict(row)
    enriched["title"] = dossier.get("title", "")
    enriched["source_type"] = dossier.get("source_type", "")
    enriched["original_file_path"] = dossier.get("original_file_path", "")
    return enriched


def _priority(row: dict[str, str]) -> float:
    try:
        return float(row.get("priority_0_5") or 0)
    except ValueError:
        return 0


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
