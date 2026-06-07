# YouTube Transcript Source Archive

## Archive Location

Archive name: YouTube Transcript Source Archive

Local Drive path:

```text
G:\My Drive\Belief\YT Transcripts
```

Codespace cannot read this Windows path directly. Repo-side inventory should use a Google Drive API or connector-backed archive bridge with a Drive folder ID or URL.

## Purpose

External source vault for YouTube transcripts, watch history, Mosaic sermon packages, and related source-processing files.

## Repo Policy

The raw archive stays outside Git. The repo stores manifests, staging scripts, source IDs, queue data, reports, and selected staged batch artifacts only.

Do not copy the full Google Drive archive into this repo. Do not commit raw transcript archives.

## Known Likely Subfolders

- `Mosaic YT Transcripts`
- `transcripts`
- `transcripts_v2`
- Any watch-history or transcript input folders found during archive checks

## Known Likely Files

- `combined_youtube_all_entries.csv`
- `combined_youtube_transcript_input.csv`
- `combined_youtube_watchlist.md`
- `dan_mcclellan_watch_history_titles.md`
- `README_youtube_transcripts.md`
- `download_youtube_transcripts.py`
- `download_youtube_transcripts_v2.py`

## Mosaic Expected Nested Folder

```text
G:\My Drive\Belief\YT Transcripts\Mosaic YT Transcripts\YT_Transcripts
```

## Safe Workflow

1. Use this manifest to identify the external source vault.
2. Run Drive corpus inventory from Codespace with `drive-corpus-inventory`.
3. Stage only selected batches into repo-side review folders.
4. Run background-safe inventory or corpus backlog tools after staging.
5. Register sources, append imports, mutate queues, or touch workbooks only through explicit downstream operator steps.

<!-- drive-corpus-inventory:latest:start -->
## Latest Drive Inventory Run

- Corpus: `youtube`
- Drive folder ID: `fake-folder-id`
- Inventory run timestamp: `2026-06-07T17:32:44`
- Status: `unavailable`
- Drive access available: `false`
- Markdown report: `reports/agentflow_runs/drive_inventory/youtube_20260607_173244/drive_corpus_inventory_report.md`
- JSON report: `reports/agentflow_runs/drive_inventory/youtube_20260607_173244/drive_corpus_inventory_report.json`
- Files JSON: `reports/agentflow_runs/drive_inventory/youtube_20260607_173244/drive_corpus_inventory_files.json`
- Folders: `0`
- Files: `0`
- Shortcuts: `0`
- Unknown items: `0`
- Total known size bytes: `0`

This manifest section is metadata-only and contains no raw archive files.
<!-- drive-corpus-inventory:latest:end -->
