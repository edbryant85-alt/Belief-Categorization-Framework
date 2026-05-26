# Belief Dashboard Tool

This project is a command-line helper for an existing Bayesian belief dashboard Excel workbook. It can inspect workbook structure and maintain review queue templates that later phases can use for source processing and approved updates.

The tool avoids direct workbook changes until an explicit guarded promotion step. Exports are written to timestamped output copies first, verified, and only then can a verified output workbook replace the configured main workbook.

## Current Capabilities

- Inspect workbook structure and write inspection reports.
- Initialize and validate queue CSV files.
- Register local source files and create manual claim templates.
- Generate prompt packets for manual review workflows.
- Validate and append manual import CSVs.
- Approve, reject, or defer proposed workbook updates.
- Preview approved workbook exports without writing Excel.
- Write approved rows to timestamped output workbook copies.
- Verify output workbook rows against approved queue rows.
- Promote a verified output workbook only through an explicit guarded command.
- Roll back from promoted archives only through an explicit guarded command.
- Navigate reports, workbooks, archives, and verified output candidates.
- Compose ready-to-run promotion and rollback commands without executing them.
- Run operator preflight and product readiness diagnostics.
- Run doctor diagnostics that explain problems and safe repair commands.
- Generate read-only debate-prep summaries from approved evidence.
- Generate printable read-only debate packets with trace appendices.
- Run an end-to-end demo workflow using non-private sample assets.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m belief_dashboard.cli product-readiness
```

## Command Map

Read-only or report-writing checks:

- `inspect-workbook`
- `validate-queues`
- `queue-summary`
- `list-proposals`
- `preview-workbook-export`
- `latest-output-workbook`
- `verify-workbook-export` without `--mark-exported`
- `current-workbook-status`
- `promotion-history`
- `export-history`
- `verification-history`
- `list-promoted-archives`
- `list-artifacts`
- `latest-artifact`
- `show-artifact`
- `find-report`
- `find-verified-output`
- `compose-promote-command`
- `compose-rollback-command`
- `next-safe-commands`
- `operator-preflight`
- `product-readiness`
- `doctor`
- `debate-summary`
- `debate-packet`

Queue-writing commands:

- `init-queues`
- `register-source`
- `append-import`
- `approve-proposal`
- `reject-proposal`
- `defer-proposal`
- `verify-workbook-export --mark-exported`

Workbook-copy writing commands:

- `apply-approved-to-workbook`

Main workbook replacement commands:

- `promote-output-workbook`
- `rollback-workbook`

## Normal Safe Workflow

```bash
python -m belief_dashboard.cli inspect-workbook
python -m belief_dashboard.cli validate-queues
python -m belief_dashboard.cli register-source --file data/raw_sources/example.md
python -m belief_dashboard.cli create-claim-template --source-id SRC0001
python -m belief_dashboard.cli generate-prompt-packet --source-id SRC0001
python -m belief_dashboard.cli validate-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims.csv
python -m belief_dashboard.cli append-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims.csv
python -m belief_dashboard.cli list-proposals
python -m belief_dashboard.cli approve-proposal --proposal-id PROP0001 --reviewer "Reviewer"
python -m belief_dashboard.cli preview-workbook-export
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run
python -m belief_dashboard.cli apply-approved-to-workbook
python -m belief_dashboard.cli find-verified-output
python -m belief_dashboard.cli compose-promote-command --latest
python -m belief_dashboard.cli operator-preflight --mode before-promotion
python -m belief_dashboard.cli doctor --mode before-promotion
```

## Demo Workflow

Demo assets live under `data/sample/end_to_end_demo/`. Run the integration demo with:

```bash
python -m pytest tests/test_end_to_end_demo.py
```

The test copies the demo workbook, source, and manual import CSVs into a temporary project directory before running the workflow. It does not touch private data or the real workbook.

## Real Workbook Workflow

Place the real workbook at the configured `workbook.default_path`, then run `product-readiness`, `inspect-workbook`, and `validate-queues` before registering sources or importing reviewed CSVs. Use `apply-approved-to-workbook --dry-run` before writing any output copy, verify the timestamped output workbook, then use `compose-promote-command --latest` and `operator-preflight --mode before-promotion` before any real promotion.

## Safety Model

The main workbook is not modified by inspection, queue validation, source registration, prompt packets, manual imports, proposal review, export preview, artifact navigation, command composition, operator preflight, product readiness, or doctor diagnostics. Approved updates are written to timestamped output workbook copies first. Main workbook replacement happens only through `promote-output-workbook` or `rollback-workbook`.

Reports are written under `reports/`. Timestamped output workbooks are written under `data/outputs/`. Backups and promoted/rollback archives are written under `data/backups/`. Queue state lives under `data/queues/`.

See also:

- `docs/OPERATOR_WORKFLOW.md`
- `docs/SAFETY_MODEL.md`
- `docs/DEMO_WALKTHROUGH.md`
- `docs/TROUBLESHOOTING.md`
- `docs/DEBATE_SUMMARIES.md`
- `docs/DEBATE_PACKETS.md`

## Phase 1 Scope

- Project scaffold for a Python CLI package.
- Configurable workbook assumptions in `config.yaml`.
- Read-only workbook inspection using `openpyxl`.
- Markdown and JSON inspection reports.
- Harmless sample data files.
- Pytest coverage using a temporary generated workbook.

## Phase 2 Scope

- Queue CSV template initialization under `data/queues/`.
- A reflection journal template under `data/queues/`.
- Queue schema definitions in code.
- Queue validation for required files, CSV header order, MI5 labels, review statuses, and 0-5 numeric fields.
- Markdown and JSON queue validation reports.

## Phase 3 Scope

- Register local raw source files in `source_dossiers.csv`.
- Preserve raw source files unchanged.
- Create source-specific extracted claim CSV templates.
- Generate markdown prompt packets for manual use in ChatGPT Plus.
- Log source registration and prompt packet generation in `import_log.csv`.

## Phase 4 Scope

- Validate manually reviewed ChatGPT CSV output before it enters queue files.
- Dry-run manual imports to preview append behavior.
- Append valid manual imports into `extracted_claims.csv`, `criteria_matrix.csv`, or `proposed_updates.csv`.
- Reject invalid rows clearly without appending anything.
- Log successful append operations in `import_log.csv`.
- Print simple queue summaries.

## Phase 5 Scope

- List proposed updates awaiting review.
- Approve, reject, or defer individual proposals by `proposal_id`.
- Preserve proposed rows while updating only their `review_status`.
- Append transformed review rows to `approved_updates.csv`, `rejected_updates.csv`, or `deferred_updates.csv`.
- Write audit rows to `change_log.csv`.
- Generate markdown and JSON review reports.

## Phase 6 Scope

- Preview approved queue rows against the existing workbook structure.
- Validate approved rows before any Excel-writing phase.
- Map approved rows to Evidence Log input columns.
- Identify formula-driven columns that should be copied down later, not manually overwritten.
- Plan workbook append row numbers and Evidence Log IDs where safe.
- Generate markdown, JSON, and CSV change-plan artifacts.

## Phase 7 Scope

- Validate approved updates using the Phase 6 preview logic.
- Dry-run approved workbook export without writing workbook files.
- Create a timestamped backup copy of the original workbook before real export.
- Create a separate timestamped output workbook under `data/outputs/`.
- Append approved rows only to the output workbook's Evidence Log sheet.
- Copy formula-driven columns down where formulas can be translated safely.
- Write markdown and JSON export reports.
- Append one audit row to `change_log.csv`.

## Phase 8 Scope

- Find the latest timestamped output workbook.
- Verify output workbook rows against approved queue rows.
- Optionally compare against a workbook export JSON report.
- Detect missing exported rows, value mismatches, missing trace metadata, and formula concerns.
- Optionally mark approved queue rows as exported only after verification succeeds.
- Write markdown and JSON export verification reports.

## Phase 9 Scope

- Promote a verified timestamped output workbook into the main workbook location.
- Require a successful Phase 8 verification JSON report before promotion.
- Confirm the verification report refers to the same output workbook being promoted.
- Run basic workbook inspection on the candidate workbook before replacing anything.
- Archive the previous main workbook under `data/backups/promoted_archives/`.
- Preserve the original output workbook under `data/outputs/`.
- Write markdown and JSON promotion reports.
- Append one audit row to `change_log.csv` after real promotion.

## Phase 10 Scope

- Print current workbook status and latest operational artifacts.
- Discover export, verification, promotion, and recovery report history.
- List promoted archive workbooks without deleting or modifying them.
- Dry-run rollback from a selected promoted archive.
- Restore a selected archive only through an explicit rollback command.
- Archive the current main workbook under `data/backups/rollback_archives/` before rollback replacement.
- Write markdown and JSON rollback reports under `reports/workbook_recovery/`.
- Append one rollback audit row to `change_log.csv` after real rollback.

## Phase 11 Scope

- List known artifact categories and their latest files.
- Find the latest artifact for a specific report or workbook type.
- Show concise summaries for JSON, markdown, and workbook artifacts.
- Find reports by type, status, text containment, source ID, or proposal ID.
- Find output workbooks that have successful verification reports.
- Provide JSON output for selector commands where useful.
- Avoid workbook edits, queue edits, promotion, rollback, API calls, and web UI work.

## Phase 12 Scope

- Compose ready-to-run commands for high-stakes promotion and rollback workflows.
- Select explicit artifacts or the latest safe candidate from existing reports and archives.
- Quote paths safely in generated shell commands.
- Print a conservative next-step checklist based on current artifacts.
- Save markdown and JSON command guide reports.
- Never execute promotion, rollback, export, verification, queue mutation, API calls, or web UI work.

## Phase 13 Scope

- Gather a read-only operator preflight packet before high-stakes workflow steps.
- Summarize workbook inspection, queue validation, queue counts, artifact navigation, verified outputs, and command guide recommendations.
- Provide mode-specific checks for before-export, before-verification, before-promotion, and before-rollback workflows.
- Save markdown and JSON preflight reports under `reports/operator_preflight/` only when requested.
- Never modify workbooks, queues, exports, verification state, promotion state, rollback state, API state, or web UI state.

Not included yet:

- OpenAI API integration.
- Paid API calls.
- Automatic AI claim extraction.
- Queue processing beyond template validation.
- Web dashboard.

## Setup

From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Workbook Location

Place your workbook here:

```text
data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx
```

The workbook is not generated by this project. If it is not present, the inspection command will report a clear failure.

## Run Inspection

Using the default path from `config.yaml`:

```bash
python -m belief_dashboard.cli inspect-workbook
```

Using an explicit workbook path:

```bash
python -m belief_dashboard.cli inspect-workbook --workbook path/to/workbook.xlsx
```

The command writes reports to:

```text
reports/workbook_inspection/
```

Each run creates:

- `workbook_inspection_YYYY-MM-DD_HHMMSS.md`
- `workbook_inspection_YYYY-MM-DD_HHMMSS.json`

## Initialize Queues

Create missing queue files:

```bash
python -m belief_dashboard.cli init-queues
```

Run it again safely:

```bash
python -m belief_dashboard.cli init-queues
```

Existing files are skipped. To intentionally replace queue templates:

```bash
python -m belief_dashboard.cli init-queues --force
```

## Validate Queues

```bash
python -m belief_dashboard.cli validate-queues
```

The command writes reports to:

```text
reports/queue_validation/
```

Each run creates:

- `queue_validation_YYYY-MM-DD_HHMMSS.md`
- `queue_validation_YYYY-MM-DD_HHMMSS.json`

Validation checks:

- All required queue files exist.
- CSV headers match the expected schema and order.
- MI5 labels are allowed values.
- Review statuses are allowed values.
- Weight and criteria score fields are blank or numeric from 0 to 5.

## Queue Files

- `source_dossiers.csv`: source-level metadata, summaries, notes, and processing status.
- `extracted_claims.csv`: claims, arguments, objections, defeaters, and related hypothesis notes extracted from sources later.
- `criteria_matrix.csv`: 0-5 review scores for relevance, reliability, clarity, argument strength, and related criteria.
- `proposed_updates.csv`: proposed Evidence Log-style updates awaiting review.
- `approved_updates.csv`: reviewed updates approved for a later Excel-writing phase.
- `rejected_updates.csv`: proposed updates rejected during review.
- `deferred_updates.csv`: proposed updates deferred for later revisit.
- `import_log.csv`: future source/template import operation log.
- `change_log.csv`: future file transformation and workbook-copy change log.
- `reflection_journal.md`: free-form reflection notes for the review process.

## Register A Source

Put raw source files in:

```text
data/raw_sources/
```

Supported file extensions are configured in `config.yaml`: `.txt`, `.md`, and `.csv`.

Example:

```bash
python -m belief_dashboard.cli register-source --file data/raw_sources/example.md
```

With optional metadata:

```bash
python -m belief_dashboard.cli register-source \
  --file data/raw_sources/example.md \
  --source-type book_notes \
  --title "Example Source" \
  --author "Example Author" \
  --url "https://example.com"
