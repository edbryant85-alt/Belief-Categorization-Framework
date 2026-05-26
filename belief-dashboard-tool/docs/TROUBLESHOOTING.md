# Troubleshooting With Doctor

Use doctor when a workflow step is blocked and you want plain-language guidance.

```bash
python -m belief_dashboard.cli doctor
python -m belief_dashboard.cli doctor --explain FINDING_ID
python -m belief_dashboard.cli doctor --mode before-promotion --explain NO_PASSING_VERIFICATION
```

Doctor explain mode is read-only. It recommends commands, but it does not run repairs, export updates, verify workbooks, promote, roll back, or edit queue files.

## Common Findings

### MAIN_WORKBOOK_MISSING

The main workbook is missing from the configured path.

Safe next steps:

1. Confirm you are in `belief-dashboard-tool/`.
2. Confirm the workbook exists at `data/workbooks/bayesian_belief_dashboard_expanded_9_hypotheses.xlsx`.
3. Run `python -m belief_dashboard.cli inspect-workbook`.
4. Run `python -m belief_dashboard.cli doctor`.

Do not create a blank workbook as a substitute or run export/promotion commands until inspection passes.

### MISSING_QUEUES

Required queue files are missing.

Safe commands:

```bash
python -m belief_dashboard.cli init-queues
python -m belief_dashboard.cli validate-queues
```

Do not manually invent queue headers or append imports before queues validate.

### QUEUE_VALIDATION_FAILED

One or more queue CSV files has invalid headers or values.

Safe next steps:

1. Run `python -m belief_dashboard.cli validate-queues`.
2. Open the latest report under `reports/queue_validation/`.
3. Fix malformed headers, invalid MI5 labels, invalid statuses, or invalid score ranges.
4. Rerun validation.

Do not export approved updates while queues fail validation.

### NO_OUTPUT_WORKBOOK

Verification needs an output workbook, but none was found.

Safe commands:

```bash
python -m belief_dashboard.cli preview-workbook-export
python -m belief_dashboard.cli apply-approved-to-workbook --dry-run
python -m belief_dashboard.cli apply-approved-to-workbook
```

Do not run verification without an output workbook or promote the main workbook directly.

### NO_PASSING_VERIFICATION

Promotion is blocked because no passing verification report was found.

Safe commands:

```bash
python -m belief_dashboard.cli find-verified-output
python -m belief_dashboard.cli latest-output-workbook
python -m belief_dashboard.cli verify-workbook-export --workbook "data/outputs/output_file.xlsx"
```

Do not promote an output workbook until verification passes. Do not manually copy an output workbook over the main workbook.

### NO_PROMOTED_ARCHIVE

Rollback is blocked because no promoted archive exists.

Safe commands:

```bash
python -m belief_dashboard.cli list-promoted-archives
python -m belief_dashboard.cli promotion-history
```

Do not attempt rollback without an archive. Use an external backup process if the CLI has no promoted archive to restore.
