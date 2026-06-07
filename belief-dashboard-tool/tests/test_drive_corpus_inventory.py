from __future__ import annotations

import json
from pathlib import Path

import pytest

from belief_dashboard_agentflows.cli import main as agentflow_main
import belief_dashboard_agentflows.flows.drive_corpus_inventory as drive_inventory
from belief_dashboard_agentflows.flows.drive_corpus_inventory import (
    DriveAccessUnavailable,
    DriveInventoryProvider,
    DriveItem,
    GoogleApiDriveInventoryProvider,
    ProviderStatus,
    parse_drive_folder_id,
    render_drive_auth_check_markdown,
    run_drive_auth_check,
    run_drive_corpus_inventory,
)


class FakeDriveProvider(DriveInventoryProvider):
    name = "fake-drive"

    def __init__(self, items: list[DriveItem] | None = None, *, available: bool = True) -> None:
        self.items = items or []
        self.available = available

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, self.available, "fake provider available" if self.available else "fake unavailable")

    def list_folder_tree(
        self,
        folder_id: str,
        *,
        max_depth: int | None,
        max_items: int | None,
        max_files: int | None = None,
        include_trashed: bool = False,
        corpus: str = "",
    ) -> list[DriveItem]:
        if not self.available:
            raise DriveAccessUnavailable(self.status())
        return [DriveItem(**{**item.__dict__, "corpus": corpus}) for item in self.items]


def test_cli_requires_drive_folder_id_or_url(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        agentflow_main(["drive-corpus-inventory", "--project-dir", str(tmp_path), "--corpus", "youtube", "--background-safe"])

    assert "--drive-folder-id" in capsys.readouterr().err


def test_folder_url_parser_extracts_folder_id() -> None:
    assert parse_drive_folder_id("https://drive.google.com/drive/folders/abc123") == "abc123"
    assert parse_drive_folder_id("https://drive.google.com/drive/u/0/folders/abc123?usp=sharing") == "abc123"
    assert parse_drive_folder_id("https://drive.google.com/open?id=abc123") == "abc123"


def test_command_writes_markdown_json_files_json_and_manifest(tmp_path: Path) -> None:
    provider = FakeDriveProvider(
        [
            DriveItem(
                name="Mosaic YT Transcripts",
                id="folder-1",
                mime_type="application/vnd.google-apps.folder",
                item_type="folder",
                relative_path="Mosaic YT Transcripts",
                depth=1,
            ),
            DriveItem(
                name="combined_youtube_all_entries.csv",
                id="file-1",
                mime_type="text/csv",
                item_type="file",
                relative_path="combined_youtube_all_entries.csv",
                size_bytes=120,
                modified_time="2026-06-01T00:00:00Z",
                depth=1,
            ),
        ]
    )

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="youtube",
        background_safe=True,
        project_dir=tmp_path,
        output_root=tmp_path / "reports" / "agentflow_runs" / "drive_inventory",
        run_id="youtube_test",
        provider=provider,
    )

    assert report["status"] == "passed"
    assert Path(report["output_files"]["markdown_report"]).is_file()
    assert Path(report["output_files"]["json_report"]).is_file()
    assert Path(report["output_files"]["files_json"]).is_file()
    assert Path(report["output_files"]["manifest"]).is_file()
    assert report["counts"]["folders"] == 1
    assert report["counts"]["files"] == 1

    files_json = json.loads(Path(report["output_files"]["files_json"]).read_text(encoding="utf-8"))
    assert files_json["items"][0]["source_system"] == "google_drive"
    assert files_json["items"][1]["name"] == "combined_youtube_all_entries.csv"


def test_manifest_is_metadata_only_and_preserves_existing_content(tmp_path: Path) -> None:
    manifest_path = tmp_path / "data/source_manifests/youtube_drive_archive_manifest.md"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("# Existing Manifest\n\nKeep this note.\n", encoding="utf-8")

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="youtube",
        background_safe=True,
        project_dir=tmp_path,
        manifest_path=manifest_path,
        run_id="manifest_test",
        provider=FakeDriveProvider([DriveItem(name="raw.txt", id="file-1", item_type="file", depth=1)]),
    )

    manifest = manifest_path.read_text(encoding="utf-8")
    assert "Keep this note." in manifest
    assert "Latest Drive Inventory Run" in manifest
    assert "metadata-only" in manifest
    assert "raw archive files" in manifest
    assert "raw.txt" not in manifest
    assert report["output_files"]["manifest"] == str(manifest_path)


