from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import yaml

from belief_dashboard.artifacts import latest_artifact
from belief_dashboard.cli import main
from belief_dashboard.config import load_config


def test_end_to_end_demo_cli_workflow_uses_temp_files(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    demo_dir = project_root / "data" / "sample" / "end_to_end_demo"
    config_path = _prepare_demo_project(tmp_path, demo_dir)
    config = load_config(config_path)
    workbook = tmp_path / "data" / "workbooks" / "demo_workbook.xlsx"
    original_hash = _sha256(workbook)

    assert main(["inspect-workbook", "--config", str(config_path)]) == 0
    assert main(["init-queues", "--config", str(config_path)]) == 0
    assert main(["validate-queues", "--config", str(config_path)]) == 0
    assert main(["register-source", "--config", str(config_path), "--file", str(tmp_path / "data" / "raw_sources" / "sample_source.md")]) == 0
    assert main(["create-claim-template", "--config", str(config_path), "--source-id", "SRC0001"]) == 0
    assert main(["generate-prompt-packet", "--config", str(config_path), "--source-id", "SRC0001"]) == 0

    for import_type, filename in [
        ("extracted_claims", "extracted_claims.csv"),
        ("criteria_matrix", "criteria_matrix.csv"),
        ("proposed_updates", "proposed_updates.csv"),
    ]:
        import_file = tmp_path / "data" / "manual_imports" / filename
        assert main(["validate-import", "--config", str(config_path), "--type", import_type, "--file", str(import_file)]) == 0
        assert main(["append-import", "--config", str(config_path), "--type", import_type, "--file", str(import_file)]) == 0

    assert main(["approve-proposal", "--config", str(config_path), "--proposal-id", "PROP0001", "--reviewer", "Demo Reviewer"]) == 0
    assert main(["preview-workbook-export", "--config", str(config_path)]) == 0
    assert main(["apply-approved-to-workbook", "--config", str(config_path)]) == 0

    latest_output = latest_artifact("output_workbooks", config, tmp_path)
    assert latest_output["exists"] is True
    assert main(["verify-workbook-export", "--config", str(config_path), "--workbook", latest_output["path"]]) == 0
    assert main(["compose-promote-command", "--config", str(config_path), "--latest"]) == 0
    assert main(["operator-preflight", "--config", str(config_path), "--mode", "before-promotion"]) == 0

    assert _sha256(workbook) == original_hash
    assert _row_count(tmp_path / "data" / "queues" / "extracted_claims.csv") == 1
    assert _row_count(tmp_path / "data" / "queues" / "criteria_matrix.csv") == 1
    assert _row_count(tmp_path / "data" / "queues" / "proposed_updates.csv") == 1
    assert _row_count(tmp_path / "data" / "queues" / "approved_updates.csv") == 1
    assert list((tmp_path / "reports" / "workbook_inspection").glob("*.json"))
    assert list((tmp_path / "reports" / "queue_validation").glob("*.json"))
    assert list((tmp_path / "reports" / "prompt_packets").glob("SRC0001_prompt_packet_*.md"))
    assert list((tmp_path / "reports" / "manual_imports").glob("*.json"))
    assert list((tmp_path / "reports" / "reviews").glob("*.json"))
    assert list((tmp_path / "reports" / "workbook_export_preview").glob("*.json"))
    assert list((tmp_path / "reports" / "workbook_exports").glob("*.json"))
    assert list((tmp_path / "reports" / "export_verification").glob("*.json"))
    assert list((tmp_path / "data" / "outputs").glob("*.xlsx"))
    assert list((tmp_path / "data" / "backups").glob("*.xlsx"))


def test_product_readiness_cli_json_and_save(tmp_path: Path, capsys) -> None:
    project_root = Path(__file__).resolve().parents[1]
    demo_dir = project_root / "data" / "sample" / "end_to_end_demo"
    config_path = _prepare_demo_project(tmp_path, demo_dir)
    assert main(["init-queues", "--config", str(config_path)]) == 0
    capsys.readouterr()

    assert main(["product-readiness", "--config", str(config_path), "--format", "json"]) in {0, 1}
    output = json.loads(capsys.readouterr().out)
    assert output["operation"] == "product_readiness"
    assert output["checks"]
    assert main(["product-readiness", "--config", str(config_path), "--save"]) in {0, 1}
    reports_dir = tmp_path / "reports" / "product_readiness"
    assert list(reports_dir.glob("product_readiness_*.md"))
    json_reports = list(reports_dir.glob("product_readiness_*.json"))
    assert json_reports
    data = json.loads(json_reports[-1].read_text(encoding="utf-8"))
    assert data["operation"] == "product_readiness"
    assert data["test_command"] == "python -m pytest"


def _prepare_demo_project(tmp_path: Path, demo_dir: Path) -> Path:
    config = load_config("config.yaml")
    config["workbook"]["default_path"] = "data/workbooks/demo_workbook.xlsx"
    config["paths"]["sample_dir"] = "data/sample"
    config["queues"]["base_dir"] = "data/queues"
    config["prompt_packets"]["output_dir"] = "reports/prompt_packets"
    config["manual_imports"]["input_dir"] = "data/manual_imports"
    config["manual_imports"]["reports_dir"] = "reports/manual_imports"
    config["reviews"]["reports_dir"] = "reports/reviews"
    config["workbook_export"]["reports_dir"] = "reports/workbook_export_preview"
    config["workbook_export"]["final_reports_dir"] = "reports/workbook_exports"
    config["workbook_export"]["output_preview_dir"] = "reports/workbook_export_preview"
    config["workbook_export"]["backups_dir"] = "data/backups"
    config["workbook_export"]["outputs_dir"] = "data/outputs"
    config["export_verification"]["reports_dir"] = "reports/export_verification"
    config["export_verification"]["outputs_dir"] = "data/outputs"
    config["workbook_promotion"]["reports_dir"] = "reports/workbook_promotion"
    config["workbook_promotion"]["archive_dir"] = "data/backups/promoted_archives"
    config["workbook_promotion"]["main_workbook_path"] = "data/workbooks/demo_workbook.xlsx"
    config["workbook_recovery"]["reports_dir"] = "reports/workbook_recovery"
    config["workbook_recovery"]["archive_dir"] = "data/backups/promoted_archives"
    config["workbook_recovery"]["rollback_archive_dir"] = "data/backups/rollback_archives"
    config["workbook_recovery"]["main_workbook_path"] = "data/workbooks/demo_workbook.xlsx"
    config["report_discovery"] = {
        "workbook_exports_dir": "reports/workbook_exports",
        "export_verification_dir": "reports/export_verification",
        "workbook_promotion_dir": "reports/workbook_promotion",
        "workbook_recovery_dir": "reports/workbook_recovery",
    }
    config["artifact_navigation"] = {
        "reports_dir": "reports/artifact_navigation",
        "reports": {
            "workbook_inspection": "reports/workbook_inspection",
            "queue_validation": "reports/queue_validation",
            "prompt_packets": "reports/prompt_packets",
            "manual_imports": "reports/manual_imports",
            "reviews": "reports/reviews",
            "workbook_export_preview": "reports/workbook_export_preview",
            "workbook_exports": "reports/workbook_exports",
            "export_verification": "reports/export_verification",
            "workbook_promotion": "reports/workbook_promotion",
            "workbook_recovery": "reports/workbook_recovery",
        },
        "workbooks": {
            "main": "data/workbooks/demo_workbook.xlsx",
            "outputs": "data/outputs",
            "backups": "data/backups",
            "promoted_archives": "data/backups/promoted_archives",
            "rollback_archives": "data/backups/rollback_archives",
        },
        "default_limit": 10,
    }
    config["command_composition"]["reports_dir"] = "reports/command_guides"
    config["operator_preflight"]["reports_dir"] = "reports/operator_preflight"
    config["product_readiness"] = {
        "reports_dir": "reports/product_readiness",
        "sample_demo_dir": "data/sample/end_to_end_demo",
    }

    for directory in [
        "data/workbooks",
        "data/raw_sources",
        "data/manual_imports",
        "data/outputs",
        "data/backups",
        "data/backups/promoted_archives",
        "data/backups/rollback_archives",
        "data/sample/end_to_end_demo",
        *config["artifact_navigation"]["reports"].values(),
        "reports/artifact_navigation",
        "reports/command_guides",
        "reports/operator_preflight",
        "reports/product_readiness",
    ]:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)

    shutil.copy2(demo_dir / "demo_workbook.xlsx", tmp_path / "data" / "workbooks" / "demo_workbook.xlsx")
    shutil.copy2(demo_dir / "sample_source.md", tmp_path / "data" / "raw_sources" / "sample_source.md")
    for filename in ["demo_workbook.xlsx", "sample_source.md", "extracted_claims.csv", "criteria_matrix.csv", "proposed_updates.csv", "README.md"]:
        shutil.copy2(demo_dir / filename, tmp_path / "data" / "sample" / "end_to_end_demo" / filename)
    for filename in ["extracted_claims.csv", "criteria_matrix.csv", "proposed_updates.csv"]:
        shutil.copy2(demo_dir / filename, tmp_path / "data" / "manual_imports" / filename)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
