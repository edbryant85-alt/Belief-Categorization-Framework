# Agentflows

Agentflows are guarded copilots around the existing `belief_dashboard.cli` workflow. They help prepare, validate, summarize, and route artifacts without creating a second path for queue or workbook mutation.

## Allowed Execution Model

Agents may:

- read queue CSV files;
- run allowlisted CLI commands;
- generate markdown and JSON reports;
- write cleaned intermediate manual-import artifacts;
- recommend next safe commands.

Agents may not:

- directly edit the main workbook;
- directly edit central queue CSV files;
- bypass import validation, proposal review, workbook export, or verification;
- promote or roll back without explicit confirmation;
- push branches without explicit confirmation.

## MVP Commands

Run the three report-first workflows from the project root:

```bash
python -m belief_dashboard_agentflows.cli extraction-qa --source-id SRC0012
python -m belief_dashboard_agentflows.cli proposal-review-assistant --source-id SRC0012
python -m belief_dashboard_agentflows.cli export-preflight
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode report
python -m belief_dashboard_agentflows.cli corpus-backlog-runner --corpus mosaic --mode inventory --background-safe
python -m belief_dashboard_agentflows.cli drive-corpus-inventory --drive-folder-id FOLDER_ID --corpus youtube --background-safe
python -m belief_dashboard_agentflows.cli corpus-etl --archive-root "/path/to/synced/archive" --corpus youtube --mode review-pack --background-safe
```

Save reports under `reports/agentflows/`:

```bash
python -m belief_dashboard_agentflows.cli extraction-qa --source-id SRC0012 --save
```

Use JSON output for machine-readable review:

```bash
python -m belief_dashboard_agentflows.cli proposal-review-assistant --source-id SRC0012 --format json
```

## Dry-Run By Default

The MVP agentflow CLI is report-only by default. It does not append imports, approve proposals, export workbooks, mark approved rows as exported, promote, roll back, push, or open pull requests.

Future guarded operations must require explicit confirmation flags:

```bash
--confirm-guarded-write
--confirm-push
--confirm-promotion
```

The current `--auto-commit` option is intentionally conservative. It refuses to run unless the worktree was clean at flow start and the current branch is not `main` or `master`. Auto-push is not default behavior.

## Expected Outputs

`extraction-qa` reports:

- import files found or missing;
- existing CLI validation results;
- cross-file reference blockers;
- duplicate ID blockers;
- quality warnings;
- cleaned candidate files when `clean-import` can produce them;
- the next safest command.

`proposal-review-assistant` reports:

- proposal review cards;
- supporting claim text;
- criteria summary;
- MI5 hypothesis impact;
- risk flags;
- suggested approve, reject, or defer action.

`export-preflight` reports:

- queue validation, doctor, operator preflight, and export preview status;
- approved row count;
- export status distribution;
- blockers and warnings;
- the next safest command.

`cluster-extraction-batch` reports:

- cluster membership and selected source IDs;
- skipped sources and reasons;
- source priority, relevance, role, and already-imported status;
- prompt packet and schema-locked workspace status;
- prompt packet truncation status;
- manual import CSV presence and row counts;
- shape diagnosis, validation, clean-candidate, and dry-run append status by import type;
- duplicate-risk notes for IDs already present in target queues;
- recommended next action for each source.

`corpus-backlog-runner` reports:

- selected corpus inventory for Mosaic, YouTube transcript/watch-history, SRC0018 Reasonable Faith, and general theology/apologetics folders;
- registered and unregistered source candidates;
- existing clusters, packet plans, generated CSV batches, validation reports, and QA reports;
- a human review inbox for batches needing review or repair;
- recommended next safe processing batches;
- explicit exclusion of prophecy files and prophecy corpora.

`drive-corpus-inventory` reports:

- Google Drive metadata for a selected source archive folder;
- folder/file IDs, names, relative paths when determinable, mime types, sizes, timestamps, links, and available metadata hashes;
- provider and credential availability;
- markdown, JSON, files JSON, and source-manifest summaries;
- explicit confirmation that no raw archive files were downloaded and no queues, imports, proposals, or workbooks were mutated.

`corpus-etl` reports:

