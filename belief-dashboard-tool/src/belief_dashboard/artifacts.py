from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.utils import resolve_project_path, timestamp_for_filename
from belief_dashboard.workbook import inspect_workbook


REPORT_PATTERNS = ["*.json", "*.md", "*.csv"]
WORKBOOK_PATTERNS = ["*.xlsx"]


class UnknownArtifactTypeError(ValueError):
    pass


def artifact_type_map(config: dict[str, Any], base_dir: str | Path) -> dict[str, dict[str, Any]]:
    nav = config["artifact_navigation"]
    items: dict[str, dict[str, Any]] = {}
    for artifact_type, directory in nav["reports"].items():
        items[artifact_type] = {
            "artifact_type": artifact_type,
            "directory": resolve_project_path(directory, base_dir=base_dir),
            "patterns": REPORT_PATTERNS,
            "kind": "report",
        }
    workbooks = nav["workbooks"]
    items["output_workbooks"] = {
        "artifact_type": "output_workbooks",
        "directory": resolve_project_path(workbooks["outputs"], base_dir=base_dir),
        "patterns": WORKBOOK_PATTERNS,
        "kind": "workbook",
    }
    items["promoted_archives"] = {
        "artifact_type": "promoted_archives",
        "directory": resolve_project_path(workbooks["promoted_archives"], base_dir=base_dir),
        "patterns": WORKBOOK_PATTERNS,
        "kind": "workbook",
    }
    items["rollback_archives"] = {
        "artifact_type": "rollback_archives",
        "directory": resolve_project_path(workbooks["rollback_archives"], base_dir=base_dir),
        "patterns": WORKBOOK_PATTERNS,
        "kind": "workbook",
    }
    return items