```

The command appends a row to:

```text
data/queues/source_dossiers.csv
```

It will not register the same original file path twice unless you pass:

```bash
python -m belief_dashboard.cli register-source --file data/raw_sources/example.md --allow-duplicate
```

If queue files are missing, run:

```bash
python -m belief_dashboard.cli init-queues
```

## Create A Claim Template

After registering a source, create a source-specific extracted-claims template:

```bash
python -m belief_dashboard.cli create-claim-template --source-id SRC0001
```

This writes:

```text
reports/prompt_packets/SRC0001_extracted_claims_template.csv
```

The main `data/queues/extracted_claims.csv` is not filled with blank rows.

## Generate A Prompt Packet

Create a ChatGPT-ready markdown prompt packet:

```bash
python -m belief_dashboard.cli generate-prompt-packet --source-id SRC0001
```

Optionally limit the amount of source text included inline:

```bash
python -m belief_dashboard.cli generate-prompt-packet --source-id SRC0001 --max-characters 12000
```

Prompt packets are saved in:

```text
reports/prompt_packets/
```

Each generated packet includes:

- Source metadata and source text.
- The project hypothesis list.
- MI5 label options.
- Philosophical safeguards.
- Instructions for CSV-ready `extracted_claims.csv`, `criteria_matrix.csv`, and `proposed_updates.csv` rows.

To use it with ChatGPT Plus, open the generated `.md` file, paste the prompt into ChatGPT, and review the response manually. Save any accepted output into the queue CSV files yourself. Do not paste unreviewed model output into the Excel workbook.

## Manual Imports

After reviewing ChatGPT output, save CSV-ready rows under:

```text
data/manual_imports/
```

Typical filenames:

```text
data/manual_imports/SRC0001_extracted_claims.csv
data/manual_imports/SRC0001_criteria_matrix.csv
data/manual_imports/SRC0001_proposed_updates.csv
```

Supported import types:

- `extracted_claims`
- `criteria_matrix`
- `proposed_updates`

Do not import directly into `approved_updates.csv` yet. Approval remains a separate workflow.

## Validate A Manual Import

```bash
python -m belief_dashboard.cli validate-import \
  --type extracted_claims \
  --file data/manual_imports/SRC0001_extracted_claims.csv