- local/synced archive metadata inventory;
- candidate source detection and conservative source-type, cluster, and role suggestions;
- registered-source match status from existing source dossiers;
- existing generated batch, validation, QA, and proposal-review state;
- a human review inbox for `review-pack`;
- explicit prophecy exclusions;
- explicit confirmation that no raw archive was copied and no queues, imports, proposals, workbook, commit, or push were mutated.

## Corpus ETL Controller

`corpus-etl` is the guarded source-to-spreadsheet controller. Its purpose is to connect the existing safe pieces into one operator view:

```text
raw archive
-> inventory
-> candidate detection
-> registration planning
-> cluster/batch planning
-> preparation status
-> validation/dry-run state
-> human review inbox
```

It does not bypass human review. It does not register sources, append imports, approve/reject/defer proposals, apply approved updates, export or verify workbooks, promote, roll back, commit, or push. Real ledger changes remain manual/native CLI decisions.

Local/synced archive root mode is the MVP path:

```bash
python -m belief_dashboard_agentflows.cli corpus-etl \
  --archive-root "G:\My Drive\Belief\YT Transcripts" \
  --corpus youtube \
  --mode review-pack \
  --background-safe \
  --max-sources 10
```

The archive root must exist in the runtime environment. A Windows Drive mount such as `G:\My Drive\Belief\YT Transcripts` exists only on the synced Windows machine unless it has been mounted or staged elsewhere. If the path is unavailable, the command writes a safe unavailable report instead of copying raw files into the repo.

Future Drive provider mode is parser-compatible:

```bash
python -m belief_dashboard_agentflows.cli corpus-etl \
  --drive-folder-id FOLDER_ID \
  --corpus youtube \
  --mode inventory \
  --background-safe
```

For the MVP, Drive mode reports provider availability and refuses to download raw Drive files. Use `drive-corpus-inventory` for current Drive metadata inventories.

Supported MVP modes:

- `inventory`: scan an archive root, write `candidate_sources.csv`, markdown, and JSON reports.
- `plan`: inventory plus planning columns for cluster, source role, duplicate risk, priority, and next action.
- `prepare`: plan plus existing registered/staged/generated state inspection; it recommends safe preparation work but does not mutate queues.
- `review-pack`: prepare plus `human_review_inbox.md` for human review.

Future modes are accepted by the parser but refused in the safe MVP:

- `draft`
- `append-approved`
- `export-approved`
- `drive-stage`
- `drive-download`

If `--background-safe` is set, these future modes always refuse.

Outputs are written under:

```text
reports/agentflow_runs/corpus_etl/<corpus>_<mode>_YYYYMMDD_HHMMSS/
```

or, with `--run-id`:

```text
reports/agentflow_runs/corpus_etl/<run-id>/
```

Each normal archive-root run writes:

- `corpus_etl_report.md`
- `corpus_etl_report.json`
- `candidate_sources.csv`

`review-pack` also writes:

- `human_review_inbox.md`

Prophecy exclusion is aggressive. Any file, folder, path, corpus, title, or inferred topic containing `prophecy`, `prophecies`, or `prophetic` is listed in the excluded section and not processed further.

The review pack helps the operator see batches ready for human review, batches needing repair, batches that may be ready for real append only after confirmation, proposals awaiting review, registered candidates ready for extraction, unregistered candidates needing registration decisions, and likely duplicates.

What remains manual:

- interpreting source importance;
- registering selected sources;
- choosing packet batches;
- drafting and reviewing extracted claims;
- running real append after validation and dry-run;
- proposal decisions;
- workbook export, verification, promotion, and rollback.

## Drive Corpus Inventory

Use Drive corpus inventory when Google Drive is the source vault and Codespace is the processing environment. Codespace cannot read a local Windows mount such as `G:\My Drive\Belief\YT Transcripts`; that path exists only on the Windows machine. The bridge inventories Google Drive through a Drive API or connector-backed provider instead of trying to open the Windows filesystem path.

The MVP is inventory/report-only. It writes metadata reports and a source-manifest summary, but it does not download raw transcript files, stage batches, register sources, append imports, review proposals, export workbooks, promote, roll back, commit, or push.

Examples:

