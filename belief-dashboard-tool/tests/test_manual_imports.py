from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from belief_dashboard.config import load_config
from belief_dashboard.dossiers import register_source
from belief_dashboard.manual_imports import (
    append_manual_import,
    clean_manual_import,
    queue_summary,
    validate_manual_import,
    write_manual_import_report,
)
from belief_dashboard.queues import init_queues
from belief_dashboard.schemas import QUEUE_SCHEMAS


def test_valid_extracted_claims_import_passes_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "manual" / "SRC0001_extracted_claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "evidence"}])

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "pass"
    assert result["row_count"] == 1


def test_invalid_extracted_claims_header_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "bad.csv"
    import_path.write_text("claim_id,source_id\nC001,SRC0001\n", encoding="utf-8")

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert result["header_status"] == "fail"


def test_utf8_bom_import_header_validates(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims_bom.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "evidence"}])
    import_path.write_bytes(b"\xef\xbb\xbf" + import_path.read_bytes())

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "pass"


def test_invalid_claim_type_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "rumor"}])

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("claim_type has invalid value" in error for error in result["errors"])


def test_valid_criteria_matrix_import_passes_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "criteria.csv"
    _write_import(import_path, "criteria_matrix", [{"claim_id": "C001", "source_id": "SRC0001", "relevance_0_5": "4"}])

    result = validate_manual_import("criteria_matrix", import_path, queue_dir, config)

    assert result["overall_status"] == "pass"


def test_out_of_range_criteria_score_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "criteria.csv"
    _write_import(import_path, "criteria_matrix", [{"claim_id": "C001", "source_id": "SRC0001", "relevance_0_5": "6"}])

    result = validate_manual_import("criteria_matrix", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("relevance_0_5 must be between 0 and 5" in error for error in result["errors"])


def test_valid_proposed_updates_import_passes_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "proposed.csv"
    _write_import(
        import_path,
        "proposed_updates",
        [
            {
                "proposal_id": "P001",
                "claim_id": "C001",
                "source_id": "SRC0001",
                "evidence_argument": "A claim.",
                "category": "Example",
                "source_book": "Example Source",
                "suggested_weight_0_5": "3",
                "EC_MI5": "Likely / probable",
                "review_status": "proposed",
            }
        ],
    )

    result = validate_manual_import("proposed_updates", import_path, queue_dir, config)

    assert result["overall_status"] == "pass"


def test_invalid_mi5_label_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "proposed.csv"
    _write_import(import_path, "proposed_updates", [_valid_proposal_row({"EC_MI5": "Certain-ish"})])

    result = validate_manual_import("proposed_updates", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("EC_MI5 has invalid value" in error for error in result["errors"])


def test_out_of_range_suggested_weight_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "proposed.csv"
    _write_import(import_path, "proposed_updates", [_valid_proposal_row({"suggested_weight_0_5": "-1"})])

    result = validate_manual_import("proposed_updates", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("suggested_weight_0_5 must be between 0 and 5" in error for error in result["errors"])


def test_duplicate_ids_within_import_file_fail_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(
        import_path,
        "extracted_claims",
        [
            {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."},
            {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "Another claim."},
        ],
    )

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert result["duplicate_id_status"] == "fail"


def test_duplicate_ids_already_present_in_target_queue_fail_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "Existing."})
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "Imported."}])

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert any("already exists in target queue" in error for error in result["errors"])
    assert any("safe" in error for error in result["errors"])


