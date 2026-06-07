from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ALLOWED_CORPORA = {"youtube", "mosaic", "watch_history", "source_packets", "manifests", "general"}
PROPHECY_MARKERS = ("prophecy", "prophecies", "prophetic")
DEFAULT_OUTPUT_ROOT = Path("reports/agentflow_runs/drive_inventory")
DEFAULT_MAX_DEPTH = 10
DEFAULT_MAX_ITEMS = 5000


@dataclass(frozen=True)
class DriveItem:
    name: str
    id: str
    parent_id: str | None = None
    parent_ids: list[str] | None = None
    relative_path: str | None = None
    mime_type: str | None = None
    item_type: str = "unknown"
    size_bytes: int | None = None
    modified_time: str | None = None
    created_time: str | None = None
    web_view_link: str | None = None
    md5_checksum: str | None = None
    sha256: str | None = None
    drive_id: str | None = None
    shared_drive_id: str | None = None
    owners: list[str] | None = None
    trashed: bool | None = None
    depth: int = 0
    corpus: str = ""
    source_system: str = "google_drive"


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str = ""


class DriveAccessUnavailable(RuntimeError):
    def __init__(self, status: ProviderStatus):
        super().__init__(status.reason)
        self.status = status


class DriveInventoryProvider:
    name = "google_drive"

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, True, "provider available")

    def list_folder_tree(
        self,
        folder_id: str,
        *,
        max_depth: int | None,
        max_items: int | None,
        include_trashed: bool = False,
        corpus: str = "",
    ) -> list[DriveItem]:
        raise NotImplementedError


