from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from belief_dashboard_agentflows.flows.export_preflight import run_export_preflight
from belief_dashboard_agentflows.flows.extraction_qa import run_extraction_qa
from belief_dashboard_agentflows.flows.proposal_review_assistant import build_proposal_review_cards
from belief_dashboard_agentflows.git_policy import (
    assert_clean_worktree_at_start,
    assert_not_main_branch,
    assert_paths_allowed,
    changed_paths_from_porcelain,
    git_status_porcelain,
)
from belief_dashboard_agentflows.reports.markdown import render_markdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="belief-dashboard-agentflows")
    subparsers = parser.add_subparsers(dest="command", required=True)

    qa_parser = subparsers.add_parser("extraction-qa", help="Run guarded QA for one source import batch.")
    _add_common_args(qa_parser)
    qa_parser.add_argument("--source-id", required=True)

    review_parser = subparsers.add_parser("proposal-review-assistant", help="Generate proposal review cards.")
    _add_common_args(review_parser)
    review_parser.add_argument("--source-id")
    review_parser.add_argument("--proposal-id")
    review_parser.add_argument("--status", default="proposed")
    review_parser.add_argument("--limit", type=int)

    preflight_parser = subparsers.add_parser("export-preflight", help="Run read-only export readiness checks.")
    _add_common_args(preflight_parser)
    preflight_parser.add_argument("--output-workbook")

    args = parser.parse_args(argv)
    try:
        if args.auto_commit:
            assert_clean_worktree_at_start(args.repo_dir)
            assert_not_main_branch(args.repo_dir)
        _reject_unimplemented_confirmations(args)

        if args.command == "extraction-qa":
            report = run_extraction_qa(
                args.source_id,
                project_dir=args.project_dir,
                config_path=args.config,
                output_format=args.format,
                save=args.save or args.auto_commit,
            )
        elif args.command == "proposal-review-assistant":
            report = build_proposal_review_cards(
                project_dir=args.project_dir,
                config_path=args.config,
                source_id=args.source_id,
                proposal_id=args.proposal_id,
                status=args.status,
                limit=args.limit,
                save=args.save or args.auto_commit,
            )
        else:
            report = run_export_preflight(
                project_dir=args.project_dir,
                config_path=args.config,
                output_workbook=args.output_workbook,
                save=args.save or args.auto_commit,
            )

        if args.auto_commit:
            _auto_commit(args.repo_dir, report, args.command, args.source_id if hasattr(args, "source_id") else "")

        print(_render_report(report, args.format))
        return 0 if report.get("status") in {"pass", "ready"} else 1
    except PermissionError as exc:
        print(f"Permission denied: {exc}")
        return 2
    except Exception as exc:
        print(f"Agentflow failed: {exc}")
        return 1


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-dir", default=".", help="Project directory containing config.yaml.")
    parser.add_argument("--repo-dir", default=".", help="Git repository root for optional auto-commit checks.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml relative to project-dir.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/agentflows.")
    parser.add_argument("--auto-commit", action="store_true", help="Commit generated agentflow artifacts after safety checks.")
    parser.add_argument(
        "--confirm-guarded-write",
        action="store_true",
        help="Reserved confirmation flag for future guarded write execution. MVP flows remain report-only.",
    )
    parser.add_argument(
        "--confirm-push",
        action="store_true",
        help="Reserved confirmation flag for future push/PR execution. MVP flows never push.",
    )
    parser.add_argument(
        "--confirm-promotion",
        action="store_true",
        help="Reserved confirmation flag for future promotion/rollback execution. MVP flows never promote or roll back.",
    )


def _render_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2)
    return render_markdown(report)


def _auto_commit(repo_dir: str | Path, report: dict[str, Any], flow_name: str, source_id: str = "") -> None:
    status_lines = git_status_porcelain(repo_dir)
    changed_paths = changed_paths_from_porcelain(status_lines)
    allowed = ("belief-dashboard-tool/reports/", "belief-dashboard-tool/data/manual_imports/")
    assert_paths_allowed(changed_paths, allowed)
    if report.get("status") not in {"pass", "ready"}:
        raise PermissionError("Auto-commit requires a successful agentflow report.")
    message_bits = [f"agentflow: {flow_name}"]
    if source_id:
        message_bits.append(source_id)
    subprocess.run(["git", "add", *changed_paths], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", " ".join(message_bits)], cwd=repo_dir, check=True)


def _reject_unimplemented_confirmations(args: argparse.Namespace) -> None:
    if args.confirm_guarded_write:
        raise PermissionError("MVP agentflows are report-only and do not execute guarded writes.")
    if args.confirm_push:
        raise PermissionError("MVP agentflows do not push branches or open pull requests.")
    if args.confirm_promotion:
        raise PermissionError("MVP agentflows do not promote or roll back workbooks.")


if __name__ == "__main__":
    raise SystemExit(main())
