from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import find_source_dossier
from belief_dashboard.utils import timestamp_for_filename


PACKET_ACTIONS = {
    "extract_now",
    "extract_later",
    "skip_front_matter",
    "skip_bibliography",
    "skip_index",
    "skip_duplicate_or_noise",
    "needs_manual_review",
}

GROUP_ORDER = [
    "Introduction / What Good Is Apologetics",
    "How Do I Know Christianity Is True?",
    "Absurdity of Life without God",
    "Existence of God, chapter 3",
    "Existence of God, chapter 4",
    "Historical Knowledge",
    "Miracles",
    "Self-Understanding of Jesus",
    "Resurrection of Jesus",
    "Conclusion",
    "Bibliography/Index/End matter",
]

SAFETY_WARNINGS = [
    "This planner is read-only except for markdown/JSON planning reports under reports/source_packet_cycles.",
    "Do not process all packets from a long book in one unattended run.",
    "Generate CSVs only for human-selected packets, then diagnose, clean, validate, and dry-run before append.",
    "Append imports, review proposals, export workbooks, verify, promote, or rollback only through native CLI commands after explicit human approval.",
]

FRONT_MATTER_TERMS = [
    "preamble",
    "title page",
    "contents",
    "table of figures",
    "copyright",
    "dedication",
    "preface",
]

BIBLIOGRAPHY_TERMS = [
    "bibliography",
    "press_1983",
    "press, 1983",
    "standard_model_big_bang_126",
    "standard model big bang 126",
]

INDEX_TERMS = [
    "index",
    "becker_carl",
    "becker, carl",
    "jesus_seminar",
    "jesus seminar",
]

SUBSTANTIVE_TERMS = [
    "introduction",
    "what_good_is_apologetics",
    "what good is apologetics",
    "how_do_i_know_christianity_is_true",
    "how do i know christianity is true",
    "role_of_reason",
    "role of reason",
    "good_arguments",
    "good arguments",
    "no_ultimate_meaning_without_god",
    "no ultimate meaning without god",
    "existence_of_god",
    "existence of god",
    "thomas_aquinas",
    "thomas aquinas",
    "william_sorley",
    "william sorley",
    "kalam",
    "kalām",
    "inflationary_multiverse",
    "inflationary multiverse",
    "design_hypothesis",
    "design hypothesis",
    "many_worlds",
    "many worlds",
    "historical_knowledge",
    "historical knowledge",
    "testing_historical_hypotheses",
    "testing historical hypotheses",
    "miracles",
    "self_understanding_of_jesus",
    "self-understanding of jesus",
    "self understanding of jesus",
    "historical_jesus",
    "historical jesus",
    "implicit_christology",
    "implicit christology",
    "resurrection",
    "conspiracy_hypothesis",
    "conspiracy hypothesis",
    "resurrection_appearances",
    "resurrection appearances",
]