```

Other examples:

```bash
python -m belief_dashboard.cli validate-import \
  --type criteria_matrix \
  --file data/manual_imports/SRC0001_criteria_matrix.csv

python -m belief_dashboard.cli validate-import \
  --type proposed_updates \
  --file data/manual_imports/SRC0001_proposed_updates.csv
```

Validation reports are saved under:

```text
reports/manual_imports/
```

Validation checks headers, required IDs, duplicate IDs, source references, claim references, MI5 labels, review statuses, and 0-5 score or weight fields.

## Dry-Run Append

Preview an append without changing queue files:

```bash
python -m belief_dashboard.cli append-import \
  --type extracted_claims \
  --file data/manual_imports/SRC0001_extracted_claims.csv \
  --dry-run
```

Dry runs still create a report and append nothing.

## Append A Valid Import

Append reviewed rows after validation passes:

```bash
python -m belief_dashboard.cli append-import \
  --type extracted_claims \
  --file data/manual_imports/SRC0001_extracted_claims.csv
```

If validation fails, no rows are appended. Successful appends preserve existing queue rows, keep header order, and add a row to `data/queues/import_log.csv`.

## Queue Summary

Print queue counts:

```bash
python -m belief_dashboard.cli queue-summary
```

Also save a markdown summary:

```bash
python -m belief_dashboard.cli queue-summary --save
```

## List Proposals

Show proposals in `data/queues/proposed_updates.csv`:

```bash
python -m belief_dashboard.cli list-proposals
```

Filter by status or source:

```bash
python -m belief_dashboard.cli list-proposals --status proposed
python -m belief_dashboard.cli list-proposals --source-id SRC0001 --limit 10
```

The output includes proposal ID, source ID, claim ID, category, suggested weight, review status, and a short evidence preview.

## Approve A Proposal

```bash
python -m belief_dashboard.cli approve-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric"
```

Optional approval overrides:

```bash
python -m belief_dashboard.cli approve-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric" \
  --weight 4 \
  --category "Philosophical argument" \
  --ec-mi5 "Likely / probable" \
  --pc-mi5 "Roughly even chance" \
  --notes "Reviewed and lightly edited."
