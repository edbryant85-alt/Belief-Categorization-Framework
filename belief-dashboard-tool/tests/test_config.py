from __future__ import annotations

from belief_dashboard.config import load_config


def test_config_loads_correctly() -> None:
    config = load_config("config.yaml")

    assert config["workbook"]["default_path"] == (
        "data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx"
    )
    assert "Evidence Log" in config["workbook"]["expected_sheets"]
    assert config["paths"]["reports_dir"] == "reports/workbook_inspection"


def test_evidence_log_header_row_setting_is_read_from_config() -> None:
    config = load_config("config.yaml")

    assert config["workbook"]["evidence_log"]["header_row"] == 3
