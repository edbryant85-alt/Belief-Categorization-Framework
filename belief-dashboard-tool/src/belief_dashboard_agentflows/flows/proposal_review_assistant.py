from __future__ import annotations

from pathlib import Path
from typing import Any

from belief_dashboard.utils import timestamp_for_filename
from belief_dashboard_agentflows.config_reader import read_config
from belief_dashboard_agentflows.queue_reader import read_queue, reports_dir, row_by_id
from belief_dashboard_agentflows.reports.json import write_json_report
from belief_dashboard_agentflows.reports.markdown import write_markdown_report
from belief_dashboard_agentflows.schema_reader import criteria_score_fields, mi5_columns


def build_proposal_review_cards(
    *,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    source_id: str | None = None,
    proposal_id: str | None = None,
    status: str = "proposed",
    limit: int | None = None,
    save: bool = False,
) -> dict[str, Any]:
    config = read_config(project_dir, config_path)
    proposals = read_queue(project_dir, config, "proposed_updates")
    claims = row_by_id(read_queue(project_dir, config, "extracted_claims"), "claim_id")
    criteria = row_by_id(read_queue(project_dir, config, "criteria_matrix"), "claim_id")
    sources = row_by_id(read_queue(project_dir, config, "source_dossiers"), "source_id")

    filtered = []
    for row in proposals:
        if source_id and row.get("source_id") != source_id:
            continue
        if proposal_id and row.get("proposal_id") != proposal_id:
            continue
        if status and row.get("review_status") != status:
            continue
        filtered.append(row)
    if limit is not None:
        filtered = filtered[:limit]

    cards = [_build_card(row, claims, criteria, sources) for row in filtered]
    blockers = []
    warnings = []
    for card in cards:
        warnings.extend(f"{card['proposal_id']}: {flag}" for flag in card["risk_flags"])
    report = {
        "title": "Proposal Review Assistant Report",
        "flow": "proposal-review-assistant",
        "source_id": source_id or "",
        "status": "pass",
        "blockers": blockers,
        "warnings": warnings,
        "recommended_next_command": "Use approve-proposal, reject-proposal, or defer-proposal only after human review.",
        "cards": cards,
        "summaries": [f"{len(cards)} proposal review card(s) generated."],
        "commands_run": [],
    }
    if save:
        _write_reports(project_dir, source_id or "ALL", report)
    return report


def _build_card(
    proposal: dict[str, str],
    claims: dict[str, dict[str, str]],
    criteria: dict[str, dict[str, str]],
    sources: dict[str, dict[str, str]],
) -> dict[str, Any]:
    claim = claims.get(proposal.get("claim_id", ""), {})
    criterion = criteria.get(proposal.get("claim_id", ""), {})
    source = sources.get(proposal.get("source_id", ""), {})
    risk_flags = _risk_flags(proposal, claim, criterion)
    return {
        "proposal_id": proposal.get("proposal_id", ""),
        "source_id": proposal.get("source_id", ""),
        "source_title": source.get("title", ""),
        "claim_id": proposal.get("claim_id", ""),
        "claim_text": claim.get("claim_text", ""),
        "evidence_argument": proposal.get("evidence_argument", ""),
        "criteria_summary": _criteria_summary(criterion),
        "hypothesis_impact": _hypothesis_impact(proposal),
        "risk_flags": risk_flags,
        "suggested_action": _suggest_action(risk_flags, proposal, criterion),
    }


def _criteria_summary(row: dict[str, str]) -> str:
    if not row:
        return "No criteria row found."
    selected = []
    for field in criteria_score_fields():
        value = row.get(field, "")
        if value:
            selected.append(f"{field}={value}")
    return "; ".join(selected[:6]) or "Criteria row has no scores."


def _hypothesis_impact(row: dict[str, str]) -> str:
    impacts = [f"{column.replace('_MI5', '')}: {row[column]}" for column in mi5_columns() if row.get(column)]
    return "; ".join(impacts) or "No MI5 impact labels supplied."


def _risk_flags(proposal: dict[str, str], claim: dict[str, str], criterion: dict[str, str]) -> list[str]:
    flags: list[str] = []
    if not claim:
        flags.append("supporting claim not found")
    if not criterion:
        flags.append("criteria row not found")
    if not proposal.get("suggestion_rationale", "").strip():
        flags.append("missing suggestion rationale")
    if not proposal.get("uncertainty_notes", "").strip():
        flags.append("missing uncertainty notes")
    if proposal.get("suggested_weight_0_5") in {"4", "5"} and criterion.get("reliability_0_5") in {"", "0", "1", "2"}:
        flags.append("high suggested weight with low or missing reliability")
    if claim and proposal.get("evidence_argument", "").strip() and claim.get("claim_text", "").strip():
        if len(proposal["evidence_argument"]) > len(claim["claim_text"]) * 3:
            flags.append("proposal may over-expand the source claim")
    return flags


def _suggest_action(risk_flags: list[str], proposal: dict[str, str], criterion: dict[str, str]) -> str:
    severe = {"supporting claim not found", "criteria row not found"}
    if any(flag in severe for flag in risk_flags):
        return "defer"
    if len(risk_flags) >= 3:
        return "defer"
    if proposal.get("suggested_weight_0_5") in {"0", "1"}:
        return "reject"
    if criterion.get("relevance_0_5") in {"", "0", "1"}:
        return "defer"
    return "approve"


def _write_reports(project_dir: str | Path, source_id: str, report: dict[str, Any]) -> None:
    base = reports_dir(project_dir) / "proposal_review_assistant"
    stamp = timestamp_for_filename()
    write_markdown_report(base / f"proposal_review_assistant_{source_id}_{stamp}.md", report)
    write_json_report(base / f"proposal_review_assistant_{source_id}_{stamp}.json", report)