```

Approval appends a transformed row to `data/queues/approved_updates.csv`, sets the original proposal `review_status` to `approved`, and writes a `change_log.csv` audit row.

## Reject A Proposal

```bash
python -m belief_dashboard.cli reject-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric" \
  --reason "Reason here"
```

Optional:

```bash
python -m belief_dashboard.cli reject-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric" \
  --reason "Reason here" \
  --notes "Additional audit note."
```

Rejection appends to `data/queues/rejected_updates.csv` and sets the original proposal `review_status` to `rejected`.

## Defer A Proposal

```bash
python -m belief_dashboard.cli defer-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric" \
  --reason "Needs later review"
```

Optional:

```bash
python -m belief_dashboard.cli defer-proposal \
  --proposal-id PROP0001 \
  --reviewer "Eric" \
  --reason "Needs later review" \
  --revisit-date 2026-06-01 \
  --notes "Revisit after related sources are processed."
```

Deferral appends to `data/queues/deferred_updates.csv` and sets the original proposal `review_status` to `deferred`.

Review actions do not delete proposed rows. A proposal cannot be reviewed twice, and a proposal already present in any review target queue is rejected safely.

## Review Reports

Every review action creates markdown and JSON reports under:

```text
reports/reviews/
```

Report filenames look like:

```text
proposal_review_PROP0001_approved_YYYY-MM-DD_HHMMSS.md
proposal_review_PROP0001_approved_YYYY-MM-DD_HHMMSS.json
```

Reports include the proposal ID, action, reviewer, timestamp, source ID, claim ID, target queue, status update result, target append result, warnings, errors, and overall status.

## Preview Workbook Export

Preview approved updates against the workbook without modifying Excel:

```bash
python -m belief_dashboard.cli preview-workbook-export
```

Optional filters:

```bash
python -m belief_dashboard.cli preview-workbook-export --limit 25
python -m belief_dashboard.cli preview-workbook-export --proposal-id PROP0001
python -m belief_dashboard.cli preview-workbook-export --source-id SRC0001
```

Optional explicit paths:

```bash
python -m belief_dashboard.cli preview-workbook-export \
  --workbook data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx \
  --approved-file data/queues/approved_updates.csv
```

Preview artifacts are saved under:

```text
reports/workbook_export_preview/
```

Each run creates:

- `workbook_export_preview_YYYY-MM-DD_HHMMSS.md`
- `workbook_export_preview_YYYY-MM-DD_HHMMSS.json`
- `workbook_export_change_plan_YYYY-MM-DD_HHMMSS.csv`

The change plan shows what Phase 7 would write later: planned workbook row, planned Evidence Log ID when safe, proposal/claim/source IDs, Evidence Log input values, `approved_date` as the Date value, trace metadata in Notes, validation status, and warnings.

The preview validates approved rows against required fields, MI5 labels, 0-5 approved weights, ISO-like approved dates, source references, claim references, proposal references, and workbook input columns. The workbook is still not modified, and no updated workbook copy is created in Phase 6.

## Dry-Run Workbook Export

Validate approved updates and report what would be written without creating backup or output workbook files:

```bash
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run
```

Optional filters:

```bash
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run --limit 25
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run --proposal-id PROP0001
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run --source-id SRC0001
```

## Apply Approved Updates To A Workbook Copy

Write approved updates to a timestamped output workbook copy:

```bash
python -m belief_dashboard.cli apply-approved-to-workbook
```

Optional explicit paths:

```bash
python -m belief_dashboard.cli apply-approved-to-workbook \
  --workbook data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx \
  --approved-file data/queues/approved_updates.csv
```

The original workbook is never modified. A backup of the original workbook is saved under:

```text
data/backups/
```

The output workbook is saved under:

```text
data/outputs/
```

Export reports are saved under:

```text
reports/workbook_exports/
```

Formula copy-down means formula-driven Evidence Log columns, such as Numeric, Factor, and Log Factor columns, are copied from the previous populated Evidence Log row into each appended row. Relative references are translated with `openpyxl` where possible. Queue data is written only to configured input columns, not formula columns.

## Find Latest Output Workbook

Print the most recently modified `.xlsx` file under `data/outputs/`:

```bash
python -m belief_dashboard.cli latest-output-workbook
```

## Verify Workbook Export

Verify a timestamped output workbook against `approved_updates.csv`:

```bash
python -m belief_dashboard.cli verify-workbook-export \
  --workbook data/outputs/output_file.xlsx
```

Verify using a Phase 7 export JSON report:

```bash
python -m belief_dashboard.cli verify-workbook-export \
  --workbook data/outputs/output_file.xlsx \
  --export-report reports/workbook_exports/workbook_export_YYYY-MM-DD_HHMMSS.json
```

Optional filters:

```bash
python -m belief_dashboard.cli verify-workbook-export \
  --workbook data/outputs/output_file.xlsx \
  --proposal-id PROP0001

python -m belief_dashboard.cli verify-workbook-export \
  --workbook data/outputs/output_file.xlsx \
  --source-id SRC0001
