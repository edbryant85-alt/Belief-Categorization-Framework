from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from belief_dashboard.artifacts import (
    UnknownArtifactTypeError,
    find_reports,
    find_verified_outputs,
    latest_artifact,
    list_artifact_categories,
    render_summary,
    render_table,
    show_artifact,
    write_artifact_navigation_report,
)
from belief_dashboard.claims import create_claim_template
from belief_dashboard.command_guides import (
    compose_promote_command,
    compose_rollback_command,
    next_safe_commands,
    render_command_guide,
    write_command_guide_report,
)
from belief_dashboard.config import load_config
from belief_dashboard.dossiers import DuplicateSourceError, QueueSetupError, register_source
from belief_dashboard.export_verification import (
    latest_output_workbook,
    verify_workbook_export,
    write_export_verification_reports,
)
from belief_dashboard.export_preview import preview_workbook_export, write_export_preview_artifacts
from belief_dashboard.history import (
    current_workbook_status,
    export_history,
    list_promoted_archives,
    promotion_history,
    render_current_status_markdown,
    render_history_table,
    verification_history,
    write_current_status_report,
    write_history_reports,
)
from belief_dashboard.manual_imports import (
    append_manual_import,
    queue_summary,
    validate_manual_import,
    write_manual_import_report,
    write_queue_summary,
)
from belief_dashboard.operator_preflight import (
    PREFLIGHT_MODES,
    build_operator_preflight,
    render_operator_preflight,
    write_operator_preflight_reports,
)
from belief_dashboard.product_readiness import (
    build_product_readiness,
    render_product_readiness,
    write_product_readiness_reports,
)
from belief_dashboard.prompts import generate_prompt_packet
from belief_dashboard.queues import init_queues, validate_queues, write_queue_validation_reports
from belief_dashboard.reviews import (
    list_proposals,
    render_proposals_table,
    review_proposal,
    write_review_report,
)
from belief_dashboard.sources import SourceRegistrationError
from belief_dashboard.utils import resolve_project_path
from belief_dashboard.workbook import inspect_workbook, write_reports
from belief_dashboard.workbook_export import apply_approved_to_workbook, write_workbook_export_report
from belief_dashboard.workbook_promotion import promote_output_workbook, write_workbook_promotion_reports
from belief_dashboard.workbook_recovery import rollback_workbook, write_workbook_rollback_reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="belief-dashboard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-workbook",
        help="Inspect the configured Excel workbook without modifying it.",
    )
    inspect_parser.add_argument(
        "--workbook",
        help="Optional path to an .xlsx workbook. Defaults to workbook.default_path in config.yaml.",
    )
    inspect_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    init_parser = subparsers.add_parser(
        "init-queues",
        help="Create missing queue CSV templates and reflection journal.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing queue template files intentionally.",
    )
    init_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    validate_parser = subparsers.add_parser(
        "validate-queues",
        help="Validate queue CSV templates and values.",
    )
    validate_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    register_parser = subparsers.add_parser(
        "register-source",
        help="Register a raw source file in source_dossiers.csv.",
    )
    register_parser.add_argument("--file", required=True, help="Path to the raw source file.")
    register_parser.add_argument("--source-type", default="", help="Optional source type, such as book_notes.")
    register_parser.add_argument("--title", default="", help="Optional source title.")
    register_parser.add_argument("--author", default="", help="Optional author or speaker.")
    register_parser.add_argument("--url", default="", help="Optional source URL.")
    register_parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Allow another dossier row for the same original file path.",
    )
    register_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    claim_template_parser = subparsers.add_parser(
        "create-claim-template",
        help="Create a source-specific extracted_claims CSV template.",
    )
    claim_template_parser.add_argument("--source-id", required=True, help="Source ID, such as SRC0001.")
    claim_template_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    prompt_parser = subparsers.add_parser(
        "generate-prompt-packet",
        help="Create a markdown prompt packet for manual ChatGPT analysis.",
    )
    prompt_parser.add_argument("--source-id", required=True, help="Source ID, such as SRC0001.")
    prompt_parser.add_argument(
        "--max-characters",
        type=int,
        help="Maximum source characters to include inline. Defaults to prompt_packets.max_inline_characters.",
    )
    prompt_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    validate_import_parser = subparsers.add_parser(
        "validate-import",
        help="Validate a reviewed manual import CSV before appending it to queues.",
    )
    validate_import_parser.add_argument("--type", required=True, help="Import type, such as extracted_claims.")
    validate_import_parser.add_argument("--file", required=True, help="Path to the manual import CSV.")
    validate_import_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    append_import_parser = subparsers.add_parser(
        "append-import",
        help="Validate and append a reviewed manual import CSV to its target queue.",
    )
    append_import_parser.add_argument("--type", required=True, help="Import type, such as extracted_claims.")
    append_import_parser.add_argument("--file", required=True, help="Path to the manual import CSV.")
    append_import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report what would append without changing queue files.",
    )
    append_import_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    summary_parser = subparsers.add_parser(
        "queue-summary",
        help="Print a simple summary of queue row counts.",
    )
    summary_parser.add_argument(
        "--save",
        action="store_true",
        help="Also save a markdown summary under reports/manual_imports.",
    )
    summary_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    approve_parser = subparsers.add_parser(
        "approve-proposal",
        help="Approve one proposed update and append it to approved_updates.csv.",
    )
    _add_review_common_args(approve_parser)
    approve_parser.add_argument("--weight", help="Optional approved weight override from 0 to 5.")
    approve_parser.add_argument("--category", help="Optional category override.")
    for hypothesis in ["ec", "pc", "pt", "ct", "mt", "is", "ms", "hc", "n"]:
        approve_parser.add_argument(f"--{hypothesis}-mi5", dest=f"{hypothesis}_mi5")

    reject_parser = subparsers.add_parser(
        "reject-proposal",
        help="Reject one proposed update and append it to rejected_updates.csv.",
    )
    _add_review_common_args(reject_parser)
    reject_parser.add_argument("--reason", required=True, help="Reason for rejection.")

    defer_parser = subparsers.add_parser(
        "defer-proposal",
        help="Defer one proposed update and append it to deferred_updates.csv.",
    )
    _add_review_common_args(defer_parser)
    defer_parser.add_argument("--reason", required=True, help="Reason for deferral.")
    defer_parser.add_argument("--revisit-date", default="", help="Optional revisit date in YYYY-MM-DD format.")

    list_parser = subparsers.add_parser(
        "list-proposals",
        help="List proposed updates with optional filters.",
    )
    list_parser.add_argument("--status", help="Filter by review_status.")
    list_parser.add_argument("--source-id", help="Filter by source ID.")
    list_parser.add_argument("--limit", type=int, help="Maximum number of proposals to show.")
    list_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    export_preview_parser = subparsers.add_parser(
        "preview-workbook-export",
        help="Preview approved queue rows against the workbook without writing Excel.",
    )
    export_preview_parser.add_argument("--workbook", help="Optional workbook path. Defaults to workbook.default_path.")
    export_preview_parser.add_argument("--approved-file", help="Optional approved_updates.csv path.")
    export_preview_parser.add_argument("--limit", type=int, help="Maximum approved rows to consider.")
    export_preview_parser.add_argument("--proposal-id", help="Filter to one proposal ID.")
    export_preview_parser.add_argument("--source-id", help="Filter to one source ID.")
    export_preview_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    apply_export_parser = subparsers.add_parser(
        "apply-approved-to-workbook",
        help="Apply approved updates to a timestamped workbook copy.",
    )
    apply_export_parser.add_argument("--workbook", help="Optional workbook path. Defaults to workbook.default_path.")
    apply_export_parser.add_argument("--approved-file", help="Optional approved_updates.csv path.")
    apply_export_parser.add_argument("--limit", type=int, help="Maximum approved rows to export.")
    apply_export_parser.add_argument("--proposal-id", help="Filter to one proposal ID.")
    apply_export_parser.add_argument("--source-id", help="Filter to one source ID.")
    apply_export_parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing workbook files.")
    apply_export_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    verify_export_parser = subparsers.add_parser(
        "verify-workbook-export",
        help="Verify a timestamped output workbook against approved updates.",
    )
    verify_export_parser.add_argument("--workbook", required=True, help="Path to the output workbook to verify.")
    verify_export_parser.add_argument("--export-report", help="Optional workbook export JSON report.")
    verify_export_parser.add_argument("--approved-file", help="Optional approved_updates.csv path.")
    verify_export_parser.add_argument("--proposal-id", help="Filter to one proposal ID.")
    verify_export_parser.add_argument("--source-id", help="Filter to one source ID.")
    verify_export_parser.add_argument("--mark-exported", action="store_true", help="Mark approved rows exported if verification succeeds.")
    verify_export_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    latest_output_parser = subparsers.add_parser(
        "latest-output-workbook",
        help="Print the most recently modified .xlsx file under data/outputs.",
    )
    latest_output_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    promote_parser = subparsers.add_parser(
        "promote-output-workbook",
        help="Promote a verified output workbook into the main workbook location.",
    )
    promote_parser.add_argument("--workbook", required=True, help="Path to the verified output workbook.")
    promote_parser.add_argument("--verification-report", required=True, help="Path to the successful verification JSON report.")
    promote_parser.add_argument("--main-workbook", help="Optional main workbook path. Defaults to workbook_promotion.main_workbook_path.")
    promote_parser.add_argument("--dry-run", action="store_true", help="Run safety checks without writing files.")
    promote_parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )

    status_parser = subparsers.add_parser(
        "current-workbook-status",
        help="Print current workbook status and latest operational artifacts.",
    )
    status_parser.add_argument("--save", action="store_true", help="Save a markdown status report under reports/workbook_recovery.")
    status_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    promotion_history_parser = subparsers.add_parser("promotion-history", help="Summarize workbook promotion history.")
    promotion_history_parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print. Defaults to 10.")
    promotion_history_parser.add_argument("--save", action="store_true", help="Save markdown and JSON history reports.")
    promotion_history_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    export_history_parser = subparsers.add_parser("export-history", help="Summarize workbook export history.")
    export_history_parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print. Defaults to 10.")
    export_history_parser.add_argument("--save", action="store_true", help="Save markdown and JSON history reports.")
    export_history_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    verification_history_parser = subparsers.add_parser("verification-history", help="Summarize export verification history.")
    verification_history_parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print. Defaults to 10.")
    verification_history_parser.add_argument("--save", action="store_true", help="Save markdown and JSON history reports.")
    verification_history_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    archives_parser = subparsers.add_parser("list-promoted-archives", help="List promoted archive workbooks.")
    archives_parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print. Defaults to 10.")
    archives_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    rollback_parser = subparsers.add_parser(
        "rollback-workbook",
        help="Restore a selected promoted archive to the main workbook path.",
    )
    rollback_parser.add_argument("--archive", required=True, help="Path to the promoted archive workbook to restore.")
    rollback_parser.add_argument("--main-workbook", help="Optional main workbook path. Defaults to workbook_recovery.main_workbook_path.")
    rollback_parser.add_argument("--dry-run", action="store_true", help="Run rollback checks without writing files.")
    rollback_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    artifacts_parser = subparsers.add_parser("list-artifacts", help="List known project artifact categories.")
    artifacts_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    artifacts_parser.add_argument("--save", action="store_true", help="Also save markdown and JSON reports under reports/artifact_navigation.")
    artifacts_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    latest_artifact_parser = subparsers.add_parser("latest-artifact", help="Show the latest artifact for a type.")
    latest_artifact_parser.add_argument("--type", required=True, help="Artifact type, such as export_verification or output_workbooks.")
    latest_artifact_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    latest_artifact_parser.add_argument("--save", action="store_true", help="Also save markdown and JSON reports under reports/artifact_navigation.")
    latest_artifact_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    show_artifact_parser = subparsers.add_parser("show-artifact", help="Show a concise summary of a report or workbook artifact.")
    show_artifact_parser.add_argument("--path", required=True, help="Path to the artifact to summarize.")
    show_artifact_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    show_artifact_parser.add_argument("--save", action="store_true", help="Also save markdown and JSON reports under reports/artifact_navigation.")
    show_artifact_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    find_report_parser = subparsers.add_parser("find-report", help="Find matching report artifacts.")
    find_report_parser.add_argument("--type", required=True, help="Report artifact type, such as export_verification.")
    find_report_parser.add_argument("--status", choices=["pass", "warning", "fail"], help="Filter JSON reports by status.")
    find_report_parser.add_argument("--contains", help="Filter reports by raw text containment.")
    find_report_parser.add_argument("--source-id", help="Filter reports containing this source ID.")
    find_report_parser.add_argument("--proposal-id", help="Filter reports containing this proposal ID.")
    find_report_parser.add_argument("--limit", type=int, help="Maximum rows to print.")
    find_report_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    find_report_parser.add_argument("--save", action="store_true", help="Also save markdown and JSON reports under reports/artifact_navigation.")
    find_report_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    verified_output_parser = subparsers.add_parser("find-verified-output", help="List output workbooks with verification reports.")
    verified_output_parser.add_argument("--status", choices=["pass", "warning", "fail"], default="pass", help="Verification status to match. Defaults to pass.")
    verified_output_parser.add_argument("--latest", action="store_true", help="Return only the latest matching verified output.")
    verified_output_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    verified_output_parser.add_argument("--save", action="store_true", help="Also save markdown and JSON reports under reports/artifact_navigation.")
    verified_output_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    compose_promote_parser = subparsers.add_parser("compose-promote-command", help="Print ready-to-run promotion commands without executing them.")
    compose_promote_parser.add_argument("--latest", action="store_true", help="Use the latest passing verified output workbook.")
    compose_promote_parser.add_argument("--workbook", help="Path to the output workbook to promote.")
    compose_promote_parser.add_argument("--verification-report", help="Path to the matching verification JSON report.")
    compose_promote_parser.add_argument("--include-dry-run", dest="include_dry_run", action="store_true", default=None, help="Include a dry-run command first.")
    compose_promote_parser.add_argument("--no-dry-run", dest="include_dry_run", action="store_false", help="Only print the real command.")
    compose_promote_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    compose_promote_parser.add_argument("--save", action="store_true", help="Save markdown and JSON guide reports under reports/command_guides.")
    compose_promote_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    compose_rollback_parser = subparsers.add_parser("compose-rollback-command", help="Print ready-to-run rollback commands without executing them.")
    compose_rollback_parser.add_argument("--latest", action="store_true", help="Use the latest promoted archive workbook.")
    compose_rollback_parser.add_argument("--archive", help="Path to the promoted archive workbook.")
    compose_rollback_parser.add_argument("--include-dry-run", dest="include_dry_run", action="store_true", default=None, help="Include a dry-run command first.")
    compose_rollback_parser.add_argument("--no-dry-run", dest="include_dry_run", action="store_false", help="Only print the real command.")
    compose_rollback_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    compose_rollback_parser.add_argument("--save", action="store_true", help="Save markdown and JSON guide reports under reports/command_guides.")
    compose_rollback_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    next_safe_parser = subparsers.add_parser("next-safe-commands", help="Print a conservative next-step command checklist.")
    next_safe_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    next_safe_parser.add_argument("--save", action="store_true", help="Save markdown and JSON guide reports under reports/command_guides.")
    next_safe_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    preflight_parser = subparsers.add_parser("operator-preflight", help="Gather a read-only operator preflight packet.")
    preflight_parser.add_argument("--mode", choices=sorted(PREFLIGHT_MODES), help="Preflight mode. Defaults to operator_preflight.default_mode.")
    preflight_parser.add_argument("--workbook", help="Optional main workbook path to inspect.")
    preflight_parser.add_argument("--output-workbook", help="Optional output workbook path for verification preflight.")
    preflight_parser.add_argument("--verification-report", help="Optional verification report path for promotion preflight.")
    preflight_parser.add_argument("--archive", help="Optional promoted archive path for rollback preflight.")
    preflight_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    preflight_parser.add_argument("--save", action="store_true", help="Save markdown and JSON preflight reports under reports/operator_preflight.")
    preflight_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    product_readiness_parser = subparsers.add_parser("product-readiness", help="Run a project product readiness diagnostic.")
    product_readiness_parser.add_argument("--sample-demo-dir", help="Optional path to the sample demo asset directory.")
    product_readiness_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    product_readiness_parser.add_argument("--save", action="store_true", help="Save markdown and JSON product readiness reports under reports/product_readiness.")
    product_readiness_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    args = parser.parse_args(argv)

    if args.command == "inspect-workbook":
        return _inspect_workbook_command(args)
    if args.command == "init-queues":
        return _init_queues_command(args)
    if args.command == "validate-queues":
        return _validate_queues_command(args)
    if args.command == "register-source":
        return _register_source_command(args)
    if args.command == "create-claim-template":
        return _create_claim_template_command(args)
    if args.command == "generate-prompt-packet":
        return _generate_prompt_packet_command(args)
    if args.command == "validate-import":
        return _validate_import_command(args)
    if args.command == "append-import":
        return _append_import_command(args)
    if args.command == "queue-summary":
        return _queue_summary_command(args)
    if args.command == "approve-proposal":
        return _review_proposal_command(args, "approved")
    if args.command == "reject-proposal":
        return _review_proposal_command(args, "rejected")
    if args.command == "defer-proposal":
        return _review_proposal_command(args, "deferred")
    if args.command == "list-proposals":
        return _list_proposals_command(args)
    if args.command == "preview-workbook-export":
        return _preview_workbook_export_command(args)
    if args.command == "apply-approved-to-workbook":
        return _apply_approved_to_workbook_command(args)
    if args.command == "verify-workbook-export":
        return _verify_workbook_export_command(args)
    if args.command == "latest-output-workbook":
        return _latest_output_workbook_command(args)
    if args.command == "promote-output-workbook":
        return _promote_output_workbook_command(args)
    if args.command == "current-workbook-status":
        return _current_workbook_status_command(args)
    if args.command == "promotion-history":
        return _promotion_history_command(args)
    if args.command == "export-history":
        return _export_history_command(args)
    if args.command == "verification-history":
        return _verification_history_command(args)
    if args.command == "list-promoted-archives":
        return _list_promoted_archives_command(args)
    if args.command == "rollback-workbook":
        return _rollback_workbook_command(args)
    if args.command == "product-readiness":
        return _product_readiness_command(args)
    if args.command == "list-artifacts":
        return _list_artifacts_command(args)
    if args.command == "latest-artifact":
        return _latest_artifact_command(args)
    if args.command == "show-artifact":
        return _show_artifact_command(args)
    if args.command == "find-report":
        return _find_report_command(args)
    if args.command == "find-verified-output":
        return _find_verified_output_command(args)
    if args.command == "compose-promote-command":
        return _compose_promote_command(args)
    if args.command == "compose-rollback-command":
        return _compose_rollback_command(args)
    if args.command == "next-safe-commands":
        return _next_safe_commands_command(args)
    if args.command == "operator-preflight":
        return _operator_preflight_command(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


def _inspect_workbook_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    base_dir = config_path.resolve().parent
    workbook_path = Path(args.workbook) if args.workbook else resolve_project_path(
        config["workbook"]["default_path"],
        base_dir=base_dir,
    )
    reports_dir = resolve_project_path(config["paths"]["reports_dir"], base_dir=base_dir)

    result = inspect_workbook(workbook_path, config)
    markdown_path, json_path = write_reports(result, reports_dir)

    print(f"Workbook inspection status: {result['overall_status']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if not result["workbook_file_exists"]:
        print(f"Workbook not found: {workbook_path}")
        return 1
    if result["overall_status"] == "fail":
        return 1
    return 0


def _init_queues_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    base_dir = config_path.resolve().parent
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)

    result = init_queues(queue_dir, config, force=args.force)
    print(f"Queue directory: {result['base_dir']}")
    print(f"Created: {len(result['created'])}")
    print(f"Skipped: {len(result['skipped'])}")
    print(f"Overwritten: {len(result['overwritten'])}")
    _print_paths("created", result["created"])
    _print_paths("skipped", result["skipped"])
    _print_paths("overwritten", result["overwritten"])
    return 0


def _validate_queues_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)
    base_dir = config_path.resolve().parent
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path("reports/queue_validation", base_dir=base_dir)

    result = validate_queues(queue_dir, config)
    markdown_path, json_path = write_queue_validation_reports(result, reports_dir)
    print(f"Queue validation status: {result['overall_status']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    if result["overall_status"] == "fail":
        return 1
    return 0


def _register_source_command(args: argparse.Namespace) -> int:
    config_path, config, base_dir = _load_command_config(args)
    del config_path
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    source_path = Path(args.file)

    try:
        result = register_source(
            source_path,
            queue_dir,
            config,
            source_type=args.source_type,
            title=args.title,
            author=args.author,
            url=args.url,
            allow_duplicate=args.allow_duplicate,
        )
    except (DuplicateSourceError, QueueSetupError, SourceRegistrationError) as exc:
        print(f"Could not register source: {exc}")
        return 1

    row = result["row"]
    print("Source registered.")
    print(f"Source ID: {row['source_id']}")
    print(f"Title: {row['title']}")
    print(f"Original file path: {row['original_file_path']}")
    print(f"Dossier file: {result['dossier_path']}")
    return 0


def _create_claim_template_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    output_dir = resolve_project_path(config["prompt_packets"]["output_dir"], base_dir=base_dir)

    try:
        result = create_claim_template(args.source_id, queue_dir, output_dir, config)
    except (FileNotFoundError, QueueSetupError, SourceRegistrationError) as exc:
        print(f"Could not create claim template: {exc}")
        return 1

    print("Claim template created.")
    print(f"Source ID: {result['source_id']}")
    print(f"Template: {result['template_path']}")
    return 0


def _generate_prompt_packet_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    output_dir = resolve_project_path(config["prompt_packets"]["output_dir"], base_dir=base_dir)

    try:
        result = generate_prompt_packet(
            args.source_id,
            queue_dir,
            output_dir,
            config,
            max_characters=args.max_characters,
        )
    except (FileNotFoundError, QueueSetupError, SourceRegistrationError) as exc:
        print(f"Could not generate prompt packet: {exc}")
        return 1

    print("Prompt packet created.")
    print(f"Source ID: {result['source_id']}")
    print(f"Prompt packet: {result['prompt_packet_path']}")
    print(f"Characters included: {result['characters_included']}")
    print(f"Truncated: {result['truncated']}")
    return 0


def _validate_import_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["manual_imports"]["reports_dir"], base_dir=base_dir)

    result = validate_manual_import(args.type, args.file, queue_dir, config)
    markdown_path, json_path = write_manual_import_report(result, reports_dir)
    print(f"Import validation status: {result['overall_status']}")
    print(f"Rows checked: {result['row_count']}")
    print(f"Target queue: {result['target_queue_file']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _append_import_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["manual_imports"]["reports_dir"], base_dir=base_dir)

    result = append_manual_import(args.type, args.file, queue_dir, config, dry_run=args.dry_run)
    markdown_path, json_path = write_manual_import_report(result, reports_dir)
    print(f"Import validation status: {result['overall_status']}")
    print(f"Dry run: {result['dry_run']}")
    print(f"Append performed: {result['append_performed']}")
    print(f"Rows appended: {result['rows_appended']}")
    print(f"Target queue: {result['target_queue_file']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _queue_summary_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["manual_imports"]["reports_dir"], base_dir=base_dir)
    summary = queue_summary(queue_dir, config)

    print(f"Queue directory: {summary['queue_dir']}")
    for name, count in summary["counts"].items():
        print(f"{name}: {count}")
    print("proposed_updates_by_review_status:")
    for status, count in summary["proposed_updates_by_review_status"].items():
        print(f"  {status}: {count}")
    print("approved_updates_export_tracking:")
    for status, count in summary["approved_updates_export_tracking"].items():
        print(f"  {status}: {count}")
    if args.save:
        summary_path = write_queue_summary(summary, reports_dir)
        print(f"Markdown summary: {summary_path}")
    return 0


def _review_proposal_command(args: argparse.Namespace, action: str) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["reviews"]["reports_dir"], base_dir=base_dir)
    mi5_overrides = _mi5_overrides_from_args(args)

    result = review_proposal(
        args.proposal_id,
        action,
        queue_dir,
        config,
        reviewer=args.reviewer,
        reason=getattr(args, "reason", ""),
        notes=args.notes,
        revisit_date=getattr(args, "revisit_date", ""),
        weight=getattr(args, "weight", None),
        category=getattr(args, "category", None),
        mi5_overrides=mi5_overrides,
    )
    markdown_path, json_path = write_review_report(result, reports_dir)
    print(f"Review status: {result['overall_status']}")
    print(f"Proposal ID: {result['proposal_id']}")
    print(f"Action: {result['action']}")
    print(f"Target queue: {result['target_queue']}")
    print(f"Proposed status updated: {result['proposed_status_updated']}")
    print(f"Target row appended: {result['target_queue_row_appended']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _list_proposals_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    rows = list_proposals(queue_dir, config, status=args.status, source_id=args.source_id, limit=args.limit)
    print(render_proposals_table(rows))
    return 0


def _preview_workbook_export_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    workbook_path = Path(args.workbook) if args.workbook else resolve_project_path(
        config["workbook"]["default_path"],
        base_dir=base_dir,
    )
    approved_file = Path(args.approved_file) if args.approved_file else queue_dir / config["queues"]["files"]["approved_updates"]
    reports_dir = resolve_project_path(config["workbook_export"]["reports_dir"], base_dir=base_dir)

    result = preview_workbook_export(
        workbook_path,
        approved_file,
        queue_dir,
        config,
        limit=args.limit,
        proposal_id=args.proposal_id,
        source_id=args.source_id,
    )
    markdown_path, json_path, csv_path = write_export_preview_artifacts(result, reports_dir)
    print(f"Workbook export preview status: {result['overall_status']}")
    print(f"Approved rows considered: {result['approved_rows_considered']}")
    print(f"Rows ready for export: {result['rows_ready_for_export']}")
    print(f"Rows blocked: {result['rows_blocked_by_validation_errors']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    print(f"CSV change plan: {csv_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _apply_approved_to_workbook_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    workbook_path = Path(args.workbook) if args.workbook else resolve_project_path(
        config["workbook"]["default_path"],
        base_dir=base_dir,
    )
    approved_file = Path(args.approved_file) if args.approved_file else queue_dir / config["queues"]["files"]["approved_updates"]
    backups_dir = resolve_project_path(config["workbook_export"]["backups_dir"], base_dir=base_dir)
    outputs_dir = resolve_project_path(config["workbook_export"]["outputs_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["workbook_export"]["final_reports_dir"], base_dir=base_dir)

    result = apply_approved_to_workbook(
        workbook_path,
        approved_file,
        queue_dir,
        config,
        backups_dir=backups_dir,
        outputs_dir=outputs_dir,
        dry_run=args.dry_run,
        limit=args.limit,
        proposal_id=args.proposal_id,
        source_id=args.source_id,
    )
    markdown_path, json_path = write_workbook_export_report(result, reports_dir)
    print(f"Workbook export status: {result['overall_status']}")
    print(f"Dry run: {result['dry_run']}")
    print(f"Rows exported: {result['rows_exported']}")
    print(f"Rows blocked: {result['rows_blocked']}")
    print(f"Backup workbook: {result['backup_workbook_path']}")
    print(f"Output workbook: {result['output_workbook_path']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _verify_workbook_export_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    approved_file = Path(args.approved_file) if args.approved_file else queue_dir / config["queues"]["files"]["approved_updates"]
    reports_dir = resolve_project_path(config["export_verification"]["reports_dir"], base_dir=base_dir)
    result = verify_workbook_export(
        args.workbook,
        approved_file,
        queue_dir,
        config,
        export_report=args.export_report,
        proposal_id=args.proposal_id,
        source_id=args.source_id,
        mark_exported=args.mark_exported,
    )
    markdown_path, json_path = write_export_verification_reports(result, reports_dir)
    print(f"Export verification status: {result['overall_status']}")
    print(f"Matching rows found: {result['matching_exported_rows_found']}")
    print(f"Missing rows: {result['missing_exported_rows']}")
    print(f"Value mismatches: {result['value_mismatches']}")
    print(f"Formula concerns: {result['formula_concerns']}")
    print(f"Marked exported: {result['approved_rows_marked_exported']}")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _latest_output_workbook_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    outputs_dir = resolve_project_path(config["export_verification"]["outputs_dir"], base_dir=base_dir)
    latest = latest_output_workbook(outputs_dir)
    if latest is None:
        print(f"No .xlsx output workbooks found under: {outputs_dir}")
        return 1
    print(latest)
    return 0


def _promote_output_workbook_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    promotion_config = config["workbook_promotion"]
    main_workbook = Path(args.main_workbook) if args.main_workbook else resolve_project_path(
        promotion_config["main_workbook_path"],
        base_dir=base_dir,
    )
    archive_dir = resolve_project_path(promotion_config["archive_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(promotion_config["reports_dir"], base_dir=base_dir)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)

    result = promote_output_workbook(
        args.workbook,
        args.verification_report,
        main_workbook,
        config,
        archive_dir=archive_dir,
        reports_dir=reports_dir,
        queue_dir=queue_dir,
        dry_run=args.dry_run,
    )
    print(f"Workbook promotion status: {result['overall_status']}")
    print(f"Dry run: {result['dry_run']}")
    print(f"Verification status: {result['verification_status']}")
    print(f"Verification report matched candidate: {result['verification_report_matched_candidate']}")
    print(f"Basic workbook inspection passed: {result['basic_workbook_inspection_passed']}")
    print(f"Archive path: {result['archive_path']}")
    print(f"Main workbook replaced: {result['main_workbook_replaced']}")
    if not args.dry_run:
        try:
            markdown_path, json_path = write_workbook_promotion_reports(result, reports_dir)
        except FileExistsError as exc:
            print(f"Could not write promotion reports: {exc}")
            return 1
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    else:
        print("Dry run wrote no files.")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _current_workbook_status_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    paths = _history_paths(config, base_dir)
    status = current_workbook_status(
        main_workbook=resolve_project_path(config["workbook_recovery"]["main_workbook_path"], base_dir=base_dir),
        outputs_dir=resolve_project_path(config["workbook_export"]["outputs_dir"], base_dir=base_dir),
        export_reports_dir=paths["exports"],
        verification_reports_dir=paths["verifications"],
        promotion_reports_dir=paths["promotions"],
        recovery_reports_dir=paths["recoveries"],
        promoted_archive_dir=resolve_project_path(config["workbook_recovery"]["archive_dir"], base_dir=base_dir),
        queue_dir=resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir),
        config=config,
    )
    print(render_current_status_markdown(status))
    if args.save:
        report_path = write_current_status_report(status, paths["recoveries"])
        print(f"Markdown report: {report_path}")
    return 0


def _promotion_history_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    paths = _history_paths(config, base_dir)
    history = promotion_history(
        paths["promotions"],
        resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir) / config["queues"]["files"]["change_log"],
        limit=args.limit,
    )
    return _print_history_command(history, paths["recoveries"], save=args.save)


def _export_history_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    paths = _history_paths(config, base_dir)
    history = export_history(
        paths["exports"],
        resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir) / config["queues"]["files"]["change_log"],
        limit=args.limit,
    )
    return _print_history_command(history, paths["recoveries"], save=args.save)


def _verification_history_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    paths = _history_paths(config, base_dir)
    history = verification_history(paths["verifications"], limit=args.limit)
    return _print_history_command(history, paths["recoveries"], save=args.save)


def _list_promoted_archives_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    archive_dir = resolve_project_path(config["workbook_recovery"]["archive_dir"], base_dir=base_dir)
    history = list_promoted_archives(archive_dir, limit=args.limit)
    print(render_history_table(history))
    return 0


def _rollback_workbook_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    recovery_config = config["workbook_recovery"]
    main_workbook = Path(args.main_workbook) if args.main_workbook else resolve_project_path(
        recovery_config["main_workbook_path"],
        base_dir=base_dir,
    )
    reports_dir = resolve_project_path(recovery_config["reports_dir"], base_dir=base_dir)
    rollback_archive_dir = resolve_project_path(recovery_config["rollback_archive_dir"], base_dir=base_dir)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    result = rollback_workbook(
        args.archive,
        main_workbook,
        config,
        rollback_archive_dir=rollback_archive_dir,
        reports_dir=reports_dir,
        queue_dir=queue_dir,
        dry_run=args.dry_run,
    )
    print(f"Workbook rollback status: {result['overall_status']}")
    print(f"Dry run: {result['dry_run']}")
    print(f"Archive inspection passed: {result['archive_inspection_passed']}")
    print(f"Rollback archive path: {result['rollback_archive_path']}")
    print(f"Main workbook replaced: {result['main_workbook_replaced']}")
    if not args.dry_run:
        try:
            markdown_path, json_path = write_workbook_rollback_reports(result, reports_dir)
        except FileExistsError as exc:
            print(f"Could not write rollback reports: {exc}")
            return 1
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    else:
        print("Dry run wrote no files.")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    return 1 if result["overall_status"] == "fail" else 0


def _list_artifacts_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = list_artifact_categories(config, base_dir)
    _print_structured(result, args.format)
    _save_artifact_navigation_if_requested(args, result, config, base_dir, "artifact_categories")
    return 0


def _latest_artifact_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    try:
        result = latest_artifact(args.type, config, base_dir)
    except UnknownArtifactTypeError as exc:
        print(exc)
        return 1
    _print_structured(result, args.format)
    _save_artifact_navigation_if_requested(args, result, config, base_dir, f"latest_{args.type}")
    return 0 if result["exists"] else 1


def _show_artifact_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    artifact_path = resolve_project_path(args.path, base_dir=base_dir)
    try:
        result = show_artifact(artifact_path, config)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    _print_structured(result, args.format)
    _save_artifact_navigation_if_requested(args, result, config, base_dir, "artifact_summary")
    return 0


def _find_report_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    try:
        result = find_reports(
            args.type,
            config,
            base_dir,
            status=args.status,
            contains=args.contains,
            source_id=args.source_id,
            proposal_id=args.proposal_id,
            limit=args.limit,
        )
    except UnknownArtifactTypeError as exc:
        print(exc)
        return 1
    _print_structured(result, args.format)
    _save_artifact_navigation_if_requested(args, result, config, base_dir, f"find_{args.type}")
    return 0


def _find_verified_output_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = find_verified_outputs(config, base_dir, status=args.status, latest=args.latest)
    _print_structured(result, args.format)
    _save_artifact_navigation_if_requested(args, result, config, base_dir, "verified_outputs")
    return 0


def _compose_promote_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = compose_promote_command(
        config,
        base_dir,
        workbook=args.workbook,
        verification_report=args.verification_report,
        latest=args.latest,
        include_dry_run=args.include_dry_run,
    )
    _print_command_guide(result, args.format)
    _save_command_guide_if_requested(args, result, config, base_dir, "PROMOTE")
    return 1 if result["errors"] else 0


def _compose_rollback_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = compose_rollback_command(
        config,
        base_dir,
        archive=args.archive,
        latest=args.latest,
        include_dry_run=args.include_dry_run,
    )
    _print_command_guide(result, args.format)
    _save_command_guide_if_requested(args, result, config, base_dir, "ROLLBACK")
    return 1 if result["errors"] else 0


def _next_safe_commands_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = next_safe_commands(config, base_dir)
    _print_command_guide(result, args.format)
    _save_command_guide_if_requested(args, result, config, base_dir, "NEXT_STEPS")
    return 0


def _operator_preflight_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    mode = args.mode or config.get("operator_preflight", {}).get("default_mode", "general")
    result = build_operator_preflight(
        config,
        base_dir,
        mode=mode,
        workbook=args.workbook,
        output_workbook=args.output_workbook,
        verification_report=args.verification_report,
        archive=args.archive,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_operator_preflight(result))
    if args.save:
        reports_dir = resolve_project_path(
            config.get("operator_preflight", {}).get("reports_dir", "reports/operator_preflight"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_operator_preflight_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _product_readiness_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    result = build_product_readiness(config, base_dir, sample_demo_dir=args.sample_demo_dir)
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_product_readiness(result))
    if args.save:
        reports_dir = resolve_project_path(
            config.get("product_readiness", {}).get("reports_dir", "reports/product_readiness"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_product_readiness_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _history_paths(config: dict, base_dir: Path) -> dict[str, Path]:
    discovery = config["report_discovery"]
    return {
        "exports": resolve_project_path(discovery["workbook_exports_dir"], base_dir=base_dir),
        "verifications": resolve_project_path(discovery["export_verification_dir"], base_dir=base_dir),
        "promotions": resolve_project_path(discovery["workbook_promotion_dir"], base_dir=base_dir),
        "recoveries": resolve_project_path(discovery["workbook_recovery_dir"], base_dir=base_dir),
    }


def _print_history_command(history: dict, reports_dir: Path, *, save: bool) -> int:
    print(render_history_table(history))
    if save:
        markdown_path, json_path = write_history_reports(history, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 0


def _print_structured(result: dict, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, indent=2) + "\n")
        return
    if "rows" in result:
        print(render_table(result))
    else:
        print(render_summary(result))


def _print_command_guide(result: dict, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, indent=2) + "\n")
        return
    print(render_command_guide(result))


def _save_artifact_navigation_if_requested(
    args: argparse.Namespace,
    result: dict,
    config: dict,
    base_dir: Path,
    report_name: str,
) -> None:
    if not getattr(args, "save", False):
        return
    reports_dir = resolve_project_path(
        config.get("artifact_navigation", {}).get("reports_dir", "reports/artifact_navigation"),
        base_dir=base_dir,
    )
    markdown_path, json_path = write_artifact_navigation_report(result, reports_dir, report_name=report_name)
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")


def _save_command_guide_if_requested(
    args: argparse.Namespace,
    result: dict,
    config: dict,
    base_dir: Path,
    guide_name: str,
) -> None:
    if not getattr(args, "save", False):
        return
    reports_dir = resolve_project_path(
        config.get("command_composition", {}).get("reports_dir", "reports/command_guides"),
        base_dir=base_dir,
    )
    markdown_path, json_path = write_command_guide_report(result, reports_dir, guide_name=guide_name)
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")


def _load_command_config(args: argparse.Namespace) -> tuple[Path, dict, Path]:
    config_path = Path(args.config)
    config = load_config(config_path)
    return config_path, config, config_path.resolve().parent


def _print_paths(label: str, paths: list[str]) -> None:
    if not paths:
        return
    print(f"{label.title()} files:")
    for path in paths:
        print(f"  - {path}")


def _add_review_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--proposal-id", required=True, help="Proposal ID to review.")
    parser.add_argument("--reviewer", required=True, help="Reviewer name.")
    parser.add_argument("--notes", default="", help="Optional review notes.")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )


def _mi5_overrides_from_args(args: argparse.Namespace) -> dict[str, str]:
    mapping = {
        "ec_mi5": "EC_MI5",
        "pc_mi5": "PC_MI5",
        "pt_mi5": "PT_MI5",
        "ct_mi5": "CT_MI5",
        "mt_mi5": "MT_MI5",
        "is_mi5": "IS_MI5",
        "ms_mi5": "MS_MI5",
        "hc_mi5": "HC_MI5",
        "n_mi5": "N_MI5",
    }
    return {
        field: value
        for arg_name, field in mapping.items()
        if (value := getattr(args, arg_name, None))
    }


if __name__ == "__main__":
    raise SystemExit(main())
