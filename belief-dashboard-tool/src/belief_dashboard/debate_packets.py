from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.debate_summaries import HYPOTHESIS_NAMES, build_debate_summary
from belief_dashboard.utils import timestamp_for_filename, timestamp_iso


def build_debate_packet(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    hypothesis: str | None = None,
    topic: str | None = None,
    limit: int | None = None,
    min_weight: float | None = None,
    exported_only: bool = False,
    include_unexported: bool = False,
    source_id: str | None = None,
    category: str | None = None,
    length: str = "medium",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if not hypothesis and not topic:
        return _error_result("Supply --hypothesis HYPOTHESIS_ID, --topic \"topic text\", or both.")

    hypotheses = [item.upper() for item in config["workbook"].get("hypotheses", HYPOTHESIS_NAMES)]
    selected_hypothesis = hypothesis.upper() if hypothesis else ""
    if selected_hypothesis and selected_hypothesis not in hypotheses:
        return _error_result(f"Unknown hypothesis ID: {hypothesis}")

    packet_config = config.get("debate_packets", {})
    item_limit = int(limit if limit is not None else packet_config.get("default_limit", 10))
    summary = build_debate_summary(
        config,
        base_dir,
        hypothesis=selected_hypothesis or None,
        all_hypotheses=not selected_hypothesis,
        limit=item_limit,
        min_weight=min_weight if min_weight is not None else packet_config.get("default_min_weight", 0),
        exported_only=exported_only,
        include_unexported=include_unexported,
        source_id=source_id,
        category=category,
        length=length,
        generated_at=generated_at,
    )
    if summary["overall_status"] == "fail":
        return _error_result("; ".join(summary["errors"]))

    queue_dir = _queue_dir(config, base_dir)
    files = config["queues"]["files"]
    source_rows = _read_optional_csv(queue_dir / files["source_dossiers"])
    claim_rows = _read_optional_csv(queue_dir / files["extracted_claims"])
    proposed_rows = _read_optional_csv(queue_dir / files["proposed_updates"])
    source_index = {row.get("source_id", ""): row for row in source_rows}
    claim_index = {(row.get("claim_id", ""), row.get("source_id", "")): row for row in claim_rows}
    proposed_index = {row.get("proposal_id", ""): row for row in proposed_rows}

    combined = _combine_items(summary, topic=topic)
    support = [item for item in combined if item["classification"] in {"strong_support", "moderate_support"}][:item_limit]
    challenge = [item for item in combined if item["classification"] in {"strong_challenge", "moderate_challenge"}][:item_limit]
    neutral = [item for item in combined if item["classification"] == "neutral_mixed"][:item_limit]
    objections = [
        item for item in combined
        if item.get("is_defeater") or _float_from_scores(item, "defeater_strength_0_5") >= 4
    ][:item_limit]
    counter_objections = [item for item in combined if item.get("is_counter_defeater")][:item_limit]
    criteria_highlights = _criteria_highlights(combined)[:item_limit]
    open_questions = _open_questions(combined, proposed_index)[:item_limit]
    source_trace = _source_trace(combined, source_index)
    trace_appendix = _trace_appendix(combined)
    framing = _debate_framing(selected_hypothesis, topic or "", support, challenge, objections, open_questions)
    discord = _discord_section(selected_hypothesis, topic or "", support, challenge, open_questions, framing)
    counts = _snapshot_counts(combined)

    return {
        "operation": "debate_packet",
        "generated_at": timestamp_iso(generated_at),
        "overall_status": "pass",
        "selection": {
            "hypothesis": selected_hypothesis,
            "hypothesis_name": HYPOTHESIS_NAMES.get(selected_hypothesis, "") if selected_hypothesis else "",
            "topic": topic or "",
        },
        "filters": {
            "limit": item_limit,
            "min_weight": min_weight if min_weight is not None else packet_config.get("default_min_weight", 0),
            "exported_only": exported_only,
            "include_unexported": include_unexported,
            "source_id": source_id or "",
            "category": category or "",
            "length": length,
        },
        "counts": counts,
        "overview": _overview(selected_hypothesis, topic or "", len(combined)),
        "support_items": support,
        "challenge_items": challenge,
        "neutral_items": neutral,
        "objections": objections,
        "counter_objections": counter_objections,
        "criteria_highlights": criteria_highlights,
        "source_trace": source_trace,
        "open_questions": open_questions,
        "debate_framing": framing,
        "discord_section": discord,
        "trace_appendix": trace_appendix,
        "warnings": _warnings(combined, topic),
        "errors": [],
        "no_workbook_or_queue_data_modified": True,
    }


def render_debate_packet(packet: dict[str, Any], *, style: str = "markdown", length: str = "medium") -> str:
    if packet["overall_status"] == "fail":
        return "\n".join(["Debate packet status: fail", *[f"- {error}" for error in packet["errors"]]])
    if style == "discord":
        return packet["discord_section"]

    selection = packet["selection"]
    lines = [
        f"# Debate Packet: {_packet_title(selection)}",
        "",
        f"- Generated: `{packet['generated_at']}`",
        f"- Hypothesis: `{selection.get('hypothesis') or 'None'}` {selection.get('hypothesis_name', '')}",
        f"- Topic: `{selection.get('topic') or 'None'}`",
        f"- Records considered: `{packet['counts']['records_considered']}`",
        "- Caveat: This summarizes approved records and does not tell you what to believe.",
        "- No workbook or queue data was modified.",
        "",
        "## Hypothesis / Topic Overview",
        packet["overview"],
        "",
        "## Position Snapshot",
        *_snapshot_lines(packet),
        "",
        "## Strongest Supporting Evidence",
        *_item_lines(packet["support_items"], length=length),
        "",
        "## Strongest Challenging Evidence",
        *_item_lines(packet["challenge_items"], length=length),
        "",
        "## Objections and Defeaters",
        *_item_lines(packet["objections"], length=length, include_why=True),
        "",
        "## Counter-Objections / Counter-Defeaters",
        *_item_lines(packet["counter_objections"], length=length, include_why=True),
        "",
        "## Criteria Matrix Highlights",
        *_criteria_lines(packet["criteria_highlights"]),
        "",
        "## Source Trace",
        *_source_lines(packet["source_trace"]),
        "",
        "## Open Questions / Uncertainty",
        *_question_lines(packet["open_questions"]),
        "",
        "## Debate Framing",
        *_framing_lines(packet["debate_framing"]),
        "",
        "## Discord Copy Section",
        packet["discord_section"],
        "",
        "## Trace Appendix",
        *_appendix_lines(packet["trace_appendix"]),
    ]
    if packet["warnings"]:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in packet["warnings"]]])
    return "\n".join(lines).rstrip()