```

Verification reports are saved under:

```text
reports/export_verification/
```

Each run creates:

- `export_verification_YYYY-MM-DD_HHMMSS.md`
- `export_verification_YYYY-MM-DD_HHMMSS.json`

Verification checks trace metadata in Notes, mapped Evidence Log values, formula-driven columns, and optional export report planned rows. It does not modify the original workbook and does not promote an output workbook.

## Mark Approved Rows Exported

After verification succeeds, mark the matching approved queue rows as exported:

```bash
python -m belief_dashboard.cli verify-workbook-export \
  --workbook data/outputs/output_file.xlsx \
  --mark-exported
```

Rows are marked only when verification has no blocking errors. The added approved queue fields mean:

- `export_status`: currently `exported` when verified and marked.
- `exported_at`: verification timestamp.
- `exported_workbook`: verified output workbook path.
- `export_verification_report`: JSON verification report path.

## Dry-Run Workbook Promotion

Preview promotion checks without writing files:

```bash
python -m belief_dashboard.cli promote-output-workbook \
  --workbook data/outputs/output_file.xlsx \
  --verification-report reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json \
  --dry-run
```

Dry-run promotion checks that the candidate output workbook exists, the current main workbook exists, the verification report exists and has an accepted status, the report points to the candidate workbook, the workbook appears unchanged since verification, and basic workbook inspection passes. It writes no archive, no report files, no changelog row, and does not replace the main workbook.

## Promote A Verified Output Workbook

After a Phase 8 verification report has `overall_status: pass`, promote that exact workbook:

```bash
python -m belief_dashboard.cli promote-output-workbook \
  --workbook data/outputs/output_file.xlsx \
  --verification-report reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json
```

Optional explicit main workbook path:

```bash
python -m belief_dashboard.cli promote-output-workbook \
  --workbook data/outputs/output_file.xlsx \
  --verification-report reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json \
  --main-workbook data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx
```

The verification report is required because Phase 7 only creates a candidate output workbook; Phase 8 proves that the expected approved rows are present and consistent. Phase 9 refuses failed, warning, missing, stale, or mismatched verification reports.

Before replacement, the previous main workbook is archived under:

```text
data/backups/promoted_archives/
```

Promotion reports are saved under:

```text
reports/workbook_promotion/
```

Each real promotion creates:

- `workbook_promotion_YYYY-MM-DD_HHMMSS.md`
- `workbook_promotion_YYYY-MM-DD_HHMMSS.json`

Promotion differs from exporting approved updates: export creates a separate timestamped workbook in `data/outputs/`; promotion makes one verified output workbook the current working workbook after archiving the previous main workbook.

## Current Workbook Status

Print the current workbook state and latest related artifacts:

```bash
python -m belief_dashboard.cli current-workbook-status
```

Save a markdown status report:

```bash
python -m belief_dashboard.cli current-workbook-status --save
```

Saved status reports go under:

```text
reports/workbook_recovery/
```

## View Histories

View workbook export history:

```bash
python -m belief_dashboard.cli export-history
```

View export verification history:

```bash
python -m belief_dashboard.cli verification-history
```

View workbook promotion history:

```bash
python -m belief_dashboard.cli promotion-history
```

Limit output or save markdown and JSON history reports:

```bash
python -m belief_dashboard.cli export-history --limit 10 --save
python -m belief_dashboard.cli verification-history --limit 10 --save
python -m belief_dashboard.cli promotion-history --limit 10 --save
```

History reports are saved under:

```text
reports/workbook_recovery/
```

## List Promoted Archives

List archived main workbooks created before promotion:

```bash
python -m belief_dashboard.cli list-promoted-archives
```

Optional:

```bash
python -m belief_dashboard.cli list-promoted-archives --limit 10
```

Promoted archives are stored under:

```text
data/backups/promoted_archives/
```

## Dry-Run Rollback

Preview rollback from a selected promoted archive without writing files:

```bash
python -m belief_dashboard.cli rollback-workbook \
  --archive data/backups/promoted_archives/archive_file.xlsx \
  --dry-run
```

Dry-run rollback checks that the archive exists, the current main workbook exists, and the selected archive passes basic workbook inspection. It writes no rollback archive, no report files, no changelog row, and does not replace the main workbook.

## Perform Rollback

Restore a selected promoted archive to the main workbook path:

```bash
python -m belief_dashboard.cli rollback-workbook \
  --archive data/backups/promoted_archives/archive_file.xlsx
```

Optional explicit main workbook path:

```bash
python -m belief_dashboard.cli rollback-workbook \
  --archive data/backups/promoted_archives/archive_file.xlsx \
  --main-workbook data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx
```

Before replacement, rollback archives the current main workbook under:

```text
data/backups/rollback_archives/
```

Rollback reports are saved under:

```text
reports/workbook_recovery/
```

Each real rollback creates:

- `workbook_rollback_YYYY-MM-DD_HHMMSS.md`
- `workbook_rollback_YYYY-MM-DD_HHMMSS.json`

## List Artifact Categories

Show known artifact categories, directories, counts, and latest files:

```bash
python -m belief_dashboard.cli list-artifacts
```

Structured output:

```bash
python -m belief_dashboard.cli list-artifacts --format json
```

Save a lightweight navigation snapshot:

```bash
python -m belief_dashboard.cli list-artifacts --save
```

Categories include inspection reports, queue validation reports, prompt packets, manual import reports, review reports, export previews, workbook exports, export verification reports, promotion reports, recovery reports, output workbooks, promoted archives, and rollback archives.

## Find Latest Artifact

Show the latest artifact for a type:

```bash
python -m belief_dashboard.cli latest-artifact --type output_workbooks
python -m belief_dashboard.cli latest-artifact --type export_verification
python -m belief_dashboard.cli latest-artifact --type workbook_promotion
```

Structured output:

```bash
python -m belief_dashboard.cli latest-artifact --type export_verification --format json
```

Add `--save` to write markdown and JSON selector reports under `reports/artifact_navigation/`.

## Show Artifact Summary

Summarize a specific artifact without modifying it:

```bash
python -m belief_dashboard.cli show-artifact \
  --path reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json

