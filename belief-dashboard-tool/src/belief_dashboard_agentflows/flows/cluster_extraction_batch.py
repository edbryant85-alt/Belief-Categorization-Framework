from __future__ import annotations

import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from belief_dashboard.extraction_workspace import diagnose_import_shape
from belief_dashboard.schemas import QUEUE_SCHEMAS
from belief_dashboard.utils import timestamp_for_filename
from belief_dashboard_agentflows.cli_runner import CliResult, run_cli_command
from belief_dashboard_agentflows.config_reader import read_config
from belief_dashboard_agentflows.flows.extraction_qa import run_extraction_qa
from belief_dashboard_agentflows.queue_reader import manual_imports_dir, queue_dir, read_queue
from belief_dashboard_agentflows.reports.json import write_json_report


IMPORT_TYPES = ("extracted_claims", "criteria_matrix", "proposed_updates")
MODES = ("prepare", "qa", "dry-run", "report")


def run_cluster_extraction_batch(
    *,
    cluster_id: str,
    project_dir: str | Path = ".",
    config_path: str | Path = "config.yaml",
    source_ids: list[str] | None = None,
    limit: int | None = None,
    mode: str = "report",
    force_workspace: bool = False,
    include_already_imported: bool = False,
    save: bool = True,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"Unsupported cluster extraction batch mode: {mode}")
    project = Path(project_dir)
    config = read_config(project, config_path)
    cluster = _find_cluster(project, config, cluster_id)
    members = _cluster_members(project, config, cluster_id)
    dossiers = {row.get("source_id", ""): row for row in read_queue(project, config, "source_dossiers")}
    selected, skipped = select_cluster_candidates(
        members,
        include_source_ids=source_ids or [],
        limit=limit,
        include_already_imported=include_already_imported,
        imported_source_ids=_fully_imported_source_ids(project, config),
        reviewed_source_ids=_fully_reviewed_source_ids(project, config),
    )
    source_reports = []
    commands_run: list[dict[str, Any]] = []
    for member in selected:
        source_id = member["source_id"]
        source_report, command_summaries = _process_source(
            source_id=source_id,
            member=member,
            dossier=dossiers.get(source_id, {}),
            project_dir=project,
            config_path=config_path,
            config=config,
            mode=mode,
            force_workspace=force_workspace,
        )
        source_reports.append(source_report)
        commands_run.extend(command_summaries)

    status_counts = Counter(source["recommended_next_action"] for source in source_reports)
    report = {
        "title": "Cluster Extraction Batch Report",
        "flow": "cluster-extraction-batch",
        "status": _overall_status(source_reports),
        "cluster_id": cluster_id,
        "cluster_title": cluster.get("cluster_title", ""),
        "mode": mode,
        "timestamp": (generated_at or datetime.now()).replace(microsecond=0).isoformat(),
        "source_count_in_cluster": len(members),
        "selected_source_ids": [row["source_id"] for row in selected],
        "skipped_sources": skipped,
        "sources": source_reports,
        "dirty_git_status": _git_status(project),
        "overall_batch_readiness_summary": dict(sorted(status_counts.items())),
        "blockers": _batch_blockers(source_reports),
        "warnings": _batch_warnings(source_reports),
        "recommended_next_command": _batch_next_command(mode, cluster_id),
        "commands_run": commands_run,
    }
    if save:
        markdown_path, json_path = write_cluster_batch_reports(project, cluster_id, report, written_at=generated_at)
        report["markdown_report_path"] = str(markdown_path)
        report["json_report_path"] = str(json_path)
    return report


