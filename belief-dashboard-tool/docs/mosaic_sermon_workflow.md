# Mosaic Sermon Workflow

Mosaic sermon transcripts are treated as `lived_belief_baseline` sources. They are useful for understanding ordinary preached theology, emphasis, pastoral application, and community-level framing, but they are not formal argument sources and are not automatically workbook evidence.

The full Mosaic transcript archive lives outside this repo, currently under:

```text
G:\My Drive\Belief\YT Transcripts\Mosaic YT Transcripts\YT_Transcripts
```

Do not commit the full 428-sermon archive unless that has been explicitly approved. The repo should receive only bounded batch artifacts that are ready for review.

Mosaic sermon files can be inventoried from Google Drive without downloading raw files:

```powershell
python -m belief_dashboard_agentflows.cli drive-corpus-inventory --drive-folder-id FOLDER_ID --corpus mosaic --background-safe
```

Use Drive inventory reports to choose selected batches. Raw archive files should remain in Drive and should not be committed.

## Safety Rules

- Manual-import files are review artifacts only.
- Source packets are staged for human review before any dashboard import.
- Nothing in this workflow appends central queues.
- Nothing in this workflow appends to the workbook.
- Nothing in this workflow modifies workbook files.
- Nothing in this workflow approves, rejects, defers, exports, promotes, or rolls back anything.
- Do not change Mosaic source IDs during staging.
- Do not create or revise extracted claims during staging.
- Run native validation and dry-run append before any real native CLI append.

## Batch 1 Sources

Batch 1 consists of these source packets:

- `SRC-MOSAIC-0070`
- `SRC-MOSAIC-0073`
- `SRC-MOSAIC-0078`
- `SRC-MOSAIC-0080`
- `SRC-MOSAIC-0084`
- `SRC-MOSAIC-0381`
- `SRC-MOSAIC-0385`

## Staged Folder Layout

The guarded staging utility copies only the expected Batch 1 artifacts into:

```text
data/external/mosaic/manifests/
data/external/mosaic/triage/
data/external/mosaic/quality/
data/external/mosaic/manual_import/batch_001/
source_packets/mosaic/batch_001/
```

It also writes:

```text
data/external/mosaic/manual_import/batch_001/staging_manifest_batch_001.csv
```

The staging manifest records each copied file, its source path, destination path, copied flag, and byte size.

## Stage Batch 1

The following legacy staging commands are for a local Windows checkout only, where the `G:\` Drive mount exists. Do not run them in Codespace; use `drive-corpus-inventory` there.

Run dry-run first from the repo root, `belief-dashboard-tool`:

```powershell
python .\tools\stage_mosaic_batch_artifacts.py --source-root "G:\My Drive\Belief\YT Transcripts\Mosaic YT Transcripts\YT_Transcripts" --batch batch_001
```

If every required source file exists and the planned destinations look right, apply the staging copy:

```powershell
python .\tools\stage_mosaic_batch_artifacts.py --source-root "G:\My Drive\Belief\YT Transcripts\Mosaic YT Transcripts\YT_Transcripts" --batch batch_001 --apply
```

Use `--overwrite` only after reviewing existing staged files:

```powershell
python .\tools\stage_mosaic_batch_artifacts.py --source-root "G:\My Drive\Belief\YT Transcripts\Mosaic YT Transcripts\YT_Transcripts" --batch batch_001 --apply --overwrite
```

## Review Path

After staging, inspect `git status` and review the copied files. Treat the staged `manual_import` CSVs as candidates, not as queue state.

To include Mosaic in a background-safe backlog report without extracting claims or appending anything, run:

```powershell
python -m belief_dashboard_agentflows.cli corpus-backlog-runner --corpus mosaic --mode inventory --background-safe
```

The intended path is:

```text
local transcript processing -> source packets -> triage -> manual-import CSVs -> validation/QA -> dry-run append -> human review -> explicit native append only if approved
```

A safe downstream sequence is:

1. Inspect the staged manifest and source packets.
2. Validate the staged manual-import CSVs with the native CLI schema checks.
3. Review claim grounding, packet quality, MI5 labels, weights, and duplicate risks.
4. Run native `append-import --dry-run` only after review.
5. Run real native `append-import` only by explicit human decision.

The Mosaic staging script does not perform any of these downstream dashboard operations.