python -m belief_dashboard.cli show-artifact \
  --path data/outputs/output_file.xlsx
```

JSON reports show status, key timestamps, workbook/report paths, row counts when available, and warning/error counts. Markdown reports show a short preview. Workbook files are inspected read-only using the existing workbook inspection logic.

Add `--save` to keep a copy of the summary under `reports/artifact_navigation/`.

## Find Reports

Find passing export verification reports:

```bash
python -m belief_dashboard.cli find-report \
  --type export_verification \
  --status pass
```

Find recent successful promotion reports:

```bash
python -m belief_dashboard.cli find-report \
  --type workbook_promotion \
  --status pass \
  --limit 5
```

Find reports containing a proposal ID:

```bash
python -m belief_dashboard.cli find-report \
  --type reviews \
  --contains PROP0001
```

Structured output:

```bash
python -m belief_dashboard.cli find-report \
  --type export_verification \
  --status pass \
  --format json
```

Add `--save` to preserve the filtered selector result under `reports/artifact_navigation/`.

## Find Verified Outputs

List output workbooks with matching verification reports before promotion:

```bash
python -m belief_dashboard.cli find-verified-output
```

Only show the latest passing verified output:

```bash
python -m belief_dashboard.cli find-verified-output --latest
```

Add `--save` to preserve the candidate list under `reports/artifact_navigation/`.

This command prints the output workbook path, verification report path, status, verification timestamp, whether the workbook still exists, and whether it appears modified after verification. It is intended to reduce operator error before running:

```bash
python -m belief_dashboard.cli promote-output-workbook \
  --workbook ... \
  --verification-report ...
```

## Compose Promotion Commands

Command composition exists to reduce path-selection errors while keeping high-stakes actions explicit. These commands print ready-to-copy commands; they do not run promotion, rollback, export, verification, or queue mutation commands.

Compose from explicit artifacts:

```bash
python -m belief_dashboard.cli compose-promote-command \
  --workbook data/outputs/output_file.xlsx \
  --verification-report reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json
```

Compose from the latest passing verified output:

```bash
python -m belief_dashboard.cli compose-promote-command --latest
```

The default output includes a dry-run command first, then the real promotion command:

```bash
python -m belief_dashboard.cli promote-output-workbook --workbook "..." --verification-report "..." --dry-run
python -m belief_dashboard.cli promote-output-workbook --workbook "..." --verification-report "..."
```

Structured output:

```bash
python -m belief_dashboard.cli compose-promote-command --latest --format json
```

## Compose Rollback Commands

Compose from an explicit promoted archive:

```bash
python -m belief_dashboard.cli compose-rollback-command \
  --archive data/backups/promoted_archives/archive_file.xlsx
```

Compose from the latest promoted archive:

```bash
python -m belief_dashboard.cli compose-rollback-command --latest
```

The default output includes a dry-run command first, then the real rollback command:

```bash
python -m belief_dashboard.cli rollback-workbook --archive "..." --dry-run
python -m belief_dashboard.cli rollback-workbook --archive "..."
```

Structured output:

```bash
python -m belief_dashboard.cli compose-rollback-command --latest --format json
```

## Next Safe Commands

Ask for a conservative command checklist:

```bash
python -m belief_dashboard.cli next-safe-commands
```

Structured output:

```bash
python -m belief_dashboard.cli next-safe-commands --format json
```

The checklist favors read-only checks, preview commands, dry-runs, artifact selection, and command composition. It does not execute mutating commands.

## Save Command Guides

Add `--save` to command-composition commands to write markdown and JSON guide reports:

```bash
python -m belief_dashboard.cli compose-promote-command --latest --save
python -m belief_dashboard.cli compose-rollback-command --latest --save
python -m belief_dashboard.cli next-safe-commands --save
```

Saved reports are written under:

```text
reports/command_guides/
```

Guide reports clearly note that no high-stakes command was executed.

## Operator Preflight

Operator preflight exists to gather the current operational state into one read-only packet before export, verification, promotion, or rollback decisions. It does not execute high-stakes commands and does not mutate workbooks or queue CSV files.

Run the general preflight:

```bash
python -m belief_dashboard.cli operator-preflight
```

Structured output:

```bash
python -m belief_dashboard.cli operator-preflight --format json
```

Before export:

```bash
python -m belief_dashboard.cli operator-preflight --mode before-export
```

This focuses on workbook inspection, queue validation, approved update counts, export preview context, and dry-run export recommendations.

Before verification:

```bash
python -m belief_dashboard.cli operator-preflight --mode before-verification
```

This focuses on the latest output workbook, latest export report, whether the output workbook exists, and the suggested verification command.

Before promotion:

```bash
python -m belief_dashboard.cli operator-preflight --mode before-promotion
```

This focuses on passing verification reports, verified output workbook existence, whether the output appears modified after verification, and composed promotion commands.

You can also pass explicit artifacts:

```bash
python -m belief_dashboard.cli operator-preflight \
  --mode before-promotion \
  --output-workbook data/outputs/output_file.xlsx \
  --verification-report reports/export_verification/export_verification_YYYY-MM-DD_HHMMSS.json
