# Operator Workflow

This tool is a guarded CLI workflow for moving reviewed queue data into timestamped workbook copies before any promotion to the main workbook.

## Normal Safe Flow

1. Inspect the workbook:
   `python -m belief_dashboard.cli inspect-workbook`
2. Validate queues:
   `python -m belief_dashboard.cli validate-queues`
3. Register a source and generate manual review materials:
   `register-source`, `create-claim-template`, `generate-prompt-packet`
4. Validate and append manual imports:
   `validate-import`, then `append-import`
5. Review proposals:
   `list-proposals`, then `approve-proposal`, `reject-proposal`, or `defer-proposal`
6. Preview export:
   `python -m belief_dashboard.cli preview-workbook-export`
7. Dry-run or apply export to a timestamped output copy:
   `python -m belief_dashboard.cli apply-approved-to-workbook --dry-run`
8. Verify output workbook:
   `python -m belief_dashboard.cli verify-workbook-export --workbook data/outputs/...xlsx`
9. Compose promotion command:
   `python -m belief_dashboard.cli compose-promote-command --latest`
10. Run operator preflight:
   `python -m belief_dashboard.cli operator-preflight --mode before-promotion`

Promotion and rollback remain explicit guarded commands. Command composition and preflight do not execute them.

## Product Readiness

Run:

```bash
python -m belief_dashboard.cli product-readiness
```

This checks local readiness and prints the test command to run before real use.
