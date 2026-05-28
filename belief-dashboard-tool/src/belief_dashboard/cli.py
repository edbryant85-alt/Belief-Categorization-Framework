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
from belief_dashboard.debate_packets import (
    build_debate_packet,
    render_debate_packet,
    write_debate_packet_reports,
)
from belief_dashboard.debate_summaries import (
    build_debate_summary,
    render_debate_summary,
    write_debate_summary_reports,
)
from belief_dashboard.dossiers import DuplicateSourceError, QueueSetupError, find_source_dossiers, register_source
from belief_dashboard.doctor import (
    DOCTOR_MODES,
    build_doctor_explanation,
    build_doctor_report,
    render_doctor_explanation,
    render_doctor_report,
    write_doctor_explanation_reports,
    write_doctor_reports,
)
from belief_dashboard.evidence_networks import (
    CLUSTER_TYPES,
    build_evidence_clusters,
    build_source_network,
    render_evidence_clusters,
    render_source_network,
    write_evidence_network_reports,
)
from belief_dashboard.evidence_clusters import (
    EvidenceClusterError,
    add_source_to_cluster,
    build_cluster_summary,
    bulk_add_sources_to_cluster,
    cluster_candidates_for_extraction,
    create_cluster,
    generate_cluster_triage_packet,
    init_cluster_queues,
    list_clusters,
    render_cluster_summary,
    write_cluster_summary_reports,
)
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
    clean_manual_import,
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
from belief_dashboard.source_briefs import (
    build_source_brief,
    render_source_brief,
    write_source_brief_reports,
)
from belief_dashboard.source_comparisons import (
    build_source_comparison,
    build_source_map,
    render_source_comparison,
    render_source_map,
    write_source_comparison_reports,
)
from belief_dashboard.source_triage import (
    build_triage_summary,
    bulk_register_sources,
    generate_triage_prompt_packet,
    render_triage_summary,
    write_triage_summary_reports,
)
from belief_dashboard.study_queue import build_study_queue, render_study_queue, write_study_queue_reports
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

    init_cluster_parser = subparsers.add_parser(
        "init-cluster-queues",
        help="Create missing evidence cluster queue CSV templates.",
    )
    init_cluster_parser.add_argument("--force", action="store_true", help="Overwrite existing cluster queue files intentionally.")
    init_cluster_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

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

    bulk_register_parser = subparsers.add_parser(
        "bulk-register-sources",
        help="Register many raw source files for lightweight triage.",
    )
    bulk_register_parser.add_argument("--dir", required=True, help="Directory containing raw source files.")
    bulk_register_parser.add_argument("--glob", default="*", help="Filename glob to match. Defaults to *.")
    bulk_register_parser.add_argument("--recursive", action="store_true", help="Search directories recursively.")
    bulk_register_parser.add_argument("--limit", type=int, help="Maximum files to register.")
    bulk_register_parser.add_argument("--source-type", default="youtube_transcript", help="Source type to assign. Defaults to youtube_transcript.")
    bulk_register_parser.add_argument("--author", default="", help="Optional author or speaker for all registered files.")
    bulk_register_parser.add_argument("--allow-duplicate", action="store_true", help="Allow duplicate original file paths.")
    bulk_register_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    find_source_parser = subparsers.add_parser(
        "find-source",
        help="Find registered source IDs by title, path, URL, type, or metadata text.",
    )
    find_source_parser.add_argument("query", nargs="?", help="Text to search across source dossier metadata.")
    find_source_parser.add_argument("--source-id", help="Filter by source ID or partial source ID.")
    find_source_parser.add_argument("--file", help="Filter by original file path text.")
    find_source_parser.add_argument("--limit", type=int, default=20, help="Maximum rows to print. Defaults to 20.")
    find_source_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    find_source_parser.add_argument(
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

    triage_packet_parser = subparsers.add_parser(
        "generate-triage-packet",
        help="Create a ChatGPT-ready batch source triage prompt packet.",
    )
    triage_packet_parser.add_argument("--source-id", action="append", help="Source ID to include. Can be repeated.")
    triage_packet_parser.add_argument("--limit", type=int, help="Maximum untriaged sources to include.")
    triage_packet_parser.add_argument("--include-triaged", action="store_true", help="Allow already triaged sources in automatic selection.")
    triage_packet_parser.add_argument("--max-characters-per-source", type=int, help="Maximum characters to include per source.")
    triage_packet_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

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

    clean_import_parser = subparsers.add_parser(
        "clean-import",
        help="Write a cleaned copy of a manual import CSV without changing queue files.",
    )
    clean_import_parser.add_argument("--type", required=True, help="Import type, such as extracted_claims.")
    clean_import_parser.add_argument("--file", required=True, help="Path to the manual import CSV.")
    clean_import_parser.add_argument("--output", help="Cleaned CSV output path. Defaults to <input>_cleaned.csv.")
    clean_import_parser.add_argument(
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

    triage_summary_parser = subparsers.add_parser(
        "triage-summary",
        help="Summarize source triage decisions and full-extraction candidates.",
    )
    triage_summary_parser.add_argument("--min-priority", type=int, help="Minimum priority for full-extraction candidates.")
    triage_summary_parser.add_argument("--limit", type=int, help="Maximum candidate rows to include.")
    triage_summary_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    triage_summary_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/source_triage.")
    triage_summary_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    triage_candidates_parser = subparsers.add_parser(
        "list-triage-candidates",
        help="List triaged sources recommended for full extraction.",
    )
    triage_candidates_parser.add_argument("--min-priority", type=int, help="Minimum priority. Defaults to source_triage.default_candidate_min_priority.")
    triage_candidates_parser.add_argument("--limit", type=int, help="Maximum candidates to print.")
    triage_candidates_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    triage_candidates_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    create_cluster_parser = subparsers.add_parser("create-cluster", help="Create one evidence cluster row.")
    create_cluster_parser.add_argument("--cluster-id", required=True)
    create_cluster_parser.add_argument("--title", required=True)
    create_cluster_parser.add_argument("--core-question", required=True)
    create_cluster_parser.add_argument("--description", default="")
    create_cluster_parser.add_argument("--hypotheses", default="")
    create_cluster_parser.add_argument("--topic-tags", default="")
    create_cluster_parser.add_argument("--status", default="active")
    create_cluster_parser.add_argument("--notes", default="")
    create_cluster_parser.add_argument("--config", default="config.yaml")

    add_cluster_source_parser = subparsers.add_parser("add-source-to-cluster", help="Assign one registered source to an evidence cluster.")
    add_cluster_source_parser.add_argument("--cluster-id", required=True)
    add_cluster_source_parser.add_argument("--source-id", required=True)
    add_cluster_source_parser.add_argument("--role", required=True)
    add_cluster_source_parser.add_argument("--subtopic", default="")
    add_cluster_source_parser.add_argument("--relevance", type=float, default=0)
    add_cluster_source_parser.add_argument("--priority", type=float, default=0)
    add_cluster_source_parser.add_argument("--status", default="active")
    add_cluster_source_parser.add_argument("--notes", default="")
    add_cluster_source_parser.add_argument("--allow-duplicate", action="store_true")
    add_cluster_source_parser.add_argument("--config", default="config.yaml")

    bulk_cluster_source_parser = subparsers.add_parser("bulk-add-sources-to-cluster", help="Assign multiple existing source dossier rows to a cluster.")
    bulk_cluster_source_parser.add_argument("--cluster-id", required=True)
    bulk_cluster_source_parser.add_argument("--source-type")
    bulk_cluster_source_parser.add_argument("--source-folder")
    bulk_cluster_source_parser.add_argument("--source-id", action="append", default=[])
    bulk_cluster_source_parser.add_argument("--role", required=True)
    bulk_cluster_source_parser.add_argument("--subtopic", default="")
    bulk_cluster_source_parser.add_argument("--relevance", type=float, default=0)
    bulk_cluster_source_parser.add_argument("--priority", type=float, default=0)
    bulk_cluster_source_parser.add_argument("--status", default="active")
    bulk_cluster_source_parser.add_argument("--allow-duplicate", action="store_true")
    bulk_cluster_source_parser.add_argument("--format", choices=["table", "json"], default="table")
    bulk_cluster_source_parser.add_argument("--config", default="config.yaml")

    cluster_summary_parser = subparsers.add_parser("cluster-summary", help="Summarize one evidence cluster.")
    cluster_summary_parser.add_argument("--cluster-id", required=True)
    cluster_summary_parser.add_argument("--format", choices=["table", "json"], default="table")
    cluster_summary_parser.add_argument("--save", action="store_true")
    cluster_summary_parser.add_argument("--config", default="config.yaml")

    list_clusters_parser = subparsers.add_parser("list-clusters", help="List evidence clusters.")
    list_clusters_parser.add_argument("--status")
    list_clusters_parser.add_argument("--topic")
    list_clusters_parser.add_argument("--hypothesis")
    list_clusters_parser.add_argument("--format", choices=["table", "json"], default="table")
    list_clusters_parser.add_argument("--config", default="config.yaml")

    cluster_packet_parser = subparsers.add_parser("generate-cluster-triage-packet", help="Create a cluster-level ChatGPT triage packet.")
    cluster_packet_parser.add_argument("--cluster-id", required=True)
    cluster_packet_parser.add_argument("--max-sources", type=int)
    cluster_packet_parser.add_argument("--max-chars-per-source", type=int)
    cluster_packet_parser.add_argument("--include-role")
    cluster_packet_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cluster_packet_parser.add_argument("--output")
    cluster_packet_parser.add_argument("--config", default="config.yaml")

    cluster_candidates_parser = subparsers.add_parser("cluster-candidates-for-extraction", help="List cluster sources likely worth full extraction.")
    cluster_candidates_parser.add_argument("--cluster-id", required=True)
    cluster_candidates_parser.add_argument("--min-priority", type=float)
    cluster_candidates_parser.add_argument("--format", choices=["table", "json"], default="table")
    cluster_candidates_parser.add_argument("--config", default="config.yaml")

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

    batch_review_parser = subparsers.add_parser(
        "batch-review-guide",
        help="Print conservative per-proposal review commands without changing queue files.",
    )
    batch_review_parser.add_argument("--source-id", help="Filter to one source ID.")
    batch_review_parser.add_argument("--status", default="proposed", help="Filter by review_status. Defaults to proposed.")
    batch_review_parser.add_argument("--action", choices=["approved", "rejected", "deferred"], default="approved", help="Review action to compose. Defaults to approved.")
    batch_review_parser.add_argument("--reviewer", required=True, help="Reviewer name to include in commands.")
    batch_review_parser.add_argument("--reason", default="", help="Reason to include for rejected/deferred commands.")
    batch_review_parser.add_argument("--limit", type=int, help="Maximum commands to print.")
    batch_review_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    batch_review_parser.add_argument(
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

    doctor_parser = subparsers.add_parser("doctor", help="Explain project health issues and safest repair commands.")
    doctor_parser.add_argument("--mode", choices=sorted(DOCTOR_MODES), help="Doctor mode. Defaults to doctor.default_mode.")
    doctor_parser.add_argument("--explain", help="Explain one currently detected doctor finding ID in more detail.")
    doctor_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    doctor_parser.add_argument("--save", action="store_true", help="Save markdown and JSON doctor reports under reports/doctor.")
    doctor_parser.add_argument("--verbose", action="store_true", help="Include informational findings in console output.")
    doctor_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    debate_parser = subparsers.add_parser("debate-summary", help="Summarize approved evidence for debate prep without changing data.")
    debate_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    debate_parser.add_argument("--all", action="store_true", help="Generate summaries for all configured hypotheses.")
    debate_parser.add_argument("--limit", type=int, help="Maximum items per section. Defaults to debate_summaries.default_limit.")
    debate_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    debate_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    debate_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    debate_parser.add_argument("--source-id", help="Filter to one source ID.")
    debate_parser.add_argument("--category", help="Filter to categories containing this text.")
    debate_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    debate_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/debate_summaries.")
    debate_parser.add_argument("--short", action="store_true", help="Print a compact summary.")
    debate_parser.add_argument("--long", action="store_true", help="Print a more detailed summary.")
    debate_parser.add_argument("--discord", action="store_true", help="Print compact copy-friendly markdown for Discord.")
    debate_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    packet_parser = subparsers.add_parser("debate-packet", help="Create a printable read-only debate prep packet.")
    packet_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    packet_parser.add_argument("--topic", help="Simple text filter over evidence, source, and claim context.")
    packet_parser.add_argument("--limit", type=int, help="Maximum items per section. Defaults to debate_packets.default_limit.")
    packet_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    packet_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    packet_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    packet_parser.add_argument("--source-id", help="Filter to one source ID.")
    packet_parser.add_argument("--category", help="Filter to categories containing this text.")
    packet_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    packet_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/debate_packets.")
    packet_parser.add_argument("--discord", action="store_true", help="Print only the compact Discord section.")
    packet_parser.add_argument("--short", action="store_true", help="Print a compact packet.")
    packet_parser.add_argument("--long", action="store_true", help="Print a more detailed packet.")
    packet_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    study_parser = subparsers.add_parser("study-queue", help="Create a read-only prioritized study and reflection checklist.")
    study_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    study_parser.add_argument("--all", action="store_true", help="Consider all configured hypotheses.")
    study_parser.add_argument("--topic", help="Simple text filter over evidence, source, claim, and criteria context.")
    study_parser.add_argument("--limit", type=int, help="Maximum study items to show. Defaults to study_queue.default_limit.")
    study_parser.add_argument("--min-priority", type=float, help="Minimum priority score to include.")
    study_parser.add_argument("--source-id", help="Filter to one source ID.")
    study_parser.add_argument("--category", help="Filter to categories containing this text.")
    study_parser.add_argument("--include-deferred", action="store_true", help="Include deferred updates as study candidates.")
    study_parser.add_argument("--include-rejected", action="store_true", help="Include rejected updates for review context.")
    study_parser.add_argument("--include-reflections", action="store_true", help="Include reflection journal notes if present.")
    study_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format. Defaults to table.")
    study_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/study_queue.")
    study_parser.add_argument("--short", action="store_true", help="Print a compact study queue.")
    study_parser.add_argument("--long", action="store_true", help="Print a more detailed study queue.")
    study_parser.add_argument("--discord", action="store_true", help="Print compact copy-friendly study priorities.")
    study_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    source_brief_parser = subparsers.add_parser("source-brief", help="Create a read-only dossier for one source ID.")
    source_brief_parser.add_argument("--source-id", required=True, help="Source ID, such as SRC0001.")
    source_brief_parser.add_argument("--limit", type=int, help="Maximum rows per long section. Defaults to source_briefs.default_limit.")
    source_brief_parser.add_argument("--include-raw-excerpt", dest="include_raw_excerpt", action="store_true", default=None, help="Include a bounded excerpt from original_file_path.")
    source_brief_parser.add_argument("--no-raw-excerpt", dest="include_raw_excerpt", action="store_false", help="Do not include a raw source excerpt.")
    source_brief_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    source_brief_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/source_briefs.")
    source_brief_parser.add_argument("--short", action="store_true", help="Print a compact source brief.")
    source_brief_parser.add_argument("--long", action="store_true", help="Print a more detailed source brief.")
    source_brief_parser.add_argument("--discord", action="store_true", help="Print only the compact Discord source brief.")
    source_brief_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    compare_parser = subparsers.add_parser("compare-sources", help="Compare two or more source dossiers read-only.")
    compare_parser.add_argument("--source-id", action="append", default=[], help="Source ID to compare. Repeat for multiple sources.")
    compare_parser.add_argument("--sources", help="Comma-separated source IDs, such as SRC0001,SRC0002.")
    compare_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    compare_parser.add_argument("--topic", help="Simple text filter over evidence, source, claim, and criteria context.")
    compare_parser.add_argument("--limit", type=int, help="Maximum rows per section. Defaults to source_comparisons.default_limit.")
    compare_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    compare_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    compare_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    compare_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    compare_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/source_comparisons.")
    compare_parser.add_argument("--short", action="store_true", help="Print a compact comparison.")
    compare_parser.add_argument("--long", action="store_true", help="Print a more detailed comparison.")
    compare_parser.add_argument("--discord", action="store_true", help="Print only compact copy-friendly comparison text.")
    compare_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    source_map_parser = subparsers.add_parser("source-map", help="Map sources affecting one hypothesis or topic read-only.")
    source_map_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    source_map_parser.add_argument("--topic", help="Simple text filter over evidence, source, claim, and criteria context.")
    source_map_parser.add_argument("--limit", type=int, help="Maximum rows per section. Defaults to source_comparisons.default_limit.")
    source_map_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    source_map_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    source_map_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    source_map_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    source_map_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/source_comparisons.")
    source_map_parser.add_argument("--short", action="store_true", help="Print a compact source map.")
    source_map_parser.add_argument("--long", action="store_true", help="Print a more detailed source map.")
    source_map_parser.add_argument("--discord", action="store_true", help="Print only compact copy-friendly source-map text.")
    source_map_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    clusters_parser = subparsers.add_parser("evidence-clusters", help="Group evidence into read-only thematic and structural clusters.")
    clusters_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    clusters_parser.add_argument("--topic", help="Simple text filter over evidence, source, claim, and criteria context.")
    clusters_parser.add_argument("--category", help="Filter to categories containing this text.")
    clusters_parser.add_argument("--source-id", help="Filter to one source ID.")
    clusters_parser.add_argument("--cluster-type", choices=sorted(CLUSTER_TYPES), default="all", help="Cluster family to show. Defaults to all.")
    clusters_parser.add_argument("--limit", type=int, help="Maximum rows per section. Defaults to evidence_networks.default_limit.")
    clusters_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    clusters_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    clusters_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    clusters_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    clusters_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/evidence_networks.")
    clusters_parser.add_argument("--short", action="store_true", help="Print compact clusters.")
    clusters_parser.add_argument("--long", action="store_true", help="Print detailed clusters.")
    clusters_parser.add_argument("--discord", action="store_true", help="Print only compact copy-friendly cluster text.")
    clusters_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    network_parser = subparsers.add_parser("source-network", help="Create a read-only source-centered evidence network summary.")
    network_parser.add_argument("--hypothesis", help="Hypothesis ID, such as EC or N.")
    network_parser.add_argument("--topic", help="Simple text filter over evidence, source, claim, and criteria context.")
    network_parser.add_argument("--source-id", help="Filter to one source ID.")
    network_parser.add_argument("--limit", type=int, help="Maximum rows per section. Defaults to evidence_networks.default_limit.")
    network_parser.add_argument("--min-weight", type=float, help="Minimum approved weight to include.")
    network_parser.add_argument("--exported-only", action="store_true", help="Only include approved rows marked exported.")
    network_parser.add_argument("--include-unexported", action="store_true", help="Allow unexported approved rows. This is the default unless --exported-only is supplied.")
    network_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format. Defaults to markdown.")
    network_parser.add_argument("--save", action="store_true", help="Save markdown and JSON reports under reports/evidence_networks.")
    network_parser.add_argument("--short", action="store_true", help="Print a compact source network.")
    network_parser.add_argument("--long", action="store_true", help="Print a detailed source network.")
    network_parser.add_argument("--discord", action="store_true", help="Print only compact copy-friendly source-network text.")
    network_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml. Defaults to ./config.yaml.")

    args = parser.parse_args(argv)

    if args.command == "inspect-workbook":
        return _inspect_workbook_command(args)
    if args.command == "init-queues":
        return _init_queues_command(args)
    if args.command == "init-cluster-queues":
        return _init_cluster_queues_command(args)
    if args.command == "validate-queues":
        return _validate_queues_command(args)
    if args.command == "register-source":
        return _register_source_command(args)
    if args.command == "bulk-register-sources":
        return _bulk_register_sources_command(args)
    if args.command == "find-source":
        return _find_source_command(args)
    if args.command == "create-claim-template":
        return _create_claim_template_command(args)
    if args.command == "generate-prompt-packet":
        return _generate_prompt_packet_command(args)
    if args.command == "generate-triage-packet":
        return _generate_triage_packet_command(args)
    if args.command == "validate-import":
        return _validate_import_command(args)
    if args.command == "clean-import":
        return _clean_import_command(args)
    if args.command == "append-import":
        return _append_import_command(args)
    if args.command == "queue-summary":
        return _queue_summary_command(args)
    if args.command == "triage-summary":
        return _triage_summary_command(args)
    if args.command == "list-triage-candidates":
        return _list_triage_candidates_command(args)
    if args.command == "create-cluster":
        return _create_cluster_command(args)
    if args.command == "add-source-to-cluster":
        return _add_source_to_cluster_command(args)
    if args.command == "bulk-add-sources-to-cluster":
        return _bulk_add_sources_to_cluster_command(args)
    if args.command == "cluster-summary":
        return _cluster_summary_command(args)
    if args.command == "list-clusters":
        return _list_clusters_command(args)
    if args.command == "generate-cluster-triage-packet":
        return _generate_cluster_triage_packet_command(args)
    if args.command == "cluster-candidates-for-extraction":
        return _cluster_candidates_for_extraction_command(args)
    if args.command == "approve-proposal":
        return _review_proposal_command(args, "approved")
    if args.command == "reject-proposal":
        return _review_proposal_command(args, "rejected")
    if args.command == "defer-proposal":
        return _review_proposal_command(args, "deferred")
    if args.command == "list-proposals":
        return _list_proposals_command(args)
    if args.command == "batch-review-guide":
        return _batch_review_guide_command(args)
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
    if args.command == "doctor":
        return _doctor_command(args)
    if args.command == "debate-summary":
        return _debate_summary_command(args)
    if args.command == "debate-packet":
        return _debate_packet_command(args)
    if args.command == "study-queue":
        return _study_queue_command(args)
    if args.command == "source-brief":
        return _source_brief_command(args)
    if args.command == "compare-sources":
        return _compare_sources_command(args)
    if args.command == "source-map":
        return _source_map_command(args)
    if args.command == "evidence-clusters":
        return _evidence_clusters_command(args)
    if args.command == "source-network":
        return _source_network_command(args)

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


def _init_cluster_queues_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    result = init_cluster_queues(queue_dir, config, force=args.force)
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


def _bulk_register_sources_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    raw_dir = Path(args.dir)
    result = bulk_register_sources(
        raw_dir,
        queue_dir,
        config,
        source_type=args.source_type,
        pattern=args.glob,
        recursive=args.recursive,
        limit=args.limit,
        author=args.author,
        allow_duplicate=args.allow_duplicate,
    )
    print(f"Raw sources directory: {result['raw_sources_dir']}")
    print(f"Files considered: {result['files_considered']}")
    print(f"Registered: {len(result['registered'])}")
    print(f"Skipped: {len(result['skipped'])}")
    if result["registered"]:
        for row in result["registered"]:
            print(f"- {row['source_id']}: {row['title']} ({row['file_path']})")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    return 1 if result["errors"] else 0


def _find_source_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        rows = find_source_dossiers(
            queue_dir,
            config,
            query=args.query,
            source_id=args.source_id,
            file_path=args.file,
            limit=args.limit,
        )
    except QueueSetupError as exc:
        print(f"Could not find sources: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print(_render_sources_table(rows))
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


def _generate_triage_packet_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    output_dir = resolve_project_path(config["source_triage"]["reports_dir"], base_dir=base_dir)
    limit = args.limit
    if limit is None and not args.source_id:
        limit = int(config["source_triage"]["default_batch_size"])
    try:
        result = generate_triage_prompt_packet(
            queue_dir,
            output_dir,
            config,
            source_ids=args.source_id,
            limit=limit,
            include_triaged=args.include_triaged,
            max_characters_per_source=args.max_characters_per_source,
        )
    except (FileNotFoundError, QueueSetupError, SourceRegistrationError) as exc:
        print(f"Could not generate triage packet: {exc}")
        return 1
    print("Triage prompt packet created.")
    print(f"Sources included: {result['source_count']}")
    print(f"Source IDs: {', '.join(result['source_ids'])}")
    print(f"Prompt packet: {result['prompt_packet_path']}")
    print(f"Characters included: {result['characters_included']}")
    print(f"Truncated sources: {result['truncated_source_count']}")
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


def _clean_import_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    input_path = Path(args.file)
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_cleaned{input_path.suffix}")
    result = clean_manual_import(args.type, input_path, output_path, queue_dir, config)
    print(f"Clean import status: {result['overall_status']}")
    print(f"Rows cleaned: {result['row_count']}")
    print(f"Output file: {result['output_file_path']}")
    print(f"Changes: {len(result['changes'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
    for note in result["next_step_notes"]:
        print(note)
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


def _triage_summary_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config["source_triage"]["reports_dir"], base_dir=base_dir)
    summary = build_triage_summary(queue_dir, config, min_priority=args.min_priority, limit=args.limit)
    if args.format == "json":
        print(json.dumps(summary, indent=2))
    else:
        print(render_triage_summary(summary))
    if args.save:
        markdown_path, json_path = write_triage_summary_reports(summary, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 0


def _list_triage_candidates_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    summary = build_triage_summary(queue_dir, config, min_priority=args.min_priority, limit=args.limit)
    candidates = summary["full_extraction_candidates"]
    if args.format == "json":
        print(json.dumps(candidates, indent=2))
        return 0
    print(_render_triage_candidates_table(candidates))
    return 0


def _create_cluster_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        result = create_cluster(
            queue_dir,
            config,
            cluster_id=args.cluster_id,
            title=args.title,
            core_question=args.core_question,
            description=args.description,
            hypotheses=args.hypotheses,
            topic_tags=args.topic_tags,
            status=args.status,
            notes=args.notes,
        )
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not create cluster: {exc}")
        return 1
    print("Evidence cluster created.")
    print(f"Cluster ID: {result['cluster_id']}")
    print(f"Cluster queue: {result['cluster_path']}")
    return 0


def _add_source_to_cluster_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        result = add_source_to_cluster(
            queue_dir,
            config,
            cluster_id=args.cluster_id,
            source_id=args.source_id,
            role=args.role,
            subtopic=args.subtopic,
            relevance=args.relevance,
            priority=args.priority,
            status=args.status,
            notes=args.notes,
            allow_duplicate=args.allow_duplicate,
        )
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not add source to cluster: {exc}")
        return 1
    print("Source added to evidence cluster.")
    print(f"Cluster ID: {result['row']['cluster_id']}")
    print(f"Source ID: {result['row']['source_id']}")
    print(f"Role: {result['row']['source_role']}")
    print(f"Membership queue: {result['membership_path']}")
    return 0


def _bulk_add_sources_to_cluster_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        result = bulk_add_sources_to_cluster(
            queue_dir,
            config,
            cluster_id=args.cluster_id,
            source_type=args.source_type,
            source_folder=args.source_folder,
            source_ids=args.source_id,
            role=args.role,
            subtopic=args.subtopic,
            relevance=args.relevance,
            priority=args.priority,
            status=args.status,
            allow_duplicate=args.allow_duplicate,
        )
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not bulk add sources to cluster: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Cluster ID: {result['cluster_id']}")
        print(f"Considered: {result['considered']}")
        print(f"Added: {len(result['added'])}")
        print(f"Skipped: {len(result['skipped'])}")
        print(f"Failed: {len(result['failed'])}")
        for row in result["added"]:
            print(f"- {row['source_id']}: {row['title']}")
    return 1 if result["failed"] else 0


def _cluster_summary_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        summary = build_cluster_summary(queue_dir, config, cluster_id=args.cluster_id)
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not summarize cluster: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(summary, indent=2))
    else:
        print(render_cluster_summary(summary))
    if args.save:
        reports_dir = resolve_project_path(config.get("evidence_clusters", {}).get("reports_dir", "reports/evidence_clusters"), base_dir=base_dir)
        markdown_path, json_path = write_cluster_summary_reports(summary, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 0


def _list_clusters_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        result = list_clusters(queue_dir, config, status=args.status, topic=args.topic, hypothesis=args.hypothesis)
    except QueueSetupError as exc:
        print(f"Could not list clusters: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(_render_clusters_table(result["rows"]))
    return 0


def _generate_cluster_triage_packet_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    reports_dir = resolve_project_path(config.get("evidence_clusters", {}).get("reports_dir", "reports/evidence_clusters"), base_dir=base_dir)
    try:
        result = generate_cluster_triage_packet(
            queue_dir,
            reports_dir,
            config,
            cluster_id=args.cluster_id,
            max_sources=args.max_sources,
            max_chars_per_source=args.max_chars_per_source,
            include_role=args.include_role,
            output_path=args.output,
        )
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not generate cluster triage packet: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("Cluster triage prompt packet created.")
        print(f"Cluster ID: {result['cluster_id']}")
        print(f"Sources included: {result['source_count']}")
        print(f"Prompt packet: {result['prompt_packet_path']}")
        print(f"Characters included: {result['characters_included']}")
    return 0


def _cluster_candidates_for_extraction_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    try:
        result = cluster_candidates_for_extraction(queue_dir, config, cluster_id=args.cluster_id, min_priority=args.min_priority)
    except (EvidenceClusterError, QueueSetupError) as exc:
        print(f"Could not list cluster candidates: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(_render_cluster_candidates_table(result["rows"]))
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


def _batch_review_guide_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    queue_dir = resolve_project_path(config["queues"]["base_dir"], base_dir=base_dir)
    rows = list_proposals(queue_dir, config, status=args.status, source_id=args.source_id, limit=args.limit)
    commands = [_review_command_for_row(row, args.action, args.reviewer, args.reason) for row in rows]
    result = {
        "operation": "batch_review_guide",
        "action": args.action,
        "reviewer": args.reviewer,
        "source_id": args.source_id or "",
        "status": args.status or "",
        "commands": commands,
        "no_queue_data_modified": True,
    }
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("Batch review guide")
        print("No queue data was modified.")
        for command in commands:
            print(command)
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


def _doctor_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    mode = args.mode or config.get("doctor", {}).get("default_mode", "general")
    if args.explain:
        explanation = build_doctor_explanation(config, base_dir, args.explain, mode=mode)
        if args.format == "json":
            print(json.dumps(explanation, indent=2) + "\n")
        else:
            print(render_doctor_explanation(explanation))
        if args.save:
            reports_dir = resolve_project_path(
                config.get("doctor", {}).get("reports_dir", "reports/doctor"),
                base_dir=base_dir,
            )
            markdown_path, json_path = write_doctor_explanation_reports(explanation, reports_dir)
            print(f"Markdown report: {markdown_path}")
            print(f"JSON report: {json_path}")
        return 0 if explanation["status"] == "detected" else 1

    result = build_doctor_report(config, base_dir, mode=mode, verbose=args.verbose)
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_doctor_report(result))
    if args.save:
        reports_dir = resolve_project_path(
            config.get("doctor", {}).get("reports_dir", "reports/doctor"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_doctor_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _debate_summary_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    if not args.hypothesis and not args.all:
        print("Supply either --hypothesis HYPOTHESIS_ID or --all.")
        return 1
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    result = build_debate_summary(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        all_hypotheses=args.all,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        source_id=args.source_id,
        category=args.category,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_debate_summary(result, style="discord" if args.discord else "table", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("debate_summaries", {}).get("reports_dir", "reports/debate_summaries"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_debate_summary_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _debate_packet_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    if not args.hypothesis and not args.topic:
        print('Supply --hypothesis HYPOTHESIS_ID, --topic "topic text", or both.')
        return 1
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    packet = build_debate_packet(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        topic=args.topic,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        source_id=args.source_id,
        category=args.category,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(packet, indent=2) + "\n")
    else:
        print(render_debate_packet(packet, style="discord" if args.discord else "markdown", length=length))
    if args.save and packet["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("debate_packets", {}).get("reports_dir", "reports/debate_packets"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_debate_packet_reports(packet, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if packet["overall_status"] == "fail" else 0


def _study_queue_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    include_deferred = True if args.include_deferred else None
    include_reflections = True if args.include_reflections else None
    result = build_study_queue(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        all_hypotheses=args.all,
        topic=args.topic,
        limit=args.limit,
        min_priority=args.min_priority,
        source_id=args.source_id,
        category=args.category,
        include_deferred=include_deferred,
        include_rejected=args.include_rejected,
        include_reflections=include_reflections,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_study_queue(result, style="discord" if args.discord else "table", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("study_queue", {}).get("reports_dir", "reports/study_queue"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_study_queue_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _source_brief_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    result = build_source_brief(
        config,
        base_dir,
        source_id=args.source_id,
        limit=args.limit,
        include_raw_excerpt=args.include_raw_excerpt,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_source_brief(result, style="discord" if args.discord else "markdown", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("source_briefs", {}).get("reports_dir", "reports/source_briefs"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_source_brief_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _compare_sources_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    source_ids = list(args.source_id or [])
    if args.sources:
        source_ids.extend(item.strip() for item in args.sources.split(",") if item.strip())
    result = build_source_comparison(
        config,
        base_dir,
        source_ids=source_ids,
        hypothesis=args.hypothesis,
        topic=args.topic,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_source_comparison(result, style="discord" if args.discord else "markdown", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("source_comparisons", {}).get("reports_dir", "reports/source_comparisons"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_source_comparison_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _source_map_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    if not args.hypothesis and not args.topic:
        print('Supply --hypothesis HYPOTHESIS_ID, --topic "topic text", or both.')
        return 1
    result = build_source_map(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        topic=args.topic,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_source_map(result, style="discord" if args.discord else "markdown", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("source_comparisons", {}).get("reports_dir", "reports/source_comparisons"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_source_comparison_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _evidence_clusters_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    result = build_evidence_clusters(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        topic=args.topic,
        category=args.category,
        source_id=args.source_id,
        cluster_type=args.cluster_type,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_evidence_clusters(result, style="discord" if args.discord else "markdown", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("evidence_networks", {}).get("reports_dir", "reports/evidence_networks"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_evidence_network_reports(result, reports_dir)
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
    return 1 if result["overall_status"] == "fail" else 0


def _source_network_command(args: argparse.Namespace) -> int:
    _config_path, config, base_dir = _load_command_config(args)
    length = "medium"
    if args.short:
        length = "short"
    if args.long:
        length = "long"
    result = build_source_network(
        config,
        base_dir,
        hypothesis=args.hypothesis,
        topic=args.topic,
        source_id=args.source_id,
        limit=args.limit,
        min_weight=args.min_weight,
        exported_only=args.exported_only,
        include_unexported=args.include_unexported,
        length=length,
    )
    if args.format == "json":
        print(json.dumps(result, indent=2) + "\n")
    else:
        print(render_source_network(result, style="discord" if args.discord else "markdown", length=length))
    if args.save and result["overall_status"] != "fail":
        reports_dir = resolve_project_path(
            config.get("evidence_networks", {}).get("reports_dir", "reports/evidence_networks"),
            base_dir=base_dir,
        )
        markdown_path, json_path = write_evidence_network_reports(result, reports_dir)
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


def _render_sources_table(rows: list[dict[str, str]]) -> str:
    headers = ["source_id", "source_type", "title", "author_or_speaker", "original_file_path"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows:
        lines.append(" | ".join(_clip(row.get(header, "")) for header in headers))
    if not rows:
        lines.append("No matching sources found. |  |  |  | ")
    return "\n".join(lines)


def _render_triage_candidates_table(rows: list[dict[str, str]]) -> str:
    headers = ["source_id", "priority_0_5", "recommended_action", "title", "cluster"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows:
        lines.append(" | ".join(_clip(row.get(header, "")) for header in headers))
    if not rows:
        lines.append("No full-extraction candidates found. |  |  |  | ")
    return "\n".join(lines)


def _render_clusters_table(rows: list[dict[str, str]]) -> str:
    headers = ["cluster_id", "cluster_title", "status", "hypotheses_touched", "topic_tags", "source_count"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows:
        lines.append(" | ".join(_clip(str(row.get(header, ""))) for header in headers))
    if not rows:
        lines.append("No matching clusters found. |  |  |  |  | ")
    return "\n".join(lines)


def _render_cluster_candidates_table(rows: list[dict[str, str]]) -> str:
    headers = ["source_id", "title", "source_type", "source_role", "subtopic", "relevance_0_5", "priority_0_5", "suggested_next_command"]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in rows:
        lines.append(" | ".join(_clip(str(row.get(header, ""))) for header in headers))
    if not rows:
        lines.append("No cluster extraction candidates found. |  |  |  |  |  |  | ")
    return "\n".join(lines)


def _review_command_for_row(row: dict[str, str], action: str, reviewer: str, reason: str) -> str:
    proposal_id = row.get("proposal_id", "")
    if action == "approved":
        return f"python -m belief_dashboard.cli approve-proposal --proposal-id {proposal_id} --reviewer {_quote_arg(reviewer)}"
    if action == "rejected":
        return (
            f"python -m belief_dashboard.cli reject-proposal --proposal-id {proposal_id} "
            f"--reviewer {_quote_arg(reviewer)} --reason {_quote_arg(reason or 'Add rejection reason')}"
        )
    return (
        f"python -m belief_dashboard.cli defer-proposal --proposal-id {proposal_id} "
        f"--reviewer {_quote_arg(reviewer)} --reason {_quote_arg(reason or 'Add deferral reason')}"
    )


def _quote_arg(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _clip(value: str, limit: int = 80) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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
