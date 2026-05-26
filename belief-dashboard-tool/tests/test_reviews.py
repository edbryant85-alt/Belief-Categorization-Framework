from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from belief_dashboard.cli import main
from belief_dashboard.config import load_config
from belief_dashboard.queues import init_queues
from belief_dashboard.reviews import (
    list_proposals,
    render_proposals_table,
    review_proposal,
    write_review_report,
)
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_approving_proposed_update_appends_correct_row_to_approved_updates(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    result = review_proposal(
        "PROP0001",
        "approved",
        queue_dir,
        config,
        reviewer="Eric",
        reviewed_on=date(2026, 5, 25),
    )

    approved_rows = _read_rows(queue_dir / "approved_updates.csv")
    assert result["overall_status"] == "pass"
    assert approved_rows[0]["proposal_id"] == "PROP0001"
    assert approved_rows[0]["approved_weight_0_5"] == "3"
    assert approved_rows[0]["approved_by"] == "Eric"
    assert approved_rows[0]["approved_date"] == "2026-05-25"


def test_approving_updates_review_status_to_approved(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric")

    proposed_rows = _read_rows(queue_dir / "proposed_updates.csv")
    assert proposed_rows[0]["review_status"] == "approved"


def test_approval_with_weight_override_uses_override(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric", weight="4")

    approved_rows = _read_rows(queue_dir / "approved_updates.csv")
    assert approved_rows[0]["approved_weight_0_5"] == "4"


def test_approval_with_invalid_mi5_override_fails(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    result = review_proposal(
        "PROP0001",
        "approved",
        queue_dir,
        config,
        reviewer="Eric",
        mi5_overrides={"EC_MI5": "Certain-ish"},
    )

    assert result["overall_status"] == "fail"
    assert _read_rows(queue_dir / "approved_updates.csv") == []


def test_approval_with_out_of_range_weight_fails(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    result = review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric", weight="6")

    assert result["overall_status"] == "fail"
    assert any("between 0 and 5" in error for error in result["errors"])


def test_rejecting_proposed_update_appends_correct_row_to_rejected_updates(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal(
        "PROP0001",
        "rejected",
        queue_dir,
        config,
        reviewer="Eric",
        reason="Not strong enough.",
        notes="Reviewed manually.",
        reviewed_on=date(2026, 5, 25),
    )

    rejected_rows = _read_rows(queue_dir / "rejected_updates.csv")
    assert rejected_rows[0]["proposal_id"] == "PROP0001"
    assert rejected_rows[0]["rejection_reason"] == "Not strong enough."
    assert rejected_rows[0]["rejected_by"] == "Eric"
    assert rejected_rows[0]["rejected_date"] == "2026-05-25"
    assert rejected_rows[0]["notes"] == "Reviewed manually."


def test_rejecting_updates_review_status_to_rejected(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal("PROP0001", "rejected", queue_dir, config, reviewer="Eric", reason="No.")

    assert _read_rows(queue_dir / "proposed_updates.csv")[0]["review_status"] == "rejected"


def test_deferring_proposed_update_appends_correct_row_to_deferred_updates(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal(
        "PROP0001",
        "deferred",
        queue_dir,
        config,
        reviewer="Eric",
        reason="Needs later review.",
        revisit_date="2026-06-01",
        reviewed_on=date(2026, 5, 25),
    )

    deferred_rows = _read_rows(queue_dir / "deferred_updates.csv")
    assert deferred_rows[0]["proposal_id"] == "PROP0001"
    assert deferred_rows[0]["deferral_reason"] == "Needs later review."
    assert deferred_rows[0]["revisit_date"] == "2026-06-01"
    assert deferred_rows[0]["deferred_by"] == "Eric"
    assert deferred_rows[0]["deferred_date"] == "2026-05-25"


def test_deferring_updates_review_status_to_deferred(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal("PROP0001", "deferred", queue_dir, config, reviewer="Eric", reason="Later.")

    assert _read_rows(queue_dir / "proposed_updates.csv")[0]["review_status"] == "deferred"


def test_already_reviewed_proposals_cannot_be_reviewed_again(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)
    review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric")

    result = review_proposal("PROP0001", "rejected", queue_dir, config, reviewer="Eric", reason="No.")

    assert result["overall_status"] == "fail"
    assert any("already exists" in error or "already marked" in error for error in result["errors"])


def test_proposal_already_present_in_target_review_queue_cannot_be_reviewed_again(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)
    _append_queue_row(queue_dir / "approved_updates.csv", "approved_updates", {"proposal_id": "PROP0001"})

    result = review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric")

    assert result["overall_status"] == "fail"
    assert any("already exists in approved_updates.csv" in error for error in result["errors"])


def test_missing_proposal_id_fails_clearly(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    result = review_proposal("PROP9999", "approved", queue_dir, config, reviewer="Eric")

    assert result["overall_status"] == "fail"
    assert any("Proposal ID not found" in error for error in result["errors"])


def test_review_action_writes_to_change_log(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    review_proposal(
        "PROP0001",
        "approved",
        queue_dir,
        config,
        reviewer="Eric",
        reviewed_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    change_rows = _read_rows(queue_dir / "change_log.csv")
    assert change_rows[0]["operation"] == "review_proposal:approved"
    assert change_rows[0]["status"] == "success"


def test_review_action_writes_markdown_and_json_reports(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)
    result = review_proposal("PROP0001", "approved", queue_dir, config, reviewer="Eric")

    markdown_path, json_path = write_review_report(
        result,
        tmp_path / "reports",
        written_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    assert markdown_path.name == "proposal_review_PROP0001_approved_2026-05-25_153000.md"
    assert json_path.exists()
    assert "Proposal Review Report" in markdown_path.read_text(encoding="utf-8")


def test_list_proposals_shows_proposed_items(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)

    rows = list_proposals(queue_dir, config)
    table = render_proposals_table(rows)

    assert len(rows) == 1
    assert "PROP0001" in table
    assert "Example evidence" in table


def test_list_proposals_status_filter_filters_correctly(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)
    _append_queue_row(queue_dir / "proposed_updates.csv", "proposed_updates", _proposal_row({"proposal_id": "PROP0002", "review_status": "approved"}))

    rows = list_proposals(queue_dir, config, status="proposed")

    assert [row["proposal_id"] for row in rows] == ["PROP0001"]


def test_list_proposals_cli_prints_table(tmp_path: Path, capsys) -> None:
    config, queue_dir = _setup_queue_with_proposal(tmp_path)
    config["queues"]["base_dir"] = str(queue_dir)
    config_path = tmp_path / "config.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    exit_code = main(["list-proposals", "--config", str(config_path), "--status", "proposed"])

    assert exit_code == 0
    assert "PROP0001" in capsys.readouterr().out


def _setup_queue_with_proposal(tmp_path: Path) -> tuple[dict, Path]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    init_queues(queue_dir, config)
    _append_queue_row(queue_dir / "proposed_updates.csv", "proposed_updates", _proposal_row())
    return config, queue_dir


def _proposal_row(overrides: dict[str, str] | None = None) -> dict[str, str]:
    row = {
        "proposal_id": "PROP0001",
        "claim_id": "C001",
        "source_id": "SRC0001",
        "evidence_argument": "Example evidence argument.",
        "category": "Example",
        "source_book": "Example Source",
        "suggested_weight_0_5": "3",
        "EC_MI5": "Likely / probable",
        "PC_MI5": "Roughly even chance",
        "notes": "Original note.",
        "review_status": "proposed",
    }
    if overrides:
        row.update(overrides)
    return row


def _append_queue_row(path: Path, queue_name: str, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[queue_name])
        writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[queue_name]})


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