def write_debate_packet_reports(
    packet: dict[str, Any],
    reports_dir: str | Path,
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    label = _filename_label(packet["selection"])
    markdown_path = reports_path / f"debate_packet_{label}_{stamp}.md"
    json_path = reports_path / f"debate_packet_{label}_{stamp}.json"
    markdown_path.write_text(render_debate_packet(packet, length="long"), encoding="utf-8")
    json_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _combine_items(summary: dict[str, Any], *, topic: str | None) -> list[dict[str, Any]]:
    seen = set()
    combined = []
    for hypothesis_summary in summary.get("hypotheses", []):
        for key in ["support_items", "challenge_items", "neutral_items", "defeaters", "counter_defeaters", "open_questions", "salient_items"]:
            for item in hypothesis_summary.get(key, []):
                if topic and not _matches_topic(item, topic):
                    continue
                identity = (item.get("proposal_id", ""), item.get("claim_id", ""), item.get("source_id", ""))
                if identity in seen:
                    continue
                seen.add(identity)
                combined.append(item)
    return combined


def _matches_topic(item: dict[str, Any], topic: str) -> bool:
    needle = topic.lower()
    haystack = " ".join(
        str(item.get(key, ""))
        for key in [
            "evidence_preview",
            "category",
            "source_book",
            "notes_preview",
            "source_title",
            "source_summary_preview",
            "claim_preview",
            "claim_context_preview",
        ]
    ).lower()
    return needle in haystack


def _snapshot_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(item.get("category", "") for item in items if item.get("category"))
    sources = Counter(item.get("source_id", "") for item in items if item.get("source_id"))
    return {
        "records_considered": len(items),
        "strong_support": sum(1 for item in items if item.get("classification") == "strong_support"),
        "moderate_support": sum(1 for item in items if item.get("classification") == "moderate_support"),
        "neutral_mixed": sum(1 for item in items if item.get("classification") == "neutral_mixed"),
        "moderate_challenge": sum(1 for item in items if item.get("classification") == "moderate_challenge"),
        "strong_challenge": sum(1 for item in items if item.get("classification") == "strong_challenge"),
        "top_categories": categories.most_common(5),
        "top_sources": sources.most_common(5),
    }


def _criteria_highlights(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    highlights = []
    for item in items:
        flags = item.get("salience_flags", [])
        if not flags:
            continue
        highlights.append(
            {
                "proposal_id": item.get("proposal_id", ""),
                "claim_id": item.get("claim_id", ""),
                "source_id": item.get("source_id", ""),
                "criteria_scores": item.get("criteria_scores", {}),
                "highlights": flags,
                "note": "Emotional and existential salience are not evidential weight.",
            }
        )
    return highlights


def _open_questions(items: list[dict[str, Any]], proposed_index: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    questions = []
    for item in items:
        note = item.get("open_question_note") or proposed_index.get(item.get("proposal_id", ""), {}).get("uncertainty_notes", "")
        if note:
            questions.append(
                {
                    "proposal_id": item.get("proposal_id", ""),
                    "claim_id": item.get("claim_id", ""),
                    "source_id": item.get("source_id", ""),
                    "note": note,
                }
            )
    return questions


def _source_trace(items: list[dict[str, Any]], source_index: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for source_id in sorted({item.get("source_id", "") for item in items if item.get("source_id")}):
        source = source_index.get(source_id, {})
        rows.append(
            {
                "source_id": source_id,
                "title": source.get("title", ""),
                "author_or_speaker": source.get("author_or_speaker", ""),
                "source_type": source.get("source_type", ""),
                "url": source.get("url", ""),
                "processing_status": source.get("processing_status", ""),
            }
        )
    return rows


def _trace_appendix(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "proposal_id": item.get("proposal_id", ""),
            "claim_id": item.get("claim_id", ""),
            "source_id": item.get("source_id", ""),
            "category": item.get("category", ""),
            "approved_weight_0_5": item.get("approved_weight_0_5", 0),
            "hypothesis_mi5_label": item.get("hypothesis_mi5_label", ""),
            "source_book": item.get("source_book", ""),
        }
        for item in items
    ]


def _debate_framing(
    hypothesis: str,
    topic: str,
    support: list[dict[str, Any]],
    challenge: list[dict[str, Any]],
    objections: list[dict[str, Any]],
    open_questions: list[dict[str, str]],
) -> dict[str, str]:
    title = hypothesis or f"topic '{topic}'"
    strongest = support[0]["evidence_preview"] if support else "The approved record has no strong support item yet."
    vulnerable = challenge[0]["evidence_preview"] if challenge else "No strong challenge is currently surfaced."
    question = open_questions[0]["note"] if open_questions else "Which approved record would most change the balance if clarified?"
    concession = "Acknowledge the best objection before pressing the strongest support." if objections else "Concede where the approved record is thin."
    return {
        "tactical_framing": f"For {title}, keep the argument traceable to approved records and name the best challenge directly.",
        "strongest_line": strongest,
        "most_vulnerable_point": vulnerable,
        "best_question_to_ask_next": question,
        "best_concession": concession,
    }


def _discord_section(
    hypothesis: str,
    topic: str,
    support: list[dict[str, Any]],
    challenge: list[dict[str, Any]],
    open_questions: list[dict[str, str]],
    framing: dict[str, str],
) -> str:
    title = hypothesis or f"Topic: {topic}"
    lines = [
        f"Debate packet: {title}",
        "",
        "Top support:",
        *_compact_items(support),
        "",
        "Top challenge:",
        *_compact_items(challenge),
        "",
        "Key uncertainty:",
        f"- {open_questions[0]['note']}" if open_questions else "- None surfaced.",
        "",
        "Discussion question:",
        f"- {framing['best_question_to_ask_next']}",
    ]
    return "\n".join(lines)


def _compact_items(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- [{item['proposal_id']} / {item['source_id']}] Weight {item['approved_weight_0_5']}, MI5: {item.get('hypothesis_mi5_label') or 'blank'} - {item['evidence_preview']}"
        for item in items[:3]
    ]


def _overview(hypothesis: str, topic: str, count: int) -> str:
    parts = []
    if hypothesis:
        parts.append(f"hypothesis {hypothesis} - {HYPOTHESIS_NAMES.get(hypothesis, hypothesis)}")
    if topic:
        parts.append(f"topic '{topic}'")
    return f"This packet covers {' and '.join(parts)} using {count} approved record(s)."


def _warnings(items: list[dict[str, Any]], topic: str | None) -> list[str]:
    warnings = []
    if not items:
        warnings.append("No approved rows matched the current selection and filters.")
    if topic and not items:
        warnings.append("The topic filter is a simple substring search, not semantic search.")
    return warnings


def _snapshot_lines(packet: dict[str, Any]) -> list[str]:
    counts = packet["counts"]
    return [
        f"- Strong support: {counts['strong_support']}",
        f"- Moderate support: {counts['moderate_support']}",
        f"- Neutral / mixed: {counts['neutral_mixed']}",
        f"- Moderate challenge: {counts['moderate_challenge']}",
        f"- Strong challenge: {counts['strong_challenge']}",
        f"- Top categories: {_pairs(counts['top_categories'])}",
        f"- Top sources: {_pairs(counts['top_sources'])}",
    ]


def _item_lines(items: list[dict[str, Any]], *, length: str, include_why: bool = False) -> list[str]:
    if not items:
        return ["- None"]
    lines = []
    for item in items:
        line = (
            f"- [{item['proposal_id']} / {item['claim_id']} / {item['source_id']}] "
            f"Weight {item['approved_weight_0_5']}, MI5: {item.get('hypothesis_mi5_label') or 'blank'} - "
            f"{item['evidence_preview']}"
        )
        extras = [value for value in [
            f"category: {item.get('category')}" if item.get("category") else "",
            f"source: {item.get('source_title')}" if item.get("source_title") else "",
            f"claim type: {item.get('claim_type')}" if item.get("claim_type") else "",
        ] if value]
        if length == "long":
            if item.get("claim_preview"):
                extras.append(f"claim: {item['claim_preview']}")
            if item.get("notes_preview"):
                extras.append(f"notes: {item['notes_preview']}")
            if item.get("criteria_scores"):
                extras.append(f"criteria: {item['criteria_scores']}")
        if include_why:
            extras.append("why it matters: this may need to be answered directly in debate")
        if extras:
            line += f" ({'; '.join(extras)})"
        lines.append(line)
    return lines


def _criteria_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- [{item['proposal_id']} / {item['claim_id']} / {item['source_id']}] {', '.join(item['highlights'])}; scores: {item['criteria_scores']}. {item['note']}"
        for item in items
    ]


def _source_lines(items: list[dict[str, str]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- [{item['source_id']}] {item.get('title', '')} | {item.get('author_or_speaker', '')} | {item.get('source_type', '')} | {item.get('url', '')} | {item.get('processing_status', '')}"
        for item in items
    ]


def _question_lines(items: list[dict[str, str]]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- [{item['proposal_id']} / {item['claim_id']} / {item['source_id']}] {item['note']}" for item in items]


def _framing_lines(framing: dict[str, str]) -> list[str]:
    return [
        f"- Tactical framing: {framing['tactical_framing']}",
        f"- Strongest line: {framing['strongest_line']}",
        f"- Most vulnerable point: {framing['most_vulnerable_point']}",
        f"- Best question to ask next: {framing['best_question_to_ask_next']}",
        f"- Best concession: {framing['best_concession']}",
    ]


def _appendix_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    return [
        f"- {item['proposal_id']} | {item['claim_id']} | {item['source_id']} | {item['category']} | weight {item['approved_weight_0_5']} | MI5 {item['hypothesis_mi5_label'] or 'blank'} | {item['source_book']}"
        for item in items
    ]


def _pairs(values: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in values) if values else "None"


def _float_from_scores(item: dict[str, Any], field: str) -> float:
    try:
        return float(item.get("criteria_scores", {}).get(field, 0) or 0)
    except ValueError:
        return 0.0


def _queue_dir(config: dict[str, Any], base_dir: str | Path) -> Path:
    queue_value = Path(config["queues"]["base_dir"])
    return queue_value if queue_value.is_absolute() else Path(base_dir) / queue_value


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _packet_title(selection: dict[str, str]) -> str:
    if selection.get("hypothesis") and selection.get("topic"):
        return f"{selection['hypothesis']} / {selection['topic']}"
    return selection.get("hypothesis") or selection.get("topic") or "Unknown"


def _filename_label(selection: dict[str, str]) -> str:
    if selection.get("hypothesis"):
        return selection["hypothesis"]
    topic = re.sub(r"[^A-Za-z0-9]+", "_", selection.get("topic", "")).strip("_")
    return f"TOPIC_{topic or 'UNKNOWN'}"


def _error_result(message: str) -> dict[str, Any]:
    return {
        "operation": "debate_packet",
        "generated_at": timestamp_iso(),
        "overall_status": "fail",
        "selection": {},
        "filters": {},
        "counts": {"records_considered": 0},
        "support_items": [],
        "challenge_items": [],
        "objections": [],
        "counter_objections": [],
        "criteria_highlights": [],
        "source_trace": [],
        "open_questions": [],
        "debate_framing": {},
        "discord_section": "",
        "trace_appendix": [],
        "warnings": [],
        "errors": [message],
        "no_workbook_or_queue_data_modified": True,
    }
