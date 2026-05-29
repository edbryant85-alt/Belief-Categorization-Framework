from __future__ import annotations

from pathlib import Path
from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('title', 'Agentflow Report')}",
        "",
        f"- Flow: `{report.get('flow', '')}`",
        f"- Status: `{report.get('status', '')}`",
    ]
    if report.get("source_id"):
        lines.append(f"- Source ID: `{report['source_id']}`")
    lines.extend(["", "## Blockers", *_bullets(report.get("blockers", []))])
    lines.extend(["", "## Warnings", *_bullets(report.get("warnings", []))])
    lines.extend(["", "## Recommended Next Command", report.get("recommended_next_command") or "None"])
    if report.get("cards"):
        lines.extend(["", "## Review Cards"])
        for card in report["cards"]:
            lines.extend(["", f"### {card.get('proposal_id', 'Proposal')}", ""])
            lines.extend(_card_lines(card))
    if report.get("summaries"):
        lines.extend(["", "## Summaries"])
        for summary in report["summaries"]:
            lines.append(f"- {summary}")
    if report.get("commands_run"):
        lines.extend(["", "## Commands Run"])
        for command in report["commands_run"]:
            lines.append(f"- `{command.get('command', '')}` -> `{command.get('return_code', '')}`")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown_report(path: str | Path, report: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    return output


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _card_lines(card: dict[str, Any]) -> list[str]:
    lines = [
        f"- Claim: {card.get('claim_text', '')}",
        f"- Proposed evidence: {card.get('evidence_argument', '')}",
        f"- Criteria summary: {card.get('criteria_summary', '')}",
        f"- Hypothesis impact: {card.get('hypothesis_impact', '')}",
        f"- Suggested action: `{card.get('suggested_action', '')}`",
    ]
    risks = card.get("risk_flags") or []
    lines.append(f"- Risk flags: {', '.join(risks) if risks else 'None'}")
    return lines