def test_clean_import_normalizes_src0001_manual_csv_values(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    claims_path = tmp_path / "SRC0001_extracted_claims.csv"
    cleaned_claims = tmp_path / "SRC0001_extracted_claims_cleaned.csv"
    _write_import(
        claims_path,
        "extracted_claims",
        [
            {
                "claim_id": "C001",
                "source_id": "SRC0001",
                "claim_text": "A claim.",
                "claim_type": "metaphysical; moral; interpretive",
                "status": "extracted",
            }
        ],
    )

    result = clean_manual_import("extracted_claims", claims_path, cleaned_claims, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_claims)

    assert result["overall_status"] == "pass"
    assert cleaned_rows[0]["claim_type"] == "metaphysical_claim"
    assert cleaned_rows[0]["status"] == "proposed"
    assert "Original multi-label claim_type" in cleaned_rows[0]["uncertainty_notes"]


def test_clean_import_normalizes_human_readable_claim_type_labels(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    claims_path = tmp_path / "SRC0001_extracted_claims.csv"
    cleaned_claims = tmp_path / "SRC0001_extracted_claims_cleaned.csv"
    _write_import(
        claims_path,
        "extracted_claims",
        [
            {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "metaphysical claim"},
            {"claim_id": "C002", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "moral/social claim"},
            {"claim_id": "C003", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "historical/interpretive claim"},
            {"claim_id": "C004", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "counter-defeater claim"},
            {"claim_id": "C005", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "practical claim"},
        ],
    )

    result = clean_manual_import("extracted_claims", claims_path, cleaned_claims, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_claims)

    assert result["overall_status"] == "pass"
    assert [row["claim_type"] for row in cleaned_rows] == [
        "metaphysical_claim",
        "moral_claim",
        "historical_claim",
        "counter_defeater",
        "moral_claim",
    ]
    assert validate_manual_import("extracted_claims", cleaned_claims, queue_dir, config)["overall_status"] == "pass"


def test_clean_import_normalizes_src0009_generated_claim_type_labels(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    claims_path = tmp_path / "SRC0009_extracted_claims.csv"
    cleaned_claims = tmp_path / "SRC0009_extracted_claims_cleaned.csv"
    _write_import(
        claims_path,
        "extracted_claims",
        [
            {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "limit_claim"},
            {"claim_id": "C002", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "technological_claim"},
            {"claim_id": "C003", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "probabilistic_claim"},
            {"claim_id": "C004", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "trilemma"},
            {"claim_id": "C005", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "epistemic_claim"},
            {"claim_id": "C006", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "sociological_claim"},
            {"claim_id": "C007", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "theological_analogy"},
            {"claim_id": "C008", "source_id": "SRC0001", "claim_text": "A claim.", "claim_type": "conclusion"},
        ],
    )

    result = clean_manual_import("extracted_claims", claims_path, cleaned_claims, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_claims)

    assert result["overall_status"] == "pass"
    assert [row["claim_type"] for row in cleaned_rows] == [
        "interpretive_claim",
        "scientific_claim",
        "argument",
        "argument",
        "interpretive_claim",
        "historical_claim",
        "theological_claim",
        "argument",
    ]
    assert validate_manual_import("extracted_claims", cleaned_claims, queue_dir, config)["overall_status"] == "pass"


def test_clean_import_normalizes_needs_review_and_blank_source_book(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "SRC0001_proposed_updates.csv"
    cleaned_path = tmp_path / "SRC0001_proposed_updates_cleaned.csv"
    _write_import(import_path, "proposed_updates", [_valid_proposal_row({"source_book": "", "review_status": "needs_review"})])

    result = clean_manual_import("proposed_updates", import_path, cleaned_path, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_path)

    assert result["overall_status"] == "pass"
    assert cleaned_rows[0]["review_status"] == "proposed"
    assert cleaned_rows[0]["source_book"] == "Source"


def test_clean_import_normalizes_pending_review_status(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "SRC0009_proposed_updates.csv"
    cleaned_path = tmp_path / "SRC0009_proposed_updates_cleaned.csv"
    _write_import(import_path, "proposed_updates", [_valid_proposal_row({"review_status": "pending_review"})])

    result = clean_manual_import("proposed_updates", import_path, cleaned_path, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_path)

    assert result["overall_status"] == "pass"
    assert cleaned_rows[0]["review_status"] == "proposed"
    assert validate_manual_import("proposed_updates", cleaned_path, queue_dir, config)["overall_status"] == "pass"


def test_clean_import_normalizes_pending_manual_review_and_skips_blank_proposal_rows(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    import_path = tmp_path / "SRC0001_proposed_updates.csv"
    cleaned_path = tmp_path / "SRC0001_proposed_updates_cleaned.csv"
    _write_import(
        import_path,
        "proposed_updates",
        [
            _valid_proposal_row({"review_status": "pending_manual_review"}),
            {},
            {},
        ],
    )

    result = clean_manual_import("proposed_updates", import_path, cleaned_path, queue_dir, config)
    cleaned_rows = _read_rows(cleaned_path)

    assert result["overall_status"] == "warning"
    assert len(cleaned_rows) == 1
    assert cleaned_rows[0]["review_status"] == "proposed"
    assert any("skipped blank proposed_updates row" in warning for warning in result["warnings"])
    assert validate_manual_import("proposed_updates", cleaned_path, queue_dir, config)["overall_status"] == "pass"


def test_missing_referenced_source_id_fails_validation(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC9999", "claim_text": "A claim."}])

    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["overall_status"] == "fail"
    assert result["source_id_reference_status"] == "fail"


def test_append_import_dry_run_appends_nothing(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."}])

    result = append_manual_import("extracted_claims", import_path, queue_dir, config, dry_run=True)

    assert result["overall_status"] == "pass"
    assert result["append_performed"] is False
    assert _row_count(queue_dir / "extracted_claims.csv") == 0


def test_append_import_appends_rows_only_after_validation_passes(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."}])

    result = append_manual_import("extracted_claims", import_path, queue_dir, config)

    assert result["append_performed"] is True
    assert result["rows_appended"] == 1
    assert _row_count(queue_dir / "extracted_claims.csv") == 1


def test_append_import_logs_to_import_log(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."}])

    append_manual_import(
        "extracted_claims",
        import_path,
        queue_dir,
        config,
        appended_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    log_rows = _read_rows(queue_dir / "import_log.csv")
    assert log_rows[-1]["operation"] == "append_import:extracted_claims"
    assert log_rows[-1]["status"] == "success"


def test_manual_import_validation_writes_markdown_and_json_reports(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    reports_dir = tmp_path / "reports"
    import_path = tmp_path / "claims.csv"
    _write_import(import_path, "extracted_claims", [{"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."}])
    result = validate_manual_import("extracted_claims", import_path, queue_dir, config)

    markdown_path, json_path = write_manual_import_report(
        result,
        reports_dir,
        written_at=datetime(2026, 5, 25, 15, 30, 0),
    )

    assert markdown_path.name == "extracted_claims_import_validation_2026-05-25_153000.md"
    assert json_path.exists()
    assert "Manual Import Validation Report" in markdown_path.read_text(encoding="utf-8")


def test_queue_summary_reports_expected_counts(tmp_path: Path) -> None:
    config, queue_dir = _setup_queue_with_source(tmp_path)
    _append_queue_row(queue_dir / "extracted_claims.csv", "extracted_claims", {"claim_id": "C001", "source_id": "SRC0001", "claim_text": "A claim."})
    _append_queue_row(queue_dir / "proposed_updates.csv", "proposed_updates", _valid_proposal_row({"review_status": "proposed"}))
    _append_queue_row(queue_dir / "proposed_updates.csv", "proposed_updates", _valid_proposal_row({"proposal_id": "P002", "review_status": "deferred"}))

    summary = queue_summary(queue_dir, config)

    assert summary["counts"]["source_dossiers"] == 1
    assert summary["counts"]["extracted_claims"] == 1
    assert summary["counts"]["proposed_updates"] == 2
    assert summary["proposed_updates_by_review_status"] == {"deferred": 1, "proposed": 1}


def _setup_queue_with_source(tmp_path: Path) -> tuple[dict, Path]:
    config = load_config("config.yaml")
    queue_dir = tmp_path / "queues"
    source_path = tmp_path / "source.md"
    source_path.write_text("Example source.", encoding="utf-8")
    init_queues(queue_dir, config)
    register_source(source_path, queue_dir, config, registered_on=date(2026, 5, 25))
    return config, queue_dir


def _valid_proposal_row(overrides: dict[str, str] | None = None) -> dict[str, str]:
    row = {
        "proposal_id": "P001",
        "claim_id": "C001",
        "source_id": "SRC0001",
        "evidence_argument": "A claim.",
        "category": "Example",
        "source_book": "Example Source",
        "suggested_weight_0_5": "3",
        "review_status": "proposed",
    }
    if overrides:
        row.update(overrides)
    return row


def _write_import(path: Path, import_type: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[import_type])
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[import_type]})


def _append_queue_row(path: Path, queue_name: str, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_SCHEMAS[queue_name])
        writer.writerow({header: row.get(header, "") for header in QUEUE_SCHEMAS[queue_name]})


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row_count(path: Path) -> int:
    return len(_read_rows(path))