def select_cluster_candidates(
    members: list[dict[str, str]],
    *,
    include_source_ids: list[str],
    limit: int | None,
    include_already_imported: bool,
    imported_source_ids: set[str],
    reviewed_source_ids: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    explicit = {source_id for source_id in include_source_ids if source_id}
    enriched = [dict(member) for member in members if member.get("source_id")]
    for member in enriched:
        member["already_imported"] = member.get("source_id", "") in imported_source_ids
        member["fully_reviewed"] = member.get("source_id", "") in reviewed_source_ids
    selected_pool = []
    skipped = []
    for member in enriched:
        source_id = member["source_id"]
        if explicit and source_id not in explicit:
            skipped.append(_skip(member, "not explicitly requested"))
            continue
        if member["already_imported"] and not include_already_imported and source_id not in explicit:
            skipped.append(_skip(member, "already imported"))
            continue
        if member["fully_reviewed"] and not include_already_imported and source_id not in explicit:
            skipped.append(_skip(member, "already fully reviewed"))
            continue
        selected_pool.append(member)
    selected_pool.sort(key=lambda row: (-_score(row.get("priority_0_5")), -_score(row.get("relevance_0_5")), row.get("source_id", "")))
    if limit is not None:
        for member in selected_pool[limit:]:
            skipped.append(_skip(member, "beyond limit"))
        selected_pool = selected_pool[:limit]
    return selected_pool, skipped


def write_cluster_batch_reports(
    project_dir: str | Path,
    cluster_id: str,
    report: dict[str, Any],
    *,
    written_at: datetime | None = None,
) -> tuple[Path, Path]:
    reports_dir = Path(project_dir) / "reports" / "agentflow_runs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp_for_filename(written_at)
    safe_cluster = cluster_id.replace("/", "_")
    markdown_path = reports_dir / f"cluster_extraction_batch_{safe_cluster}_{stamp}.md"
    json_path = reports_dir / f"cluster_extraction_batch_{safe_cluster}_{stamp}.json"
    markdown_path.write_text(render_cluster_batch_markdown(report), encoding="utf-8")
    write_json_report(json_path, report)
    return markdown_path, json_path


def render_cluster_batch_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cluster Extraction Batch Report",
        "",
        f"- Cluster ID: `{report['cluster_id']}`",
        f"- Cluster title: {report.get('cluster_title') or '(blank)'}",
        f"- Mode: `{report['mode']}`",
        f"- Timestamp: `{report['timestamp']}`",
        f"- Source count in cluster: `{report['source_count_in_cluster']}`",
        f"- Selected source IDs: `{', '.join(report['selected_source_ids']) or 'None'}`",
        f"- Status: `{report['status']}`",
        "",
        "## Dirty Git Status",
        *_bullets([f"`{line}`" for line in report.get("dirty_git_status", [])]),
        "",
        "## Skipped Sources",
    ]
    lines.extend(_source_skip_lines(report.get("skipped_sources", [])))
    lines.extend(["", "## Batch Readiness Summary"])
    for key, value in report.get("overall_batch_readiness_summary", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Source Status"])
    for source in report.get("sources", []):
        lines.extend(_source_status_lines(source))
    lines.extend(["", "## Blockers", *_bullets(report.get("blockers", []))])
    lines.extend(["", "## Warnings", *_bullets(report.get("warnings", []))])
    lines.extend(["", "## Recommended Next Command", report.get("recommended_next_command") or "None", ""])
    return "\n".join(lines)


def _process_source(
    *,
    source_id: str,
    member: dict[str, str],
    dossier: dict[str, str],
    project_dir: Path,
    config_path: str | Path,
    config: dict[str, Any],
    mode: str,
    force_workspace: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    commands: list[dict[str, Any]] = []
    source = _base_source_report(source_id, member, dossier, project_dir, config)
    if mode == "prepare":
        if force_workspace or not source["workspace_exists"]:
            result = run_cli_command(
                _workspace_command(source_id, force_workspace, project_dir, config),
                project_dir=project_dir,
                config_path=config_path,
            )
            commands.append(_command_summary(result))
            source["workspace_generation_status"] = "pass" if result.return_code == 0 else "fail"
            source.update(_workspace_status(project_dir, config, source_id))
        else:
            source["workspace_generation_status"] = "already_exists"
    elif mode in {"qa", "dry-run"}:
        _run_diagnosis(source, project_dir, config)
        if source["any_import_csv_exists"]:
            qa = run_extraction_qa(source_id, project_dir=project_dir, config_path=config_path, save=False)
            source["extraction_qa_status"] = qa["status"]
            source["extraction_qa_blockers"] = qa.get("blockers", [])
            source["extraction_qa_warnings"] = qa.get("warnings", [])
            commands.extend(qa.get("commands_run", []))
        _run_validation_and_cleaning(source, project_dir, config_path, mode, commands)
        if mode == "dry-run":
            _run_append_dry_runs(source, project_dir, config_path, commands)
    elif mode == "report":
        _run_diagnosis(source, project_dir, config)
    source["recommended_next_action"] = _source_next_action(source, mode)
    return source, commands


def _base_source_report(
    source_id: str,
    member: dict[str, str],
    dossier: dict[str, str],
    project_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    workspace = _workspace_status(project_dir, config, source_id)
    imports = _import_status(project_dir, config, source_id)
    imported = _imported_status(project_dir, config, source_id)
    duplicate_notes = _duplicate_risk_notes(project_dir, config, source_id)
    return {
        "source_id": source_id,
        "title": dossier.get("title", ""),
        "source_priority": member.get("priority_0_5", ""),
        "source_relevance": member.get("relevance_0_5", ""),
        "source_role": member.get("source_role", ""),
        "member_status": member.get("status", ""),
        "already_imported": imported["already_imported"],
        "already_imported_by_type": imported["by_type"],
        "fully_reviewed": source_id in _fully_reviewed_source_ids(project_dir, config),
        "duplicate_risk_notes": duplicate_notes,
        "shape_diagnosis_status": "not_run",
        "clean_status": {},
        "validation_status": {},
        "dry_run_append_status": {},
        "extraction_qa_status": "not_run",
        "extraction_qa_blockers": [],
        "extraction_qa_warnings": [],
        "workspace_generation_status": "not_run",
        **workspace,
        **imports,
    }


def _workspace_status(project_dir: Path, config: dict[str, Any], source_id: str) -> dict[str, Any]:
    prompt_dir = Path(project_dir) / config["prompt_packets"]["output_dir"]
    prompt_packets = sorted(prompt_dir.glob(f"{source_id}_schema_locked_prompt_packet_*.md"))
    latest_prompt = prompt_packets[-1] if prompt_packets else None
    template_dir = manual_imports_dir(project_dir, config) / "templates"
    template_paths = {
        import_type: template_dir / f"{source_id}_{import_type}_template.csv"
        for import_type in IMPORT_TYPES
    }
    instructions = template_dir / f"{source_id}_template_instructions.md"
    workspace_exists = all(path.exists() for path in template_paths.values()) and instructions.exists()
    truncated = False
    if latest_prompt and latest_prompt.exists():
        truncated = "source text below is truncated" in latest_prompt.read_text(encoding="utf-8", errors="replace").lower()
    return {
        "prompt_packet_exists": latest_prompt is not None,
        "prompt_packet_path": str(latest_prompt) if latest_prompt else "",
        "prompt_packet_count": len(prompt_packets),
        "workspace_exists": workspace_exists,
        "template_paths": {key: str(path) for key, path in template_paths.items()},
        "template_instructions_path": str(instructions),
        "source_packet_truncated": truncated,
    }


def _import_status(project_dir: Path, config: dict[str, Any], source_id: str) -> dict[str, Any]:
    base = manual_imports_dir(project_dir, config)
    status = {}
    exists = []
    for import_type in IMPORT_TYPES:
        path = base / f"{source_id}_{import_type}.csv"
        row_count = _nonblank_row_count(path)
        status[import_type] = {"path": str(path), "exists": path.exists(), "nonblank_rows": row_count}
        exists.append(path.exists())
    return {"import_csvs": status, "all_import_csvs_exist": all(exists), "any_import_csv_exists": any(exists)}


def _run_diagnosis(source: dict[str, Any], project_dir: Path, config: dict[str, Any]) -> None:
    diagnoses = {}
    for import_type, info in source["import_csvs"].items():
        if not info["exists"]:
            diagnoses[import_type] = {"overall_status": "missing", "import_file": info["path"]}
            continue
        diagnoses[import_type] = diagnose_import_shape(import_type, project_dir / info["path"] if not Path(info["path"]).is_absolute() else info["path"], config)
    source["shape_diagnosis"] = diagnoses
    if all(item.get("overall_status") == "pass" for item in diagnoses.values()):
        source["shape_diagnosis_status"] = "pass"
    elif any(item.get("overall_status") == "fail" for item in diagnoses.values()):
        source["shape_diagnosis_status"] = "fail"
    else:
        source["shape_diagnosis_status"] = "missing"


def _run_validation_and_cleaning(
    source: dict[str, Any],
    project_dir: Path,
    config_path: str | Path,
    mode: str,
    commands: list[dict[str, Any]],
) -> None:
    for import_type, info in source["import_csvs"].items():
        if not info["exists"]:
            source["validation_status"][import_type] = {"status": "missing", "file": info["path"]}
            continue
        result = run_cli_command(["validate-import", "--type", import_type, "--file", info["path"]], project_dir=project_dir, config_path=config_path)
        commands.append(_command_summary(result))
        status = "pass" if result.return_code == 0 else "fail"
        source["validation_status"][import_type] = {"status": status, "file": info["path"], "return_code": result.return_code}
        if result.return_code != 0:
            cleaned_path = str(Path(info["path"]).with_name(Path(info["path"]).stem + ".batch.cleaned.csv"))
            clean = run_cli_command(
                ["clean-import", "--type", import_type, "--file", info["path"], "--output", cleaned_path],
                project_dir=project_dir,
                config_path=config_path,
            )
            commands.append(_command_summary(clean))
            clean_status = {"status": "pass" if clean.return_code == 0 else "fail", "file": cleaned_path, "return_code": clean.return_code}
            if clean.return_code == 0:
                cleaned_validate = run_cli_command(
                    ["validate-import", "--type", import_type, "--file", cleaned_path],
                    project_dir=project_dir,
                    config_path=config_path,
                )
                commands.append(_command_summary(cleaned_validate))
                clean_status["validation_status"] = "pass" if cleaned_validate.return_code == 0 else "fail"
                clean_status["validation_return_code"] = cleaned_validate.return_code
                if cleaned_validate.return_code == 0:
                    source["validation_status"][import_type] = {"status": "pass", "file": cleaned_path, "return_code": 0, "original_failed": True}
            source["clean_status"][import_type] = clean_status
        elif mode == "qa":
            source["clean_status"][import_type] = {"status": "not_needed", "file": ""}


def _run_append_dry_runs(
    source: dict[str, Any],
    project_dir: Path,
    config_path: str | Path,
    commands: list[dict[str, Any]],
) -> None:
    if not all(source["validation_status"].get(import_type, {}).get("status") == "pass" for import_type in IMPORT_TYPES):
        for import_type in IMPORT_TYPES:
            source["dry_run_append_status"][import_type] = {"status": "skipped", "reason": "all required import CSVs did not validate"}
        return
    for import_type in IMPORT_TYPES:
        file_path = source["validation_status"][import_type]["file"]
        result = run_cli_command(
            ["append-import", "--type", import_type, "--file", file_path, "--dry-run"],
            project_dir=project_dir,
            config_path=config_path,
        )
        commands.append(_command_summary(result))
        source["dry_run_append_status"][import_type] = {
            "status": "pass" if result.return_code == 0 else "fail",
            "file": file_path,
            "return_code": result.return_code,
        }


def _workspace_command(source_id: str, force_workspace: bool, project_dir: Path, config: dict[str, Any]) -> list[str]:
    output_dir = manual_imports_dir(project_dir, config) / "templates"
    command = ["generate-extraction-workspace", "--source-id", source_id, "--output-dir", str(output_dir)]
    if force_workspace:
        command.append("--force")
    return command


def _find_cluster(project_dir: Path, config: dict[str, Any], cluster_id: str) -> dict[str, str]:
    for row in read_queue(project_dir, config, "evidence_clusters"):
        if row.get("cluster_id") == cluster_id:
            return row
    raise ValueError(f"Cluster not found: {cluster_id}")


def _cluster_members(project_dir: Path, config: dict[str, Any], cluster_id: str) -> list[dict[str, str]]:
    return [row for row in read_queue(project_dir, config, "source_cluster_members") if row.get("cluster_id") == cluster_id]


def _fully_imported_source_ids(project_dir: Path, config: dict[str, Any]) -> set[str]:
    ids_by_type = []
    for queue_name in IMPORT_TYPES:
        ids_by_type.append({row.get("source_id", "") for row in read_queue(project_dir, config, queue_name) if row.get("source_id")})
    if not ids_by_type:
        return set()
    return set.intersection(*ids_by_type)


def _fully_reviewed_source_ids(project_dir: Path, config: dict[str, Any]) -> set[str]:
    by_source: dict[str, list[str]] = {}
    for row in read_queue(project_dir, config, "proposed_updates"):
        source_id = row.get("source_id", "")
        if source_id:
            by_source.setdefault(source_id, []).append(row.get("review_status", ""))
    return {source_id for source_id, statuses in by_source.items() if statuses and all(status in {"approved", "rejected", "deferred"} for status in statuses)}


def _imported_status(project_dir: Path, config: dict[str, Any], source_id: str) -> dict[str, Any]:
    by_type = {}
    for queue_name in IMPORT_TYPES:
        count = sum(1 for row in read_queue(project_dir, config, queue_name) if row.get("source_id") == source_id)
        by_type[queue_name] = count
    return {"already_imported": all(count > 0 for count in by_type.values()), "by_type": by_type}


def _duplicate_risk_notes(project_dir: Path, config: dict[str, Any], source_id: str) -> list[str]:
    notes = []
    base = manual_imports_dir(project_dir, config)
    for import_type, id_field in {"extracted_claims": "claim_id", "criteria_matrix": "claim_id", "proposed_updates": "proposal_id"}.items():
        import_file = base / f"{source_id}_{import_type}.csv"
        if not import_file.exists():
            continue
        existing_ids = {row.get(id_field, "") for row in read_queue(project_dir, config, import_type)}
        manual_ids = {row.get(id_field, "") for row in _read_csv_rows(import_file)}
        overlap = sorted((existing_ids & manual_ids) - {""})
        if overlap:
            notes.append(f"{import_type}: {len(overlap)} IDs already exist in target queue")
    return notes


def _nonblank_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for row in _read_csv_rows(path) if any((value or "").strip() for value in row.values()))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _score(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0


def _skip(member: dict[str, Any], reason: str) -> dict[str, str]:
    return {"source_id": member.get("source_id", ""), "reason": reason, "priority_0_5": str(member.get("priority_0_5", ""))}


def _source_next_action(source: dict[str, Any], mode: str) -> str:
    if mode == "report":
        if not source["workspace_exists"]:
            return "run_prepare_mode"
        if not source["all_import_csvs_exist"]:
            return "generate_or_collect_csvs"
        if source.get("shape_diagnosis_status") == "fail":
            return "fix_csv_shape"
        return "run_qa_mode"
    if mode == "prepare":
        if not source["workspace_exists"]:
            return "resolve_workspace_generation"
        if not source["all_import_csvs_exist"]:
            return "generate_or_collect_csvs"
        return "run_qa_mode"
    if source["already_imported"]:
        return "skip_already_imported_or_review_duplicates"
    if not source["all_import_csvs_exist"]:
        return "collect_missing_csvs"
    if source.get("shape_diagnosis_status") == "fail":
        return "fix_csv_shape"
    if not all(source.get("validation_status", {}).get(import_type, {}).get("status") == "pass" for import_type in IMPORT_TYPES):
        return "fix_validation_errors"
    if mode == "dry-run" and all(source.get("dry_run_append_status", {}).get(import_type, {}).get("status") == "pass" for import_type in IMPORT_TYPES):
        return "ready_for_human_review_before_real_append"
    if mode == "qa":
        return "run_dry_run_mode"
    return "ready_for_next_mode"


def _overall_status(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "empty"
    actions = {source.get("recommended_next_action", "") for source in sources}
    if actions == {"ready_for_human_review_before_real_append"}:
        return "ready"
    if any(action in actions for action in {"fix_validation_errors", "fix_csv_shape", "resolve_workspace_generation"}):
        return "needs_attention"
    return "in_progress"


def _batch_blockers(sources: list[dict[str, Any]]) -> list[str]:
    blockers = []
    for source in sources:
        action = source.get("recommended_next_action")
        if action in {"fix_validation_errors", "fix_csv_shape", "resolve_workspace_generation"}:
            blockers.append(f"{source['source_id']}: {action}")
    return blockers


def _batch_warnings(sources: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for source in sources:
        if source.get("source_packet_truncated"):
            warnings.append(f"{source['source_id']}: prompt packet is truncated")
        for note in source.get("duplicate_risk_notes", []):
            warnings.append(f"{source['source_id']}: {note}")
    return warnings


def _batch_next_command(mode: str, cluster_id: str) -> str:
    if mode == "prepare":
        return f"python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id {cluster_id} --mode qa"
    if mode == "qa":
        return f"python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id {cluster_id} --mode dry-run"
    if mode == "dry-run":
        return "Review the report, then use native append-import commands manually for approved files only."
    return f"python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id {cluster_id} --mode prepare"


def _command_summary(result: CliResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    return {
        "command": " ".join(result.command),
        "return_code": result.return_code,
        "risk": result.policy.risk.value,
        "stdout_preview": result.stdout[:1000],
        "stderr_preview": result.stderr[:1000],
    }


def _git_status(project_dir: Path) -> list[str]:
    result = subprocess.run(["git", "status", "--short"], cwd=project_dir, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return [result.stderr.strip() or "git status failed"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def _source_skip_lines(skipped: list[dict[str, str]]) -> list[str]:
    if not skipped:
        return ["- None"]
    return [f"- `{row['source_id']}`: {row['reason']} (priority {row.get('priority_0_5', '')})" for row in skipped]


def _source_status_lines(source: dict[str, Any]) -> list[str]:
    lines = [
        f"### {source['source_id']} - {source.get('title') or '(untitled)'}",
        "",
        f"- Priority: `{source.get('source_priority', '')}`",
        f"- Role: `{source.get('source_role', '')}`",
        f"- Already imported: `{source.get('already_imported')}`",
        f"- Prompt packet exists: `{source.get('prompt_packet_exists')}`",
        f"- Schema-locked workspace exists: `{source.get('workspace_exists')}`",
        f"- Source packet truncated: `{source.get('source_packet_truncated')}`",
        f"- Import CSVs exist: `{source.get('all_import_csvs_exist')}`",
        f"- Shape diagnosis status: `{source.get('shape_diagnosis_status')}`",
        f"- Extraction QA status: `{source.get('extraction_qa_status')}`",
        f"- Recommended next action: `{source.get('recommended_next_action')}`",
        f"- Duplicate risk notes: {', '.join(source.get('duplicate_risk_notes', [])) or 'None'}",
        "",
        "| import_type | csv_exists | rows | validation | clean | dry_run_append |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for import_type in IMPORT_TYPES:
        csv_info = source.get("import_csvs", {}).get(import_type, {})
        validation = source.get("validation_status", {}).get(import_type, {}).get("status", "not_run")
        clean = source.get("clean_status", {}).get(import_type, {}).get("status", "not_run")
        dry_run = source.get("dry_run_append_status", {}).get(import_type, {}).get("status", "not_run")
        lines.append(f"| {import_type} | {csv_info.get('exists')} | {csv_info.get('nonblank_rows', 0)} | {validation} | {clean} | {dry_run} |")
    lines.append("")
    return lines


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
