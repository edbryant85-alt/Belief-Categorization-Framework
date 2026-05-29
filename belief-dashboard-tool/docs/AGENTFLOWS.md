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

## Golden-Path Smoke Test

Use this smoke sequence before review:

```bash
python -m belief_dashboard_agentflows.cli extraction-qa --source-id SRC0012
python -m belief_dashboard_agentflows.cli proposal-review-assistant --source-id SRC0012
python -m belief_dashboard_agentflows.cli export-preflight
python -m pytest tests/test_agentflow_policies.py tests/test_agentflows.py
```

Expected behavior:

- `extraction-qa` returns `pass`, `needs_cleanup`, or `blocked` without appending queues.
- `proposal-review-assistant` returns review cards or a zero-card report without changing proposal state.
- `export-preflight` may return `not_ready` when the workbook or queues have blockers, but it must not write workbook files.
- the focused test suite should pass.

Common failure modes:

- missing manual import files for the requested source ID;
- import rows that reference missing claim IDs;
- invalid MI5 labels or score values caught by existing CLI validation;
- dirty `main` worktree when `--auto-commit` is requested;
- forbidden path changes when auto-git checks run.
