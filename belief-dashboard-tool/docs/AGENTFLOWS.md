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