def build_source_packet_cycle_plan(
    source_id: str,
    queue_dir: str | Path,
    prompt_packets_dir: str | Path,
    reports_dir: str | Path,
    config: dict[str, Any],
    *,
    source_map: str | Path | None = None,
    max_batch_size: int = 10,
    group: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if max_batch_size < 1:
        raise ValueError("--max-batch-size must be at least 1.")
    dossier = find_source_dossier(source_id, queue_dir, config)
    prompt_dir = Path(prompt_packets_dir)
    source_map_path = Path(source_map) if source_map else find_newest_source_map(source_id, prompt_dir)
    packet_rows = discover_packet_rows(source_id, prompt_dir, source_map_path=source_map_path)
    packets = [_classify_packet(row) for row in packet_rows]
    groups = _group_packets(packets)
    if group:
        selected_groups = [item for item in groups if item["group_name"].lower() == group.lower()]
        if not selected_groups:
            raise ValueError(f"Group not found in packet plan: {group}")
    else:
        selected_groups = groups
    recommended_first_batch = _recommended_first_batch(selected_groups, max_batch_size)
    counts = Counter(packet["recommended_action"] for packet in packets)
    report = {
        "source_id": source_id,
        "source_title": dossier.get("title", ""),
        "source_author": dossier.get("author_or_speaker", ""),
        "source_type": dossier.get("source_type", ""),
        "source_map_path": str(source_map_path) if source_map_path else "",
        "packet_count": len(packets),
        "classification_summary": {
            "total_packets": len(packets),
            "extract_now": counts["extract_now"],
            "extract_later": counts["extract_later"],
            "skipped_front_matter": counts["skip_front_matter"],
            "skipped_bibliography_index": counts["skip_bibliography"] + counts["skip_index"],
            "needs_manual_review": counts["needs_manual_review"],
        },
        "packets": packets,
        "groups": groups,
        "recommended_first_batch": recommended_first_batch,
        "safety_warnings": SAFETY_WARNINGS,
        "focused_group": group or "",
    }
    markdown_path, json_path = write_source_packet_cycle_reports(report, reports_dir, generated_at=generated_at)
    report["markdown_report_path"] = str(markdown_path)
    report["json_report_path"] = str(json_path)
    return report


def find_newest_source_map(source_id: str, prompt_packets_dir: str | Path) -> Path:
    prompt_dir = Path(prompt_packets_dir)
    maps = sorted(
        prompt_dir.glob(f"{source_id}_source_map_*.md"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    if not maps:
        raise FileNotFoundError(f"No source map found for {source_id} under {prompt_dir}")
    return maps[0]


def discover_packet_rows(
    source_id: str,
    prompt_packets_dir: str | Path,
    *,
    source_map_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    map_rows = _packet_rows_from_source_map(Path(source_map_path)) if source_map_path else []
    file_rows = _packet_rows_from_prompt_dir(source_id, Path(prompt_packets_dir))
    rows_by_id = {row["packet_id"]: row for row in map_rows}
    for row in file_rows:
        existing = rows_by_id.get(row["packet_id"], {})
        merged = {**existing, **row}
        if not merged.get("character_range"):
            merged["character_range"] = existing.get("character_range", "")
        rows_by_id[row["packet_id"]] = merged
    rows = list(rows_by_id.values())
    rows = [row for row in rows if row.get("packet_path") or row.get("packet_id", "").startswith(source_id)]
    rows.sort(key=lambda row: int(row.get("packet_number") or 0))
    return rows


def render_source_packet_cycle_markdown(report: dict[str, Any]) -> str:
    summary = report["classification_summary"]
    first_batch = report["recommended_first_batch"]
    lines = [
        f"# Packet Cycle Plan for {report['source_id']}",
        "",
        "## Source Summary",
        "",
        f"- source_id: `{report['source_id']}`",
        f"- title: {report['source_title']}",
        f"- author: {report['source_author']}",
        f"- source type: {report['source_type']}",
        f"- source map path: `{report['source_map_path']}`",
        f"- packet count: {report['packet_count']}",
        "",
        "## Overall Packet Classification Summary",
        "",
        f"- total packets: {summary['total_packets']}",
        f"- extract_now count: {summary['extract_now']}",
        f"- extract_later count: {summary['extract_later']}",
        f"- skipped front matter count: {summary['skipped_front_matter']}",
        f"- skipped bibliography/index count: {summary['skipped_bibliography_index']}",
        f"- needs_manual_review count: {summary['needs_manual_review']}",
        "",
        "## Recommended First Batch",
        "",
        f"- batch name: {first_batch['batch_name']}",
        f"- packet IDs: {', '.join(first_batch['packet_ids']) or '(none)'}",
        "- packet paths:",
    ]
    lines.extend([f"  - `{path}`" for path in first_batch["packet_paths"]] or ["  - (none)"])
    lines.extend(
        [
            f"- reason: {first_batch['reason']}",
            "- warnings:",
            *[f"  - {warning}" for warning in first_batch["warnings"]],
            "",
            "## Full Packet Table",
            "",
            "| packet_number | packet_slug/title | inferred chapter/group | recommended_action | reason | packet_path |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for packet in report["packets"]:
        lines.append(
            "| {packet_number} | {title} | {group_name} | {recommended_action} | {reason} | {packet_path} |".format(
                packet_number=packet["packet_number"],
                title=_md_cell(packet["packet_title"]),
                group_name=_md_cell(packet["group_name"]),
                recommended_action=packet["recommended_action"],
                reason=_md_cell(packet["reason"]),
                packet_path=f"`{packet['packet_path']}`",
            )
        )
    lines.extend(
        [
            "",
            "## Chapter/Group Table",
            "",
            "| group name | packet count | recommended priority | why it matters | recommended next action |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for group in report["groups"]:
        lines.append(
            f"| {_md_cell(group['group_name'])} | {group['packet_count']} | {group['recommended_priority']} | {_md_cell(group['why_it_matters'])} | {_md_cell(group['recommended_next_action'])} |"
        )
    lines.extend(
        [
            "",
            "## Operator Instructions",
            "",
            "- Process one batch at a time.",
            "- Use schema-locked packet text.",
            "- Generate CSVs only for selected packets.",
            "- Diagnose, clean, validate, and dry-run before append.",
            "- Append/review only through native CLI after human approval.",
            "- Do not process all packets from a long book in one unattended run.",
            "",
            "## Safety Warnings",
            "",
            *[f"- {warning}" for warning in report["safety_warnings"]],
            "",
        ]
    )
    return "\n".join(lines)


def write_source_packet_cycle_reports(
    report: dict[str, Any],
    reports_dir: str | Path,
    *,
    generated_at: datetime | None = None,
) -> tuple[Path, Path]:
    output_dir = Path(reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(generated_at)
    stem = f"{report['source_id']}_packet_cycle_plan_{stamp}"
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    markdown_path.write_text(render_source_packet_cycle_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return markdown_path, json_path


def _packet_rows_from_source_map(source_map_path: Path) -> list[dict[str, Any]]:
    if not source_map_path.exists():
        raise FileNotFoundError(f"Source map not found: {source_map_path}")
    rows: list[dict[str, Any]] = []
    for line in source_map_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| SRC"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        packet_id, character_range, headings, truncated, packet_path = cells[:5]
        number = _packet_number(packet_id) or _packet_number(packet_path)
        rows.append(
            {
                "packet_id": packet_id,
                "packet_number": number,
                "packet_title": _packet_title_from_path(packet_path) or headings.split(",")[0].strip(),
                "character_range": character_range,
                "included_headings": _split_headings(headings),
                "truncated": truncated.lower() == "true",
                "packet_path": packet_path,
            }
        )
    return rows


def _packet_rows_from_prompt_dir(source_id: str, prompt_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(prompt_dir.glob(f"{source_id}_schema_locked_packet_*.md")):
        text = path.read_text(encoding="utf-8")
        packet_id = _metadata_value(text, "Packet ID") or f"{source_id}-PKT-{_packet_number(path.name) or len(rows) + 1:03d}"
        headings = _split_headings(_metadata_value(text, "Included headings/pages"))
        rows.append(
            {
                "packet_id": packet_id,
                "packet_number": _packet_number(packet_id) or _packet_number(path.name) or len(rows) + 1,
                "packet_title": _metadata_value(text, "Packet label") or _packet_title_from_path(str(path)),
                "character_range": _metadata_value(text, "Character range"),
                "included_headings": headings,
                "truncated": False,
                "packet_path": str(path),
            }
        )
    return rows


def _classify_packet(row: dict[str, Any]) -> dict[str, Any]:
    title = row.get("packet_title", "")
    headings = row.get("included_headings") or []
    haystack = _normalize(" ".join([title, Path(row.get("packet_path", "")).stem, *headings]))
    group_name = _infer_group(haystack, row.get("packet_number") or 0)
    is_front_matter = (
        any(term in haystack for term in FRONT_MATTER_TERMS)
        and int(row.get("packet_number") or 0) <= 3
        and "what good is apologetics" not in haystack
    )
    is_bibliography = any(term in haystack for term in BIBLIOGRAPHY_TERMS)
    is_index = any(term in haystack for term in INDEX_TERMS) or (group_name == "Bibliography/Index/End matter" and "index" in haystack)
    substantive = any(term in haystack for term in SUBSTANTIVE_TERMS) or group_name not in {"Bibliography/Index/End matter", "Needs Manual Review"}
    noisy = _looks_noisy(title, headings)
    if is_front_matter:
        action = "skip_front_matter"
        reason = "Front matter/table-of-contents/preface material near the start of the book."
    elif is_index:
        action = "skip_index"
        reason = "Index-like packet or end-matter index entries."
    elif is_bibliography:
        action = "skip_bibliography"
        reason = "Bibliography-like references/end matter rather than argument text."
    elif noisy:
        action = "needs_manual_review"
        reason = "Heading/title detection looks noisy or citation-heavy; inspect before extraction."
    elif substantive:
        action = "extract_now" if group_name in GROUP_ORDER[:3] else "extract_later"
        reason = "Substantive chapter/topic material detected by transparent keyword heuristics."
    else:
        action = "needs_manual_review"
        reason = "Could not confidently classify packet from title/headings."
    return {
        "packet_id": row.get("packet_id", ""),
        "packet_number": int(row.get("packet_number") or 0),
        "packet_title": title,
        "packet_slug": _slug(title or Path(row.get("packet_path", "")).stem),
        "character_range": row.get("character_range", ""),
        "page_range": _infer_page_range(headings),
        "included_headings": headings,
        "looks_front_matter": is_front_matter,
        "looks_bibliography": is_bibliography,
        "looks_index": is_index,
        "looks_substantive_argument": substantive and action in {"extract_now", "extract_later"},
        "likely_chapter_or_part": group_name,
        "likely_topic": _infer_topic(haystack, group_name),
        "group_name": group_name,
        "recommended_action": action,
        "reason": reason,
        "packet_path": row.get("packet_path", ""),
    }


def _group_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_name = {name: [] for name in GROUP_ORDER}
    by_name["Needs Manual Review"] = []
    for packet in packets:
        by_name.setdefault(packet["group_name"], []).append(packet)
    for priority, name in enumerate([*GROUP_ORDER, "Needs Manual Review"], start=1):
        group_packets = by_name.get(name, [])
        if not group_packets:
            continue
        actions = Counter(packet["recommended_action"] for packet in group_packets)
        groups.append(
            {
                "group_name": name,
                "packet_count": len(group_packets),
                "packet_ids": [packet["packet_id"] for packet in group_packets],
                "packet_paths": [packet["packet_path"] for packet in group_packets],
                "packets": group_packets,
                "recommended_priority": priority,
                "why_it_matters": _why_group_matters(name),
                "recommended_next_action": _next_action_for_group(actions),
            }
        )
    return groups


def _recommended_first_batch(groups: list[dict[str, Any]], max_batch_size: int) -> dict[str, Any]:
    for group in groups:
        packet_ids = []
        packet_paths = []
        actionable_packets = [
            packet
            for packet in group.get("packets", [])
            if packet["recommended_action"] in {"extract_now", "extract_later", "needs_manual_review"}
        ]
        for packet in actionable_packets:
            if len(packet_ids) >= max_batch_size:
                break
            packet_ids.append(packet["packet_id"])
            packet_paths.append(packet["packet_path"])
        if packet_ids and group["recommended_next_action"] in {"extract_now", "extract_later", "needs_manual_review"}:
            return {
                "batch_name": group["group_name"],
                "packet_ids": packet_ids,
                "packet_paths": packet_paths,
                "reason": f"Highest-priority non-skipped group with a bounded batch size of {max_batch_size}.",
                "warnings": SAFETY_WARNINGS,
            }
    return {"batch_name": "", "packet_ids": [], "packet_paths": [], "reason": "No extractable packets found.", "warnings": SAFETY_WARNINGS}


def _infer_group(haystack: str, packet_number: int) -> str:
    if any(term in haystack for term in ["bibliography", "index", "press_1983", "becker_carl", "jesus_seminar"]):
        return "Bibliography/Index/End matter"
    if any(term in haystack for term in ["resurrection", "empty tomb", "conspiracy_hypothesis", "postmortem appearances", "christian faith"]):
        return "Resurrection of Jesus"
    if any(term in haystack for term in ["self_understanding_of_jesus", "self understanding of jesus", "historical jesus", "implicit_christology", "christology"]):
        return "Self-Understanding of Jesus"
    if "miracles" in haystack:
        return "Miracles"
    if any(term in haystack for term in ["historical_knowledge", "historical knowledge", "testing_historical_hypotheses", "testing historical hypotheses"]):
        return "Historical Knowledge"
    if any(term in haystack for term in ["design_hypothesis", "design hypothesis", "many_worlds", "many worlds", "inflationary_multiverse", "inflationary multiverse"]):
        return "Existence of God, chapter 4"
    if any(term in haystack for term in ["existence_of_god", "existence of god", "thomas_aquinas", "thomas aquinas", "william_sorley", "william sorley", "kalam", "kalām", "cosmological argument", "teleological argument", "moral argument"]):
        return "Existence of God, chapter 3"
    if any(term in haystack for term in ["no_ultimate_meaning_without_god", "no ultimate meaning without god", "de homine", "meaning of life", "value of life", "purpose of life", "human predicament"]):
        return "Absurdity of Life without God"
    if any(term in haystack for term in ["how_do_i_know_christianity_is_true", "how do i know christianity is true", "role_of_reason", "role of reason", "good_arguments", "good arguments", "de fide"]):
        return "How Do I Know Christianity Is True?"
    if "conclusion" in haystack and packet_number > 100:
        return "Conclusion"
    if packet_number:
        ranged = _group_from_packet_number(packet_number)
        if ranged and "introduction" in haystack:
            return ranged
    if any(term in haystack for term in ["introduction", "what_good_is_apologetics", "what good is apologetics"]) and packet_number <= 5:
        return "Introduction / What Good Is Apologetics"
    ranged = _group_from_packet_number(packet_number)
    if ranged:
        return ranged
    return "Needs Manual Review"


def _group_from_packet_number(packet_number: int) -> str:
    # Long OCR-derived book packets often repeat running headers and citations.
    # These broad bands are used only as a fallback when keyword matches are noisy.
    if 2 <= packet_number <= 5:
        return "Introduction / What Good Is Apologetics"
    if 6 <= packet_number <= 14:
        return "How Do I Know Christianity Is True?"
    if 15 <= packet_number <= 22:
        return "Absurdity of Life without God"
    if 23 <= packet_number <= 38:
        return "Existence of God, chapter 3"
    if 39 <= packet_number <= 52:
        return "Existence of God, chapter 4"
    if 53 <= packet_number <= 62:
        return "Historical Knowledge"
    if 63 <= packet_number <= 72:
        return "Miracles"
    if 73 <= packet_number <= 91:
        return "Self-Understanding of Jesus"
    if 92 <= packet_number <= 112:
        return "Resurrection of Jesus"
    if packet_number == 113:
        return "Conclusion"
    if packet_number >= 114:
        return "Bibliography/Index/End matter"
    return ""


def _infer_topic(haystack: str, group_name: str) -> str:
    for term in SUBSTANTIVE_TERMS:
        normalized = term.replace("_", " ")
        if term in haystack or normalized in haystack:
            return normalized
    return group_name


def _infer_page_range(headings: list[str]) -> str:
    pages = []
    for heading in headings:
        match = re.search(r"PDF Page\s+(\d+)", heading, flags=re.IGNORECASE)
        if match:
            pages.append(int(match.group(1)))
    if not pages:
        return ""
    return f"{min(pages)}-{max(pages)}" if min(pages) != max(pages) else str(pages[0])


def _looks_noisy(title: str, headings: list[str]) -> bool:
    combined = " ".join([title, *headings])
    citation_bits = len(re.findall(r"\b(?:ibid|press|university|translated|ed\.|vol\.|repr\.|fortress|eerdmans)\b", combined, flags=re.IGNORECASE))
    return citation_bits >= 8 or (not re.search(r"[A-Za-z]", title) and len(headings) <= 2)


def _why_group_matters(group_name: str) -> str:
    values = {
        "Introduction / What Good Is Apologetics": "Frames the apologetic method and intended use of arguments.",
        "How Do I Know Christianity Is True?": "Develops epistemology, reason, evidence, and the role of the Holy Spirit.",
        "Absurdity of Life without God": "Contains existential and moral arguments about meaning, value, and purpose.",
        "Existence of God, chapter 3": "Covers classical and kalam-style arguments for God's existence.",
        "Existence of God, chapter 4": "Covers cosmology, design, multiverse, and related scientific arguments.",
        "Historical Knowledge": "Defines the historical method used for later Christological and resurrection claims.",
        "Miracles": "Addresses miracle objections and probability/reasoning around miracle claims.",
        "Self-Understanding of Jesus": "Supports claims about Jesus's identity and implicit Christology.",
        "Resurrection of Jesus": "Central historical-apologetic case for resurrection claims.",
        "Conclusion": "May contain synthesis and ultimate apologetic framing.",
        "Bibliography/Index/End matter": "Usually citation/index support rather than extractable argument content.",
        "Needs Manual Review": "Ambiguous packets need human inspection before extraction.",
    }
    return values.get(group_name, "Packet group inferred from headings and filename keywords.")


def _next_action_for_group(actions: Counter[str]) -> str:
    for action in ["extract_now", "extract_later", "needs_manual_review", "skip_bibliography", "skip_index", "skip_front_matter"]:
        if actions[action]:
            return action
    return "skip_duplicate_or_noise"


def _metadata_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _packet_number(value: str) -> int:
    match = re.search(r"(?:PKT-|packet_)(\d+)", value)
    return int(match.group(1)) if match else 0


def _packet_title_from_path(packet_path: str) -> str:
    name = Path(packet_path).stem
    match = re.search(r"schema_locked_packet_\d+_(.+?)(?:_\d{4}-\d{2}-\d{2}_\d{6})?$", name)
    return match.group(1).replace("_", " ").strip() if match else ""


def _split_headings(value: str) -> list[str]:
    if not value or value == "(none)":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("-", " ").lower())


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")[:80]


def _md_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
