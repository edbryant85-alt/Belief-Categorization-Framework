from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues, validate_queues, write_queue_validation_reports
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_queue_schemas_exist_and_have_expected_headers() -> None:
    assert QUEUE_SCHEMAS["source_dossiers"] == [
        "source_id",
        "source_type",
        "title",
        "author_or_speaker",
        "participants",
        "date_created",
        "date_consumed",
        "date_added",
        "original_file_path",
        "url",
        "context",
        "short_summary",
        "main_claims",
        "worldview_or_perspective",
        "relevant_hypotheses",
        "reliability_notes",
        "bias_or_framing_notes",
        "my_notes",
        "processing_status",
    ]
    assert QUEUE_SCHEMAS["source_triage"] == [
        "source_id",
        "triage_status",
        "priority_0_5",
        "recommended_action",
        "relevance_tags",
        "summary",
        "key_claims",
        "reasons_for_attention",
        "reasons_to_skip",
        "cluster",
        "reviewer",
        "triaged_at",
        "notes",
    ]
    assert QUEUE_SCHEMAS["evidence_clusters"] == [
        "cluster_id",
        "cluster_title",
        "core_question",
        "description",
        "hypotheses_touched",
        "topic_tags",
        "status",
        "created_date",
        "updated_date",
        "notes",
    ]
    assert QUEUE_SCHEMAS["source_cluster_members"] == [
        "cluster_id",
        "source_id",
        "source_role",
        "subtopic",
        "relevance_0_5",
        "priority_0_5",
        "status",
        "notes",
    ]
    assert QUEUE_SCHEMAS["proposed_updates"][6] == "suggested_weight_0_5"
    assert QUEUE_SCHEMAS["proposed_updates"][-1] == "review_status"


def test_init_queues_creates_missing_queue_files(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"

    result = init_queues(queue_dir, config)

    assert len(result["created"]) == 13
    assert (queue_dir / "source_dossiers.csv").exists()
    assert (queue_dir / "source_triage.csv").exists()
    assert (queue_dir / "evidence_clusters.csv").exists()
    assert (queue_dir / "source_cluster_members.csv").exists()
    assert (queue_dir / "reflection_journal.md").exists()
    assert _read_header(queue_dir / "proposed_updates.csv") == QUEUE_SCHEMAS["proposed_updates"]


def test_init_queues_does_not_overwrite_existing_files_unless_forced(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    proposed_path = queue_dir / "proposed_updates.csv"
    proposed_path.write_text("custom\n", encoding="utf-8")

    skipped_result = init_queues(queue_dir, config)
    assert str(proposed_path) in skipped_result["skipped"]
    assert proposed_path.read_text(encoding="utf-8") == "custom\n"

    forced_result = init_queues(queue_dir, config, force=True)
    assert str(proposed_path) in forced_result["overwritten"]
    assert _read_header(proposed_path) == QUEUE_SCHEMAS["proposed_updates"]


def test_validate_queues_passes_on_freshly_initialized_empty_queues(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)

    result = validate_queues(queue_dir, config)

    assert result["overall_status"] == "pass"
    assert result["errors"] == []


def test_validate_queues_fails_on_invalid_mi5_labels(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    _append_row(
        queue_dir / "proposed_updates.csv",
        QUEUE_SCHEMAS["proposed_updates"],
        {"proposal_id": "P-001", "EC_MI5": "Certain-ish", "review_status": "proposed"},
    )

    result = validate_queues(queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("EC_MI5 has invalid value" in error for error in result["errors"])


def test_validate_queues_fails_on_invalid_claim_type(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    _append_row(
        queue_dir / "extracted_claims.csv",
        QUEUE_SCHEMAS["extracted_claims"],
        {"claim_id": "C-001", "claim_type": "rumor"},
    )

    result = validate_queues(queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("claim_type has invalid value" in error for error in result["errors"])


def test_validate_queues_fails_on_out_of_range_weights_and_scores(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    _append_row(
        queue_dir / "proposed_updates.csv",
        QUEUE_SCHEMAS["proposed_updates"],
        {"proposal_id": "P-001", "suggested_weight_0_5": "6", "review_status": "proposed"},
    )
    _append_row(
        queue_dir / "criteria_matrix.csv",
        QUEUE_SCHEMAS["criteria_matrix"],
        {"claim_id": "C-001", "relevance_0_5": "-1"},
    )

    result = validate_queues(queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("suggested_weight_0_5 must be between 0 and 5" in error for error in result["errors"])
    assert any("relevance_0_5 must be between 0 and 5" in error for error in result["errors"])


def test_validate_queues_writes_markdown_and_json_reports(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    reports_dir = tmp_path / "reports"
    init_queues(queue_dir, config)
    result = validate_queues(
        queue_dir,
        config,
        validated_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    markdown_path, json_path = write_queue_validation_reports(
        result,
        reports_dir,
        written_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    assert markdown_path.exists()
    assert json_path.exists()
    assert "Queue Validation Report" in markdown_path.read_text(encoding="utf-8")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["overall_status"] == "pass"


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def _append_row(path: Path, headers: list[str], values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        row = {header: "" for header in headers}
        row.update(values)
        writer.writerow(row)