def list_artifact_categories(config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    rows = []
    for artifact_type, definition in artifact_type_map(config, base_dir).items():
        files = _artifact_files(definition)
        latest = files[0] if files else None
        rows.append(
            {
                "artifact_type": artifact_type,
                "directory": str(definition["directory"]),
                "file_count": len(files),
                "latest_file": str(latest) if latest else "",
                "latest_modified_timestamp": _modified_timestamp(latest) if latest else "",
            }
        )
    return {"artifact_type": "artifact_categories", "rows": rows, "count": len(rows)}


def latest_artifact(artifact_type: str, config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    definition = _definition_for(artifact_type, config, base_dir)
    files = _artifact_files(definition)
    if not files:
        return {
            "artifact_type": artifact_type,
            "path": "",
            "modified_timestamp": "",
            "size": 0,
            "parsed_status": "",
            "exists": False,
        }
    latest = files[0]
    summary = _file_metadata(latest)
    summary["artifact_type"] = artifact_type
    summary["parsed_status"] = _status_from_json(latest) if latest.suffix.lower() == ".json" else ""
    return summary


def show_artifact(path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    suffix = artifact_path.suffix.lower()
    summary = _file_metadata(artifact_path)
    if suffix == ".json":
        summary.update(_summarize_json_report(artifact_path))
    elif suffix in {".md", ".markdown"}:
        summary.update(_summarize_markdown(artifact_path))
    elif suffix == ".xlsx":
        summary.update(_summarize_workbook(artifact_path, config))
    else:
        summary["artifact_kind"] = "file"
    return summary


def find_reports(
    artifact_type: str,
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    status: str | None = None,
    contains: str | None = None,
    source_id: str | None = None,
    proposal_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    definition = _definition_for(artifact_type, config, base_dir)
    if definition["kind"] != "report":
        raise UnknownArtifactTypeError(f"Artifact type is not a report type: {artifact_type}")
    filters = [value for value in [contains, source_id, proposal_id] if value]
    rows = []
    for path in _artifact_files(definition):
        text = path.read_text(encoding="utf-8", errors="replace")
        data = _load_json(path) if path.suffix.lower() == ".json" else None
        row_status = _status_from_data(data) if data else ""
        if status and row_status != status:
            continue
        if filters and not all(value in text for value in filters):
            continue
        rows.append(
            {
                "artifact_type": artifact_type,
                "path": str(path),
                "modified_timestamp": _modified_timestamp(path),
                "status": row_status,
                "size": path.stat().st_size,
            }
        )
    if limit is not None:
        rows = rows[:limit]
    return {"artifact_type": artifact_type, "rows": rows, "count": len(rows)}


def find_verified_outputs(
    config: dict[str, Any],
    base_dir: str | Path,
    *,
    status: str | None = "pass",
    latest: bool = False,
) -> dict[str, Any]:
    definition = _definition_for("export_verification", config, base_dir)
    rows = []
    for report in _artifact_files(definition):
        if report.suffix.lower() != ".json":
            continue
        data = _load_json(report)
        if not data:
            continue
        verification_status = _status_from_data(data)
        if status and verification_status != status:
            continue
        workbook_path = Path(str(data.get("output_workbook_path", "")))
        exists = workbook_path.exists()
        verification_timestamp = str(data.get("verification_timestamp", ""))
        rows.append(
            {
                "output_workbook_path": str(workbook_path),
                "verification_report_path": str(report),
                "verification_status": verification_status,
                "verification_timestamp": verification_timestamp,
                "output_workbook_exists": exists,
                "modified_after_verification": _modified_after(workbook_path, verification_timestamp) if exists else False,
            }
        )
    rows.sort(key=lambda row: row["verification_timestamp"], reverse=True)
    if latest and rows:
        rows = rows[:1]
    return {"artifact_type": "verified_outputs", "rows": rows, "count": len(rows)}


def render_table(result: dict[str, Any]) -> str:
    rows = result.get("rows", [])
    if not rows:
        return "No rows found."
    headers = list(rows[0].keys())
    lines = [" | ".join(headers), " | ".join("---" for _ in headers)]
    for row in rows:
        lines.append(" | ".join(str(row.get(header, "")) for header in headers))
    return "\n".join(lines)


def render_summary(summary: dict[str, Any]) -> str:
    lines = []
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{key}: {json.dumps(value, sort_keys=True)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def write_artifact_navigation_report(
    result: dict[str, Any],
    reports_dir: str | Path,
    *,
    report_name: str = "artifact_navigation",
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    markdown_path = reports_path / f"{report_name}_{stamp}.md"
    json_path = reports_path / f"{report_name}_{stamp}.json"
    markdown_path.write_text(_render_navigation_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return markdown_path, json_path


def _definition_for(artifact_type: str, config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    definitions = artifact_type_map(config, base_dir)
    if artifact_type not in definitions:
        known = ", ".join(sorted(definitions))
        raise UnknownArtifactTypeError(f"Unknown artifact type '{artifact_type}'. Known types: {known}")
    return definitions[artifact_type]


def _render_navigation_markdown(result: dict[str, Any]) -> str:
    title = str(result.get("artifact_type") or "artifact_navigation").replace("_", " ").title()
    lines = [f"# {title}", ""]
    if "rows" in result:
        lines.append(render_table(result))
    else:
        lines.append("```text")
        lines.append(render_summary(result))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _artifact_files(definition: dict[str, Any]) -> list[Path]:
    directory = Path(definition["directory"])
    files: list[Path] = []
    for pattern in definition["patterns"]:
        files.extend(path for path in directory.glob(pattern) if path.is_file() and path.name != ".gitkeep")
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _file_metadata(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "modified_timestamp": _modified_timestamp(path),
        "size": path.stat().st_size,
        "exists": path.exists(),
    }


def _summarize_json_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "artifact_kind": "json_report",
            "json_valid": False,
            "parse_error": str(exc),
            "status": "",
            "warnings_count": 0,
            "errors_count": 0,
        }
    if not isinstance(data, dict):
        return {"artifact_kind": "json_report", "json_valid": True, "status": "", "summary": "JSON root is not an object."}
    return {
        "artifact_kind": "json_report",
        "json_valid": True,
        "status": _status_from_data(data),
        "timestamp": _first_present(data, ["verification_timestamp", "promotion_timestamp", "rollback_timestamp", "export_timestamp", "inspection_timestamp", "validation_timestamp", "review_timestamp"]),
        "workbook_path": _first_present(data, ["output_workbook_path", "candidate_output_workbook_path", "main_workbook_path", "workbook_path"]),
        "report_path": _first_present(data, ["verification_report_path", "export_report_path"]),
        "rows_count": _first_present(data, ["approved_rows_considered", "rows_exported", "rows_ready_for_export", "row_count"]),
        "warnings_count": len(data.get("warnings", [])) if isinstance(data.get("warnings", []), list) else 0,
        "errors_count": len(data.get("errors", [])) if isinstance(data.get("errors", []), list) else 0,
    }


def _summarize_markdown(path: Path) -> dict[str, Any]:
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
        if len(lines) >= 8:
            break
    return {"artifact_kind": "markdown_report", "preview_lines": lines}


def _summarize_workbook(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    try:
        inspection = inspect_workbook(path, config)
    except Exception as exc:
        return {"artifact_kind": "workbook", "inspection_status": "fail", "inspection_error": str(exc)}
    evidence = inspection.get("evidence_log", {})
    return {
        "artifact_kind": "workbook",
        "inspection_status": inspection.get("overall_status", ""),
        "sheet_count": len(inspection.get("sheet_names_found", [])),
        "populated_evidence_rows": evidence.get("populated_evidence_rows", 0),
    }


def _status_from_json(path: Path) -> str:
    data = _load_json(path)
    return _status_from_data(data) if data else ""


def _status_from_data(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    return str(data.get("overall_status") or data.get("verification_status") or data.get("status") or "")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _first_present(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def _modified_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()


def _modified_after(path: Path, timestamp: str) -> bool:
    try:
        verified_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0) > verified_at.replace(microsecond=0)