```

Before rollback:

```bash
python -m belief_dashboard.cli operator-preflight --mode before-rollback
```

This focuses on main workbook status, promoted archive availability, archive count, and composed rollback commands.

With an explicit archive:

```bash
python -m belief_dashboard.cli operator-preflight \
  --mode before-rollback \
  --archive data/backups/promoted_archives/archive_file.xlsx
```

Save preflight reports:

```bash
python -m belief_dashboard.cli operator-preflight --mode before-promotion --save
```

Saved reports are written under:

```text
reports/operator_preflight/
```

Each saved report includes timestamp, mode, overall status, workbook status, queue validation summary, queue summary, artifact summary, latest report/workbook paths, verified output candidates, recommended next commands, warnings, errors, and a clear note that no high-stakes command was executed.

## Run Tests

```bash
pytest
```

The tests create temporary workbooks and queue files. They do not require or modify your private workbook.

## Report Contents

Workbook inspection reports include:

- Workbook path.
- Inspection timestamp.
- Whether the workbook file exists.
- Sheet names found.
- Expected sheets found and missing.
- Evidence Log header row used.
- Evidence Log columns found.
- Required columns found and missing.
- Hypothesis MI5 columns found and missing.
- Number of populated evidence rows.
- Overall status: `pass`, `warning`, or `fail`.
- Clear next-step notes.

Queue validation reports include:

- Queue base directory.
- Validation timestamp.
- Required files found or missing.
- Header validation results.
- Invalid MI5 labels, review statuses, weights, and scores.
- Overall status: `pass`, `warning`, or `fail`.
- Clear next-step notes.

Manual import reports include:

- Import file path and import type.
- Row count and target queue file.
- Header, duplicate ID, source ID, claim ID, MI5, and score/weight status.
- Whether validation passed.
- Whether rows were appended.
- Dry-run status.
- Errors, warnings, and next-step notes.

Review reports include:

- Proposal ID and action taken.
- Reviewer and timestamp.
- Source ID and claim ID.
- Target queue.
- Whether proposed row status was updated.
- Whether target queue row was appended.
- Errors, warnings, and overall status.

Workbook export preview reports include:

- Workbook and approved-updates file paths.
- Evidence Log sheet and header row.
- Existing populated evidence row count.
- First planned append row.
- Rows ready or blocked.
- Workbook input columns found and missing.
- Formula-driven columns detected.
- ID planning status.
- Planned row summary.
- Warnings, errors, and next-step notes.

Workbook export reports include:

- Workbook, backup, output, and approved-updates file paths.
- Export timestamp and dry-run status.
- Evidence Log sheet and header row.
- Rows considered, exported, and blocked.
- Workbook input columns found and missing.
- Formula columns copied or skipped.
- ID planning status.
- Exported or planned row summary.
- Warnings, errors, and next-step notes.

Export verification reports include:

- Output workbook, approved queue, and optional export report paths.
- Verification timestamp.
- Approved rows considered.
- Matching, missing, mismatched, and formula concern counts.
- Whether `--mark-exported` was used.
- Whether approved rows were marked exported.
- Summary table by proposal ID.
- Warnings, errors, and next-step notes.

Workbook promotion reports include:

- Candidate output workbook, main workbook, verification report, and archive paths.
- Verification status and path-match result.
- Dry-run status.
- Candidate, main workbook, and verification report existence checks.
- Workbook stability and basic inspection results.
- Whether the main workbook was replaced.
- Warnings, errors, overall status, and next-step notes.

Workbook rollback reports include:

- Selected archive path and main workbook path.
- Rollback timestamp and dry-run status.
- Archive and main workbook existence checks.
- Archive inspection result.
- Rollback archive path for the pre-rollback main workbook.
- Whether the main workbook was replaced.
- Warnings, errors, overall status, and next-step notes.

Artifact navigation summaries include:

- Artifact type, directory, file count, latest file, and latest modified timestamp.
- Latest artifact path, modified timestamp, size, and parsed status when available.
- JSON report status, timestamps, workbook/report paths, row counts, and warning/error counts.
- Markdown report preview lines.
- Workbook inspection status and basic workbook row counts.

Command guide reports include:

- Timestamp and operation.
- Selected workbook, verification report, or archive paths.
- Generated dry-run command when included.
- Generated real command.
- Warnings and errors.
- Clear note that no high-stakes command was executed.

Operator preflight reports include:

- Timestamp, mode, and overall status.
- Workbook inspection summary.
- Queue validation and queue summary counts.
- Artifact summary and latest report/workbook paths.
- Verified output candidates.
- Recommended next commands.
- Warnings, errors, and a clear note that no high-stakes command was executed.

Doctor reports include:

- Timestamp, mode, overall status, and severity counts.
- Findings with severity, explanation, why it matters, safe repair command, documentation reference, related path, and `can_auto_fix`.
- Optional explanation reports for one finding with likely causes, safest next steps, safe commands, verification commands, documentation, and what-not-to-do cautions.
- Safe repair commands and next safest commands.
- Documentation references.
- A clear note that no high-stakes command was executed.

## Phase 14 Scope

- Add a `product-readiness` command for project-level validation.
- Verify the main workbook, queue files, artifact directories, backup/output directories, and demo example assets.
- Generate a markdown and JSON product readiness report.
- Support `--format json` for structured output and `--save` for report persistence.
- Keep the command read-only and avoid changing workbooks, queues, or archives.

## Running product readiness

```bash
python -m belief_dashboard.cli product-readiness --format json --save
```

The command writes reports to `reports/product_readiness/` and checks that demo assets exist under `data/sample/end_to_end_demo/`.

## Phase 15 Scope

- Add a read-only `doctor` command for general, before-export, before-verification, before-promotion, and before-rollback troubleshooting.
- Explain project health issues in plain language and map each issue to the safest repair command or documentation section.
- Support table output, JSON output, verbose findings, and saved markdown/JSON reports under `reports/doctor/`.
- Avoid API calls, web dashboards, workbook mutation, queue mutation, export, verification, promotion, rollback, and export tracking changes.

## Running Doctor

General troubleshooting:

```bash
python -m belief_dashboard.cli doctor
```

Mode-specific checks:

```bash
python -m belief_dashboard.cli doctor --mode before-export
python -m belief_dashboard.cli doctor --mode before-verification
python -m belief_dashboard.cli doctor --mode before-promotion
python -m belief_dashboard.cli doctor --mode before-rollback
```

Structured output and saved reports:

```bash
python -m belief_dashboard.cli doctor --format json
python -m belief_dashboard.cli doctor --save
python -m belief_dashboard.cli doctor --mode before-promotion --format json --save
```

`product-readiness` checks whether the project is generally ready to use. `operator-preflight` reports the current operational state before a workflow step. `doctor` explains what is wrong, why it matters, and which safe command or documentation page should be used next.

Severity levels:

- `blocker`: stop; a required precondition is missing.
- `error`: fix before continuing with the relevant workflow.
- `warning`: review before proceeding.
- `info`: useful context or a safe next opportunity.

Doctor recommends commands but does not run high-stakes repairs.

## Phase 16 Scope

- Add `doctor --explain FINDING_ID` for guided troubleshooting of one currently detected doctor finding.
- Support mode-specific explanations, JSON output, and saved markdown/JSON explanation reports.
- Include likely causes, safest next steps, safe repair commands, verification commands, documentation references, related files, and what-not-to-do cautions.
- Add concise troubleshooting documentation in `docs/TROUBLESHOOTING.md`.
- Keep explain mode read-only: no workbook edits, queue edits, exports, verification, promotion, rollback, API calls, or web dashboard.

## Explaining A Finding

Use a finding ID from `doctor` output:

```bash
python -m belief_dashboard.cli doctor --explain MAIN_WORKBOOK_MISSING
python -m belief_dashboard.cli doctor --mode before-promotion --explain NO_PASSING_VERIFICATION
```

Finding IDs are matched case-insensitively, and common uppercase aliases are accepted.

Save explanation reports:

```bash
python -m belief_dashboard.cli doctor --explain MAIN_WORKBOOK_MISSING --save
```

This writes:

- `reports/doctor/doctor_explain_MAIN_WORKBOOK_MISSING_YYYY-MM-DD_HHMMSS.md`
- `reports/doctor/doctor_explain_MAIN_WORKBOOK_MISSING_YYYY-MM-DD_HHMMSS.json`

The “Do not” section lists unsafe or premature actions to avoid, such as exporting while queues fail validation, promoting without passing verification, or manually copying output workbooks over the main workbook.

## Phase 17 Scope

- Add `debate-summary` for read-only debate-prep summaries from approved update rows.
- Summarize support, challenge, neutral/mixed evidence, defeaters, open questions, salient criteria signals, and trace IDs by hypothesis.
- Support one-hypothesis and all-hypotheses summaries, JSON output, Discord-friendly output, filters, and saved markdown/JSON reports.
- Keep debate summaries read-only: no workbook edits, queue edits, exports, verification, promotion, rollback, API calls, or web dashboard.

## Debate Summaries

Summarize one hypothesis:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC
```