```bash
python -m belief_dashboard_agentflows.cli drive-corpus-inventory \
  --drive-folder-id FOLDER_ID \
  --corpus youtube \
  --background-safe

python -m belief_dashboard_agentflows.cli drive-corpus-inventory \
  --drive-folder-url "https://drive.google.com/drive/folders/FOLDER_ID" \
  --corpus mosaic \
  --background-safe
```

Allowed MVP corpora are `youtube`, `mosaic`, `watch_history`, `source_packets`, `manifests`, and `general`. Prophecy corpora are explicitly out of scope and are rejected.

Reports are written under:

```text
reports/agentflow_runs/drive_inventory/
```

Each run writes:

- `drive_corpus_inventory_report.md`
- `drive_corpus_inventory_report.json`
- `drive_corpus_inventory_files.json`
- `drive_corpus_inventory_unavailable.md` when Drive access is unavailable
- `drive_corpus_inventory_errors.json` when errors occur

The matching manifest summary is written under `data/source_manifests/`, such as:

```text
data/source_manifests/youtube_drive_archive_manifest.md
```

If Drive credentials or API libraries are unavailable, the command writes an unavailable report with setup instructions instead of faking success or falling back to raw file copying.

Before a real inventory run from Codespace, install optional Drive metadata dependencies:

```bash
python -m pip install -e ".[drive]"
```

Then check dependency and credential status without reading secrets:

```bash
python -m belief_dashboard_agentflows.cli drive-auth-check
```

For Application Default Credentials, authenticate in the Codespace environment:

```bash
gcloud auth application-default login
```

For service account credentials, keep the JSON file outside Git and point the environment variable at it:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

If using a service account, share the Drive source folder with the service account email. The auth check reports whether dependencies are installed, whether `GOOGLE_APPLICATION_CREDENTIALS` is set, whether the referenced file exists, and whether Drive service construction succeeds. It never prints credential contents.

Future staging should copy only selected batches into ignored cache paths such as:

```text
data/external/drive_cache/
data/external/drive_staging/
```

Raw archive files and credential files must remain outside Git and must not be committed. Staging/downloading raw files is future work; the current bridge is metadata-only.

## Packet Batch Drafting

`packet-batch-draft` creates guarded first-pass manual-import CSV drafts for one explicitly selected section-packet batch. It is an intermediate-write workflow: it may write generated CSV drafts, copied manual-import-ready batch files, validation/QA/dry-run report snippets, markdown/JSON run reports, and a zip artifact. It must not append queues, review proposals, export or verify workbooks with mutation, promote, roll back, commit, or push.

SRC0018 first-batch MVP:

```bash
python -m belief_dashboard_agentflows.cli packet-batch-draft \
  --source-id SRC0018 \
  --batch-name "Introduction / What Good Is Apologetics" \
  --packet-id SRC0018-PKT-002 \
  --packet-id SRC0018-PKT-003 \
  --packet-id SRC0018-PKT-004
```

Convenience alias for this MVP batch:

```bash
python -m belief_dashboard_agentflows.cli packet-batch-draft \
  --source-id SRC0018 \
  --packet-cycle-group "Introduction / What Good Is Apologetics"
```

Outputs:

- `reports/agentflow_runs/SRC0018_intro_apologetics_batch/generated/`
- `data/manual_imports/generated_batches/SRC0018_intro_apologetics/`
- `reports/agentflow_runs/SRC0018_intro_apologetics_batch/packet_batch_draft_report.md`
- `reports/agentflow_runs/SRC0018_intro_apologetics_batch/packet_batch_draft_report.json`
- `reports/agentflow_runs/SRC0018_intro_apologetics_batch/SRC0018_intro_apologetics_batch_artifacts.zip`

Review the generated CSVs before any real append. A safe review sequence is:

```bash
python -m belief_dashboard.cli validate-import --type extracted_claims --file data/manual_imports/generated_batches/SRC0018_intro_apologetics/SRC0018_intro_apologetics_extracted_claims.csv
python -m belief_dashboard.cli validate-import --type criteria_matrix --file data/manual_imports/generated_batches/SRC0018_intro_apologetics/SRC0018_intro_apologetics_criteria_matrix.csv
python -m belief_dashboard.cli validate-import --type proposed_updates --file data/manual_imports/generated_batches/SRC0018_intro_apologetics/SRC0018_intro_apologetics_proposed_updates.csv
```

