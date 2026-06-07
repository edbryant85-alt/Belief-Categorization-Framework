from __future__ import annotations

import json
from pathlib import Path

import pytest

from belief_dashboard_agentflows.cli import main as agentflow_main
from belief_dashboard_agentflows.flows.drive_corpus_inventory import (
    DriveAccessUnavailable,
    DriveInventoryProvider,
    DriveItem,
    ProviderStatus,
    parse_drive_folder_id,
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