Summarize all configured hypotheses:

```bash
python -m belief_dashboard.cli debate-summary --all
```

Use output styles:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --short
python -m belief_dashboard.cli debate-summary --hypothesis EC --long
python -m belief_dashboard.cli debate-summary --hypothesis EC --discord
```

Filter approved records:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --min-weight 3
python -m belief_dashboard.cli debate-summary --hypothesis EC --exported-only
python -m belief_dashboard.cli debate-summary --hypothesis EC --source-id SRC0001
python -m belief_dashboard.cli debate-summary --hypothesis EC --category "Philosophical argument"
```

Save reports under `reports/debate_summaries/`:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --save
python -m belief_dashboard.cli debate-summary --all --format json --save
```

Support/challenge sections are based on the selected hypothesis's MI5 label and approved weight. They are a debate-prep view over approved records, not a final declaration of belief.

## Phase 18 Scope

- Add `debate-packet` for printable, traceable debate prep packets.
- Combine debate-summary evidence sections with source trace, claim context, objections/defeaters, counter-objections, criteria highlights, open questions, debate framing, Discord copy text, and a trace appendix.
- Support hypothesis selection, topic filtering, combined filters, JSON output, Discord output, short/long output, and saved markdown/JSON reports.
- Keep debate packets read-only: no workbook edits, queue edits, exports, verification, promotion, rollback, API calls, or web dashboard.

## Debate Packets

Generate a packet for one hypothesis:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC
```

Generate a topic-filtered packet:

```bash
python -m belief_dashboard.cli debate-packet --topic "moral realism"
```

Combine hypothesis and topic filters:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --topic "moral realism"
```

Use output styles:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --short
python -m belief_dashboard.cli debate-packet --hypothesis EC --long
python -m belief_dashboard.cli debate-packet --hypothesis EC --discord
python -m belief_dashboard.cli debate-packet --hypothesis EC --format json
```

Save reports under `reports/debate_packets/`:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --save
```

`debate-summary` is the concise overview. `debate-packet` is the fuller printable prep packet with source trace, open questions, framing, Discord copy text, and a trace appendix. Use the trace appendix to return to `proposal_id`, `claim_id`, and `source_id` records. The packet summarizes approved records and does not tell you what to believe.
