from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from belief_dashboard_agentflows.flows.cluster_extraction_batch import (
    render_cluster_batch_markdown,
    run_cluster_extraction_batch,
)
from belief_dashboard_agentflows.flows.corpus_backlog import (
    render_corpus_backlog_markdown,
    run_corpus_backlog,
)
from belief_dashboard_agentflows.flows.drive_corpus_inventory import (
    render_drive_corpus_inventory_markdown,
    run_drive_corpus_inventory,
)
from belief_dashboard_agentflows.flows.export_preflight import run_export_preflight
from belief_dashboard_agentflows.flows.extraction_qa import run_extraction_qa
from belief_dashboard_agentflows.flows.packet_batch_draft import (
    render_packet_batch_draft_markdown,
    run_packet_batch_draft,
)
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
    qa_parser.add_argument("--extracted-claims-file")
    qa_parser.add_argument("--criteria-matrix-file")
    qa_parser.add_argument("--proposed-updates-file")

    packet_batch_parser = subparsers.add_parser("packet-batch-draft", help="Draft guarded manual-import CSVs for one selected source packet batch.")
    _add_common_args(packet_batch_parser)
    packet_batch_parser.add_argument("--source-id", required=True)
    packet_batch_parser.add_argument("--batch-name", default="")
    packet_batch_parser.add_argument("--packet-id", action="append", default=[])
    packet_batch_parser.add_argument("--packet-cycle-group")
    packet_batch_parser.add_argument("--overwrite", action="store_true")

    review_parser = subparsers.add_parser("proposal-review-assistant", help="Generate proposal review cards.")
    _add_common_args(review_parser)
    review_parser.add_argument("--source-id")
    review_parser.add_argument("--proposal-id")
    review_parser.add_argument("--status", default="proposed")
    review_parser.add_argument("--limit", type=int)

    preflight_parser = subparsers.add_parser("export-preflight", help="Run read-only export readiness checks.")
    _add_common_args(preflight_parser)
    preflight_parser.add_argument("--output-workbook")

    cluster_parser = subparsers.add_parser("cluster-extraction-batch", help="Run a guarded extraction batch controller for an evidence cluster.")
    _add_common_args(cluster_parser)
    cluster_parser.add_argument("--cluster-id", required=True)
    cluster_parser.add_argument("--source-id", action="append", default=[])
    cluster_parser.add_argument("--limit", type=int)
    cluster_parser.add_argument("--mode", choices=["prepare", "qa", "dry-run", "report"], default="report")
    cluster_parser.add_argument("--force-workspace", action="store_true")
    cluster_parser.add_argument("--include-already-imported", action="store_true")

    corpus_parser = subparsers.add_parser("corpus-backlog-runner", help="Run a guarded background-safe corpus backlog report.")
    _add_common_args(corpus_parser)
    corpus_parser.add_argument("--corpus", action="append", default=[], help="Corpus to include. Repeatable. Use all for all supported corpora.")
    corpus_parser.add_argument("--exclude-corpus", action="append", default=[], help="Corpus to exclude from the report.")
    corpus_parser.add_argument("--mode", choices=["inventory", "plan", "report"], default="inventory")
    corpus_parser.add_argument("--background-safe", action="store_true", help="Required safety acknowledgement for backlog reporting.")

    drive_parser = subparsers.add_parser("drive-corpus-inventory", help="Inventory a Google Drive corpus folder without downloading raw files.")
    _add_common_args(drive_parser)
    drive_group = drive_parser.add_mutually_exclusive_group(required=True)
    drive_group.add_argument("--drive-folder-id")
    drive_group.add_argument("--drive-folder-url")
    drive_parser.add_argument("--corpus", required=True)
    drive_parser.add_argument("--background-safe", action="store_true", help="Required safety acknowledgement for Drive inventory.")
    drive_parser.add_argument("--max-depth", type=int, default=10)
    drive_parser.add_argument("--max-items", type=int, default=5000)
    drive_parser.add_argument("--include-trashed", action="store_true")
    drive_parser.add_argument("--output-root", default="reports/agentflow_runs/drive_inventory")
    drive_parser.add_argument("--manifest-path")
    drive_parser.add_argument("--overwrite", action="store_true")
    drive_parser.add_argument("--json-only", action="store_true")
    drive_parser.add_argument("--markdown-only", action="store_true")

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
                extracted_claims_file=args.extracted_claims_file,
                criteria_matrix_file=args.criteria_matrix_file,
                proposed_updates_file=args.proposed_updates_file,
            )
        elif args.command == "packet-batch-draft":
            report = run_packet_batch_draft(
                source_id=args.source_id,
                batch_name=args.batch_name,
                packet_ids=args.packet_id,
                packet_cycle_group=args.packet_cycle_group,
                overwrite=args.overwrite,
                project_dir=args.project_dir,
                config_path=args.config,
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
        elif args.command == "export-preflight":
            report = run_export_preflight(
                project_dir=args.project_dir,
                config_path=args.config,
                output_workbook=args.output_workbook,
                save=args.save or args.auto_commit,
            )
        elif args.command == "cluster-extraction-batch":
            report = run_cluster_extraction_batch(
                cluster_id=args.cluster_id,
                project_dir=args.project_dir,
                config_path=args.config,
                source_ids=args.source_id,
                limit=args.limit,
                mode=args.mode,
                force_workspace=args.force_workspace,
                include_already_imported=args.include_already_imported,
                save=True,
            )
        elif args.command == "corpus-backlog-runner":
            report = run_corpus_backlog(
                corpora=args.corpus,
                mode=args.mode,
                background_safe=args.background_safe,
                exclude_corpora=args.exclude_corpus,
                project_dir=args.project_dir,
            )
        else:
            report = run_drive_corpus_inventory(
                drive_folder_id=args.drive_folder_id,
                drive_folder_url=args.drive_folder_url,
                corpus=args.corpus,
                background_safe=args.background_safe,
                max_depth=args.max_depth,
                max_items=args.max_items,
                include_trashed=args.include_trashed,
                output_root=args.output_root,
                manifest_path=args.manifest_path,
                overwrite=args.overwrite,
                json_only=args.json_only,
                markdown_only=args.markdown_only,
                project_dir=args.project_dir,
            )

        if args.auto_commit:
            source_label = ""
            if hasattr(args, "source_id"):
                source_label = ",".join(args.source_id) if isinstance(args.source_id, list) else args.source_id
            _auto_commit(args.repo_dir, report, args.command, source_label)

        print(_render_report(report, args.format))
        return 0 if report.get("status") in {"pass", "passed", "ready", "in_progress"} else 1
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
    if report.get("flow") == "corpus-backlog-runner":
        return render_corpus_backlog_markdown(report)
    if report.get("flow") == "cluster-extraction-batch":
        return render_cluster_batch_markdown(report)
    if report.get("flow") == "packet-batch-draft":
        return render_packet_batch_draft_markdown(report)
    if report.get("flow") == "drive-corpus-inventory":
        return render_drive_corpus_inventory_markdown(report)
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