class GoogleApiDriveInventoryProvider(DriveInventoryProvider):
    name = "google-api-python-client"

    def __init__(self) -> None:
        self._service: Any | None = None
        self._status: ProviderStatus | None = None

    def status(self) -> ProviderStatus:
        if self._status is not None:
            return self._status
        try:
            import google.auth  # type: ignore[import-not-found]
            from googleapiclient.discovery import build  # type: ignore[import-not-found]
        except ImportError as exc:
            self._status = ProviderStatus(
                self.name,
                False,
                "google-api-python-client/google-auth is not installed. Install Drive API dependencies or use a connector-backed provider.",
            )
            return self._status

        try:
            scopes = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
            credentials, _project = google.auth.default(scopes=scopes)
            self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            credential_hint = "Application Default Credentials"
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                credential_hint = "GOOGLE_APPLICATION_CREDENTIALS service account credentials"
            self._status = ProviderStatus(self.name, True, f"available via {credential_hint}")
            return self._status
        except Exception as exc:
            self._status = ProviderStatus(
                self.name,
                False,
                f"Drive credentials are unavailable or invalid: {exc}",
            )
            return self._status

    def list_folder_tree(
        self,
        folder_id: str,
        *,
        max_depth: int | None,
        max_items: int | None,
        include_trashed: bool = False,
        corpus: str = "",
    ) -> list[DriveItem]:
        status = self.status()
        if not status.available:
            raise DriveAccessUnavailable(status)
        if self._service is None:
            raise DriveAccessUnavailable(ProviderStatus(self.name, False, "Drive service was not initialized."))

        items: list[DriveItem] = []
        queue: list[tuple[str, str, int]] = [(folder_id, "", 0)]
        truncated = False
        while queue:
            current_folder_id, current_path, depth = queue.pop(0)
            if max_depth is not None and depth > max_depth:
                continue
            page_token: str | None = None
            while True:
                query_parts = [f"'{current_folder_id}' in parents"]
                if not include_trashed:
                    query_parts.append("trashed = false")
                response = (
                    self._service.files()
                    .list(
                        q=" and ".join(query_parts),
                        fields=(
                            "nextPageToken, files(id,name,mimeType,size,modifiedTime,createdTime,"
                            "webViewLink,md5Checksum,parents,driveId,owners(displayName),trashed)"
                        ),
                        pageToken=page_token,
                        pageSize=1000,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute()
                )
                for raw in response.get("files", []):
                    if max_items is not None and len(items) >= max_items:
                        truncated = True
                        break
                    item = _drive_item_from_api(raw, current_path=current_path, depth=depth + 1, corpus=corpus)
                    items.append(item)
                    if item.item_type == "folder" and (max_depth is None or item.depth < max_depth):
                        queue.append((item.id, item.relative_path or item.name, item.depth))
                if truncated:
                    return items
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        return items


def run_drive_corpus_inventory(
    *,
    drive_folder_id: str | None = None,
    drive_folder_url: str | None = None,
    corpus: str,
    background_safe: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_items: int = DEFAULT_MAX_ITEMS,
    include_trashed: bool = False,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
    json_only: bool = False,
    markdown_only: bool = False,
    project_dir: str | Path = ".",
    provider: DriveInventoryProvider | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not background_safe:
        raise PermissionError("drive-corpus-inventory requires --background-safe.")
    normalized_corpus = _validate_corpus(corpus)
    if not drive_folder_id and not drive_folder_url:
        raise ValueError("Provide either --drive-folder-id or --drive-folder-url.")
    parsed_folder_id = drive_folder_id or parse_drive_folder_id(drive_folder_url or "")
    if not parsed_folder_id:
        raise ValueError("Could not parse a Google Drive folder ID from the provided URL.")

    project_path = Path(project_dir)
    run_started_at = datetime.now().isoformat(timespec="seconds")
    output_dir = _run_output_dir(project_path / output_root, normalized_corpus, run_id=run_id, overwrite=overwrite)
    provider = provider or GoogleApiDriveInventoryProvider()
    provider_status = provider.status()
    warnings: list[str] = []
    errors: list[str] = []
    items: list[DriveItem] = []
    status = "unavailable"

    if provider_status.available:
        try:
            raw_items = provider.list_folder_tree(
                parsed_folder_id,
                max_depth=max_depth,
                max_items=max_items,
                include_trashed=include_trashed,
                corpus=normalized_corpus,
            )
            items, limit_warnings = _apply_limits(raw_items, max_depth=max_depth, max_items=max_items)
            warnings.extend(limit_warnings)
            status = "passed"
        except DriveAccessUnavailable as exc:
            provider_status = exc.status
            status = "unavailable"
            warnings.append(exc.status.reason)
        except Exception as exc:
            status = "failed"
            errors.append(f"Drive inventory failed: {exc}")
    else:
        warnings.append(provider_status.reason)

    summary = _summarize_items(items)
    manifest = _manifest_path(project_path, normalized_corpus, manifest_path)
    report: dict[str, Any] = {
        "title": "Drive Corpus Inventory Report",
        "flow": "drive-corpus-inventory",
        "status": status,
        "command": "drive-corpus-inventory",
        "command_invocation": _command_invocation(
            drive_folder_id=drive_folder_id,
            drive_folder_url=drive_folder_url,
            corpus=normalized_corpus,
            background_safe=background_safe,
            max_depth=max_depth,
            max_items=max_items,
            include_trashed=include_trashed,
        ),
        "working_directory": str(project_path.resolve()),
        "branch": _git_branch(project_path),
        "git_status_summary": _git_status_summary(project_path),
        "corpus": normalized_corpus,
        "drive_folder_id": drive_folder_id or "",
        "drive_folder_url": drive_folder_url or "",
        "parsed_folder_id": parsed_folder_id,
        "drive_access_available": provider_status.available and status == "passed",
        "provider": asdict(provider_status),
        "limits": {
            "max_depth": max_depth,
            "max_items": max_items,
            "truncated_by_depth": any("max_depth" in warning for warning in warnings),
            "truncated_by_items": any("max_items" in warning for warning in warnings),
        },
        "counts": summary["counts"],
        "size_bytes_known_total": summary["size_bytes_known_total"],
        "output_files": {},
        "mutations": _mutation_summary(),
        "warnings": warnings,
        "errors": errors,
        "next_safe_steps": _next_safe_steps(status),
        "run_started_at": run_started_at,
        "safety": {
            "raw_archive_files_copied": False,
            "queues_mutated": False,
            "imports_mutated": False,
            "proposals_mutated": False,
            "workbook_mutated": False,
            "committed": False,
            "pushed": False,
        },
    }
    paths = _write_reports(
        output_dir=output_dir,
        report=report,
        items=items,
        manifest_path=manifest,
        json_only=json_only,
        markdown_only=markdown_only,
    )
    report["output_files"] = {key: str(value) for key, value in paths.items()}
    _write_manifest(manifest, report)
    report["output_files"]["manifest"] = str(manifest)
    return report


def parse_drive_folder_id(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if "://" not in value and "/" not in value and "?" not in value:
        return value
    parsed = urlparse(value)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if query_id:
        return query_id
    match = re.search(r"/folders/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    return ""


def render_drive_corpus_inventory_markdown(report: dict[str, Any]) -> str:
    output_files = report.get("output_files", {})
    counts = report.get("counts", {})
    lines = [
        "# Drive Corpus Inventory Report",
        "",
        "## Run Summary",
        "",
        f"- Command: `{report.get('command_invocation', report.get('command', ''))}`",
        f"- Working directory: `{report.get('working_directory', '')}`",
        f"- Branch: `{report.get('branch') or 'unknown'}`",
        f"- Git status summary: `{report.get('git_status_summary', '')}`",
        f"- Status: `{report.get('status', '')}`",
        f"- Corpus: `{report.get('corpus', '')}`",
        f"- Drive folder ID: `{report.get('parsed_folder_id', '')}`",
        f"- Drive access available: `{str(report.get('drive_access_available', False)).lower()}`",
        f"- Provider: `{report.get('provider', {}).get('name', '')}`",
        f"- Provider status: `{report.get('provider', {}).get('reason', '')}`",
        "",
        "## Inventory Counts",
        "",
        f"- Folders inventoried: `{counts.get('folders', 0)}`",
        f"- Files inventoried: `{counts.get('files', 0)}`",
        f"- Shortcuts inventoried: `{counts.get('shortcuts', 0)}`",
        f"- Unknown items inventoried: `{counts.get('unknown', 0)}`",
        f"- Total items: `{counts.get('total_items', 0)}`",
        f"- Total known size bytes: `{report.get('size_bytes_known_total', 0)}`",
        f"- Max depth: `{report.get('limits', {}).get('max_depth')}`",
        f"- Max items: `{report.get('limits', {}).get('max_items')}`",
        f"- Truncated by depth: `{str(report.get('limits', {}).get('truncated_by_depth', False)).lower()}`",
        f"- Truncated by items: `{str(report.get('limits', {}).get('truncated_by_items', False)).lower()}`",
        "",
        "## Output Files",
        "",
    ]
    if output_files:
        for label, path in output_files.items():
            lines.append(f"- {label}: `{path}`")
    else:
        lines.append("- Output paths are being written.")
    lines.extend(["", "## Warnings", ""])
    lines.extend(_bullet_lines(report.get("warnings", [])))
    lines.extend(["", "## Errors", ""])
    lines.extend(_bullet_lines(report.get("errors", [])))
    if report.get("status") == "unavailable":
        lines.extend(
            [
                "",
                "## Drive Access Setup",
                "",
                "- Install optional Google Drive API dependencies if this environment does not provide a connector-backed provider.",
                "- Configure Google Application Default Credentials or set `GOOGLE_APPLICATION_CREDENTIALS` for a service account with Drive metadata access.",
                "- Re-run this command with a real Drive folder ID or URL.",
            ]
        )
    lines.extend(
        [
            "",
            "## Safety Confirmation",
            "",
        ]
    )
    for label, value in report.get("mutations", {}).items():
        lines.append(f"- {label}: `{str(value).lower()}`")
    lines.extend(["", "## Next Safe Steps", ""])
    lines.extend(_bullet_lines(report.get("next_safe_steps", [])))
    return "\n".join(lines).rstrip() + "\n"


def _validate_corpus(corpus: str) -> str:
    normalized = corpus.strip().lower()
    if any(marker in normalized for marker in PROPHECY_MARKERS):
        raise PermissionError("Prophecy corpora are explicitly out of scope for Drive inventory.")
    if normalized not in ALLOWED_CORPORA:
        raise ValueError(f"Unsupported corpus: {corpus}. Allowed values: {', '.join(sorted(ALLOWED_CORPORA))}.")
    return normalized


def _apply_limits(items: list[DriveItem], *, max_depth: int, max_items: int) -> tuple[list[DriveItem], list[str]]:
    warnings: list[str] = []
    limited = items
    too_deep = [item for item in limited if item.depth > max_depth]
    if too_deep:
        limited = [item for item in limited if item.depth <= max_depth]
        warnings.append(f"Inventory results were truncated by max_depth={max_depth}.")
    if len(limited) > max_items:
        limited = limited[:max_items]
        warnings.append(f"Inventory results were truncated by max_items={max_items}.")
    return limited, warnings


def _drive_item_from_api(raw: dict[str, Any], *, current_path: str, depth: int, corpus: str) -> DriveItem:
    mime_type = raw.get("mimeType") or ""
    item_type = _item_type(mime_type)
    name = raw.get("name", "")
    relative_path = f"{current_path}/{name}" if current_path else name
    owners = [owner.get("displayName", "") for owner in raw.get("owners", []) if owner.get("displayName")]
    parent_ids = raw.get("parents") or []
    return DriveItem(
        name=name,
        id=raw.get("id", ""),
        parent_id=parent_ids[0] if parent_ids else None,
        parent_ids=parent_ids,
        relative_path=relative_path,
        mime_type=mime_type,
        item_type=item_type,
        size_bytes=int(raw["size"]) if raw.get("size") else None,
        modified_time=raw.get("modifiedTime"),
        created_time=raw.get("createdTime"),
        web_view_link=raw.get("webViewLink"),
        md5_checksum=raw.get("md5Checksum"),
        drive_id=raw.get("driveId"),
        shared_drive_id=raw.get("driveId"),
        owners=owners,
        trashed=raw.get("trashed"),
        depth=depth,
        corpus=corpus,
    )


def _item_type(mime_type: str) -> str:
    if mime_type == "application/vnd.google-apps.folder":
        return "folder"
    if mime_type == "application/vnd.google-apps.shortcut":
        return "shortcut"
    if mime_type:
        return "file"
    return "unknown"


def _summarize_items(items: list[DriveItem]) -> dict[str, Any]:
    counts = {"folders": 0, "files": 0, "shortcuts": 0, "unknown": 0, "total_items": len(items)}
    size_total = 0
    for item in items:
        if item.item_type == "folder":
            counts["folders"] += 1
        elif item.item_type == "file":
            counts["files"] += 1
        elif item.item_type == "shortcut":
            counts["shortcuts"] += 1
        else:
            counts["unknown"] += 1
        if item.size_bytes is not None:
            size_total += item.size_bytes
    return {"counts": counts, "size_bytes_known_total": size_total}


def _run_output_dir(output_root: Path, corpus: str, *, run_id: str | None, overwrite: bool) -> Path:
    resolved_run_id = run_id or f"{corpus}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = output_root / resolved_run_id
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        suffix = datetime.now().strftime("%f")
        output_dir = output_root / f"{resolved_run_id}_{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _manifest_path(project_path: Path, corpus: str, manifest_path: str | Path | None) -> Path:
    if manifest_path:
        path = Path(manifest_path)
        return path if path.is_absolute() else project_path / path
    return project_path / "data" / "source_manifests" / f"{corpus}_drive_archive_manifest.md"


def _write_reports(
    *,
    output_dir: Path,
    report: dict[str, Any],
    items: list[DriveItem],
    manifest_path: Path,
    json_only: bool,
    markdown_only: bool,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if not markdown_only:
        paths["files_json"] = output_dir / "drive_corpus_inventory_files.json"
    if not json_only:
        paths["markdown_report"] = output_dir / "drive_corpus_inventory_report.md"
        if report["status"] == "unavailable":
            paths["unavailable_report"] = output_dir / "drive_corpus_inventory_unavailable.md"
    if not markdown_only:
        paths["json_report"] = output_dir / "drive_corpus_inventory_report.json"
        if report["errors"]:
            paths["errors_json"] = output_dir / "drive_corpus_inventory_errors.json"
    report["output_files"] = {**{key: str(value) for key, value in paths.items()}, "manifest": str(manifest_path)}

    files_payload = {
        "summary": {
            "corpus": report["corpus"],
            "drive_folder_id": report["parsed_folder_id"],
            "counts": report["counts"],
            "size_bytes_known_total": report["size_bytes_known_total"],
        },
        "items": [asdict(item) for item in items],
    }
    if "files_json" in paths:
        paths["files_json"].write_text(json.dumps(files_payload, indent=2) + "\n", encoding="utf-8")
    if not json_only:
        paths["markdown_report"].write_text(render_drive_corpus_inventory_markdown(report), encoding="utf-8")
        if report["status"] == "unavailable":
            paths["unavailable_report"].write_text(render_drive_corpus_inventory_markdown(report), encoding="utf-8")
    if not markdown_only:
        paths["json_report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if report["errors"]:
            paths["errors_json"].write_text(json.dumps({"errors": report["errors"]}, indent=2) + "\n", encoding="utf-8")
    return paths


def _write_manifest(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Drive Source Archive Manifest\n"
    start = "<!-- drive-corpus-inventory:latest:start -->"
    end = "<!-- drive-corpus-inventory:latest:end -->"
    latest = "\n".join(
        [
            start,
            "## Latest Drive Inventory Run",
            "",
            f"- Corpus: `{report['corpus']}`",
            f"- Drive folder ID: `{report['parsed_folder_id']}`",
            f"- Inventory run timestamp: `{report['run_started_at']}`",
            f"- Status: `{report['status']}`",
            f"- Drive access available: `{str(report['drive_access_available']).lower()}`",
            f"- Markdown report: `{report['output_files'].get('markdown_report', '')}`",
            f"- JSON report: `{report['output_files'].get('json_report', '')}`",
            f"- Files JSON: `{report['output_files'].get('files_json', '')}`",
            f"- Folders: `{report['counts']['folders']}`",
            f"- Files: `{report['counts']['files']}`",
            f"- Shortcuts: `{report['counts']['shortcuts']}`",
            f"- Unknown items: `{report['counts']['unknown']}`",
            f"- Total known size bytes: `{report['size_bytes_known_total']}`",
            "",
            "This manifest section is metadata-only and contains no raw archive files.",
            end,
            "",
        ]
    )
    if start in existing and end in existing:
        prefix = existing.split(start, 1)[0].rstrip()
        suffix = existing.split(end, 1)[1].lstrip()
        content = f"{prefix}\n\n{latest}{suffix}".rstrip() + "\n"
    else:
        content = existing.rstrip() + "\n\n" + latest
    path.write_text(content, encoding="utf-8")


def _command_invocation(**kwargs: Any) -> str:
    parts = ["python -m belief_dashboard_agentflows.cli drive-corpus-inventory"]
    if kwargs.get("drive_folder_id"):
        parts.extend(["--drive-folder-id", str(kwargs["drive_folder_id"])])
    if kwargs.get("drive_folder_url"):
        parts.extend(["--drive-folder-url", str(kwargs["drive_folder_url"])])
    parts.extend(["--corpus", str(kwargs["corpus"])])
    if kwargs.get("background_safe"):
        parts.append("--background-safe")
    parts.extend(["--max-depth", str(kwargs["max_depth"]), "--max-items", str(kwargs["max_items"])])
    if kwargs.get("include_trashed"):
        parts.append("--include-trashed")
    return " ".join(parts)


def _git_branch(project_path: Path) -> str:
    result = _git(project_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    return result.strip()


def _git_status_summary(project_path: Path) -> str:
    result = _git(project_path, ["status", "--short"])
    if not result.strip():
        return "clean"
    return f"{len(result.splitlines())} changed/untracked path(s)"


def _git(project_path: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=project_path, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _mutation_summary() -> dict[str, bool]:
    return {
        "raw_archive_copied": False,
        "queues_mutated": False,
        "imports_mutated": False,
        "proposals_mutated": False,
        "workbook_mutated": False,
        "committed": False,
        "pushed": False,
    }


def _next_safe_steps(status: str) -> list[str]:
    if status == "passed":
        return [
            "Review the markdown and files JSON inventory reports.",
            "Choose selected batches for future staging; do not download the full archive.",
            "Keep source registration and import append under explicit human review.",
        ]
    if status == "unavailable":
        return [
            "Configure Drive metadata access through Google Application Default Credentials, GOOGLE_APPLICATION_CREDENTIALS, or a connector-backed provider.",
            "Re-run drive-corpus-inventory with the same folder ID or URL.",
            "Do not fall back to copying the full raw archive into Git.",
        ]
    return ["Review errors, fix provider setup or folder access, and re-run the inventory command."]


def _bullet_lines(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