Only after human review should an operator run native `append-import`, starting with `--dry-run`. The MVP is deliberately scoped to three introduction packets and does not process all 116 SRC0018 packets.

## Cluster Batch Workflow

Use the batch controller for repeatable 10-25 source passes through a cluster:

```bash
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode prepare
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode qa
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode dry-run
```

Modes:

- `report`: read-only inventory; no workspace generation, validation, cleaning, or append dry-runs.
- `prepare`: generates or verifies schema-locked extraction workspaces; does not inspect CSV contents deeply.
- `qa`: diagnoses CSV shape, runs extraction QA, validates import CSVs, and writes separate cleaned candidates when validation fails.
- `dry-run`: runs QA/validation and uses `append-import --dry-run` only when all three required CSVs validate.

The batch controller does not perform real append, proposal review, workbook export, workbook verification, promotion, rollback, git commit, or git push.

## Corpus Backlog Runner

Use the backlog runner when the user wants background-safe catch-up work while staying before queue/workbook mutation:

```bash
python -m belief_dashboard_agentflows.cli corpus-backlog-runner \
  --corpus mosaic \
  --mode inventory \
  --background-safe

python -m belief_dashboard_agentflows.cli corpus-backlog-runner \
  --corpus reasonable_faith \
  --mode plan \
  --background-safe

python -m belief_dashboard_agentflows.cli corpus-backlog-runner \
  --corpus youtube \
  --mode inventory \
  --background-safe
```

Implemented safe modes:

- `inventory`: discover registered sources, likely candidate files, staged folders, and generated batches.
- `plan`: inventory plus next-batch recommendations from existing plans and generated artifacts.
- `report`: consolidated backlog dashboard.

Use repeatable `--corpus` for multiple corpora, or `--corpus all` for the supported MVP set. Use `--exclude-corpus NAME` to keep a corpus out of a run. Prophecy is excluded by default and is not registered, triaged, packetized, staged, clustered, extracted, or appended by this runner.

Reports are always written under:

```text
reports/agentflow_runs/corpus_backlog/
```

The runner writes only markdown and JSON backlog reports. It does not register sources, mutate queues, append imports, approve/reject/defer proposals, export or verify workbooks with mutation, promote, roll back, commit, or push. Real append/export/review remains human-controlled through the native guarded CLI.

Recommended larger-cluster sequence:

1. Register sources with native `register-source` or `bulk-register-sources`.
2. Assign cluster membership with native cluster commands.
3. Run `cluster-extraction-batch --mode prepare`.
4. Generate or collect manual import CSVs.
5. Run `cluster-extraction-batch --mode qa`.
6. Run `cluster-extraction-batch --mode dry-run`.
7. Human-review the generated rows, warnings, and dry-run output.
8. Run real `append-import` only through the native CLI.
9. Review proposals.
10. Run `export-preflight`.
11. Export, verify, and promote only through the native guarded CLI.

## Golden-Path Smoke Test

Use this smoke sequence before review:

```bash
python -m belief_dashboard_agentflows.cli extraction-qa --source-id SRC0012
python -m belief_dashboard_agentflows.cli proposal-review-assistant --source-id SRC0012
python -m belief_dashboard_agentflows.cli export-preflight
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 5 --mode report
python -m pytest tests/test_agentflow_policies.py tests/test_agentflows.py
```

Expected behavior:

- `extraction-qa` returns `pass`, `needs_cleanup`, or `blocked` without appending queues.
- `proposal-review-assistant` returns review cards or a zero-card report without changing proposal state.
- `export-preflight` may return `not_ready` when the workbook or queues have blockers, but it must not write workbook files.
- `cluster-extraction-batch --mode report` writes a batch report but does not generate workspaces, clean CSVs, append imports, or touch workbooks.
- the focused test suite should pass.

Common failure modes:

- missing manual import files for the requested source ID;
- import rows that reference missing claim IDs;
- invalid MI5 labels or score values caught by existing CLI validation;
- dirty `main` worktree when `--auto-commit` is requested;
- forbidden path changes when auto-git checks run.
