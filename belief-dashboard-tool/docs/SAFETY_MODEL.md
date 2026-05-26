# Safety Model

The project separates read-only checks, queue-writing steps, workbook-copy writing, and main-workbook replacement.

## Read-Only Commands

Examples: `inspect-workbook`, `validate-queues`, `preview-workbook-export`, `latest-output-workbook`, `current-workbook-status`, `list-artifacts`, `show-artifact`, `find-report`, `find-verified-output`, `compose-promote-command`, `compose-rollback-command`, `next-safe-commands`, `operator-preflight`, and `product-readiness`.

These commands do not modify workbooks or queue CSV files. Some read-only commands can write report files when the command's existing behavior includes reports or when `--save` is supplied.

## Queue-Writing Commands

Examples: `init-queues`, `register-source`, `append-import`, `approve-proposal`, `reject-proposal`, and `defer-proposal`.

These commands update queue CSVs and logs only. They do not modify Excel workbooks.

## Workbook-Copy Commands

`apply-approved-to-workbook` writes a backup and a timestamped output workbook copy. It does not replace the configured main workbook.

`verify-workbook-export` is read-only for the workbook. It modifies approved queue export tracking only when `--mark-exported` is explicitly supplied.

## Main Workbook Replacement

`promote-output-workbook` and `rollback-workbook` are the only commands intended to replace the configured main workbook. Both support `--dry-run`, and Phase 12/13 commands help compose and preflight those commands without executing them.