def test_unavailable_provider_writes_failure_reports(tmp_path: Path) -> None:
    report = run_drive_corpus_inventory(
        drive_folder_id="fake-folder-id",
        corpus="youtube",
        background_safe=True,
        project_dir=tmp_path,
        run_id="unavailable",
        provider=FakeDriveProvider(available=False),
    )

    assert report["status"] == "unavailable"
    assert "fake unavailable" in report["warnings"]
    assert Path(report["output_files"]["markdown_report"]).is_file()
    assert Path(report["output_files"]["json_report"]).is_file()
    assert Path(report["output_files"]["unavailable_report"]).is_file()
    assert Path(report["output_files"]["manifest"]).is_file()


def test_missing_deps_still_report_unavailable_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drive_inventory, "find_spec", lambda name: None)

    report = run_drive_auth_check(provider=FakeDriveProvider(available=False))  # type: ignore[arg-type]

    assert report["status"] == "unavailable"
    assert report["dependency_status"]["available"] is False
    assert "fake unavailable" in report["provider"]["reason"]


def test_auth_check_does_not_print_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_path = tmp_path / "super-secret-service-account.json"
    secret_path.write_text('{"private_key":"SECRET_VALUE"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(secret_path))

    report = run_drive_auth_check(provider=FakeDriveProvider(available=False))  # type: ignore[arg-type]
    markdown = render_drive_auth_check_markdown(report)

    assert "SECRET_VALUE" not in markdown
    assert str(secret_path) not in markdown
    assert "super-secret-service-account.json" not in markdown
    assert "[redacted]" in markdown
    assert report["safety"]["credential_contents_printed"] is False


def test_cli_auth_check_reports_missing_deps_without_traceback(capsys) -> None:
    exit_code = agentflow_main(["drive-auth-check"])
    output = capsys.readouterr().out

    assert exit_code in {0, 1}
    assert "Drive Auth Check" in output
    assert "Traceback" not in output


def test_inventory_does_not_mutate_queues_imports_or_copy_raw_files(tmp_path: Path) -> None:
    queues_dir = tmp_path / "data/queues"
    imports_dir = tmp_path / "data/manual_imports"
    raw_dir = tmp_path / "data/external/drive_cache"
    queues_dir.mkdir(parents=True)
    imports_dir.mkdir(parents=True)
    (queues_dir / "source_dossiers.csv").write_text("source_id,title\n", encoding="utf-8")
    (imports_dir / "candidate.csv").write_text("claim_id\n", encoding="utf-8")
    before_queue = (queues_dir / "source_dossiers.csv").read_text(encoding="utf-8")
    before_import = (imports_dir / "candidate.csv").read_text(encoding="utf-8")

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="youtube",
        background_safe=True,
        project_dir=tmp_path,
        run_id="no_mutation",
        provider=FakeDriveProvider([DriveItem(name="archive.zip", id="file-1", item_type="file", depth=1)]),
    )

    assert (queues_dir / "source_dossiers.csv").read_text(encoding="utf-8") == before_queue
    assert (imports_dir / "candidate.csv").read_text(encoding="utf-8") == before_import
    assert not raw_dir.exists()
    assert report["mutations"]["raw_archive_copied"] is False
    assert report["mutations"]["queues_mutated"] is False
    assert report["mutations"]["imports_mutated"] is False


def test_prophecy_corpus_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="Prophecy corpora"):
        run_drive_corpus_inventory(
            drive_folder_id="folder-id",
            corpus="prophecy",
            background_safe=True,
            project_dir=tmp_path,
            provider=FakeDriveProvider(),
        )

    with pytest.raises(PermissionError, match="Prophecy corpora"):
        run_drive_corpus_inventory(
            drive_folder_id="folder-id",
            corpus="biblical_prophecy_batch",
            background_safe=True,
            project_dir=tmp_path,
            provider=FakeDriveProvider(),
        )


def test_fake_provider_inventory_counts_and_max_items_truncation(tmp_path: Path) -> None:
    provider = FakeDriveProvider(
        [
            DriveItem(name="folder", id="folder", item_type="folder", depth=1),
            DriveItem(name="file1", id="file1", item_type="file", size_bytes=10, depth=1),
            DriveItem(name="file2", id="file2", item_type="file", size_bytes=20, depth=1),
        ]
    )

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="general",
        background_safe=True,
        max_items=2,
        project_dir=tmp_path,
        run_id="truncated",
        provider=provider,
    )

    assert report["counts"]["total_items"] == 2
    assert report["counts"]["folders"] == 1
    assert report["counts"]["files"] == 1
    assert report["limits"]["truncated_by_items"] is True
    assert any("max_items=2" in warning for warning in report["warnings"])


def test_max_files_limits_file_results(tmp_path: Path) -> None:
    provider = FakeDriveProvider(
        [
            DriveItem(name="folder", id="folder", item_type="folder", depth=1),
            DriveItem(name="file1", id="file1", item_type="file", size_bytes=10, depth=1),
            DriveItem(name="file2", id="file2", item_type="file", size_bytes=20, depth=1),
        ]
    )

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="general",
        background_safe=True,
        max_files=1,
        project_dir=tmp_path,
        run_id="file_truncated",
        provider=provider,
    )

    assert report["counts"]["folders"] == 1
    assert report["counts"]["files"] == 1
    assert report["limits"]["truncated_by_files"] is True
    assert any("max_files=1" in warning for warning in report["warnings"])


def test_google_api_provider_uses_mocked_drive_api_metadata_only() -> None:
    service = FakeDriveService(
        [
            {
                "files": [
                    {
                        "id": "folder-1",
                        "name": "transcripts",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["root"],
                        "modifiedTime": "2026-06-01T00:00:00Z",
                        "webViewLink": "https://drive.google.com/folder",
                        "trashed": False,
                    },
                    {
                        "id": "file-1",
                        "name": "video.csv",
                        "mimeType": "text/csv",
                        "size": "42",
                        "parents": ["root"],
                        "modifiedTime": "2026-06-02T00:00:00Z",
                        "md5Checksum": "abc123",
                        "trashed": False,
                    },
                ],
            },
            {"files": []},
        ]
    )
    provider = GoogleApiDriveInventoryProvider()
    provider._service = service
    provider._status = ProviderStatus(provider.name, True, "mocked")

    items = provider.list_folder_tree("root", max_depth=2, max_items=10, max_files=None, corpus="youtube")

    assert len(items) == 2
    assert items[0].item_type == "folder"
    assert items[1].name == "video.csv"
    assert items[1].size_bytes == 42
    assert items[1].md5_checksum == "abc123"
    assert service.download_calls == 0
    assert service.list_calls >= 1


def test_json_report_includes_mocked_drive_file_metadata(tmp_path: Path) -> None:
    provider = FakeDriveProvider(
        [
            DriveItem(
                name="video.csv",
                id="file-1",
                mime_type="text/csv",
                item_type="file",
                size_bytes=42,
                modified_time="2026-06-02T00:00:00Z",
                md5_checksum="abc123",
                depth=1,
            )
        ]
    )

    report = run_drive_corpus_inventory(
        drive_folder_id="folder-id",
        corpus="youtube",
        background_safe=True,
        project_dir=tmp_path,
        run_id="metadata",
        provider=provider,
    )
    files_payload = json.loads(Path(report["output_files"]["files_json"]).read_text(encoding="utf-8"))

    assert files_payload["items"][0]["id"] == "file-1"
    assert files_payload["items"][0]["name"] == "video.csv"
    assert files_payload["items"][0]["size_bytes"] == 42
    assert files_payload["items"][0]["md5_checksum"] == "abc123"


class FakeDriveService:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.list_calls = 0
        self.download_calls = 0

    def files(self) -> "FakeDriveService":
        return self

    def list(self, **kwargs: object) -> "FakeDriveService":
        self.list_calls += 1
        return self

    def execute(self) -> dict[str, object]:
        if not self.pages:
            return {"files": []}
        return self.pages.pop(0)
