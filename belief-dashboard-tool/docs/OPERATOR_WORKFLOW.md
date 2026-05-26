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
11. Run doctor if anything is unclear or blocked:
   `python -m belief_dashboard.cli doctor --mode before-promotion`
12. Generate debate-prep summaries from approved records:
   `python -m belief_dashboard.cli debate-summary --hypothesis EC`
13. Generate a fuller printable debate packet:
   `python -m belief_dashboard.cli debate-packet --hypothesis EC`

Promotion and rollback remain explicit guarded commands. Command composition and preflight do not execute them.

## Product Readiness

Run:

```bash
python -m belief_dashboard.cli product-readiness
```

This checks local readiness and prints the test command to run before real use.

## Doctor

Run:

```bash
python -m belief_dashboard.cli doctor
```

Doctor is a read-only troubleshooting command. It explains problems in plain language, says why each issue matters, recommends the safest next command, and points to relevant documentation or report folders.

Use mode-specific checks before guarded workflow steps:

```bash
python -m belief_dashboard.cli doctor --mode before-export
python -m belief_dashboard.cli doctor --mode before-verification
python -m belief_dashboard.cli doctor --mode before-promotion
python -m belief_dashboard.cli doctor --mode before-rollback
```

Save markdown and JSON reports under `reports/doctor/`:

```bash
python -m belief_dashboard.cli doctor --save
```

Use JSON for structured review:

```bash
python -m belief_dashboard.cli doctor --format json
```

Explain one finding in detail:

```bash
python -m belief_dashboard.cli doctor --explain MAIN_WORKBOOK_MISSING
python -m belief_dashboard.cli doctor --mode before-promotion --explain NO_PASSING_VERIFICATION
python -m belief_dashboard.cli doctor --explain MAIN_WORKBOOK_MISSING --format json
python -m belief_dashboard.cli doctor --explain MAIN_WORKBOOK_MISSING --save
```

Explanation reports are saved under `reports/doctor/` as `doctor_explain_FINDING_ID_YYYY-MM-DD_HHMMSS.md` and `.json`.

`product-readiness` checks whether the project is generally ready to use. `operator-preflight` reports the current operational state and suggested next commands. `doctor` explains what is wrong, why it matters, and how to fix it safely.

Severity levels:

- `blocker`: stop; a required precondition is missing.
- `error`: fix before continuing with the relevant workflow.
- `warning`: review before proceeding.
- `info`: useful context or a safe next opportunity.

Doctor recommends commands but does not run high-stakes repairs. It does not modify workbooks, queue CSV files, exported files, promoted archives, rollback archives, source data, proposals, approvals, or export tracking fields. It only writes doctor reports when `--save` is supplied.

The “Do not” section in explain output lists unsafe or premature actions to avoid. Treat those cautions as guardrails: they describe actions that might bypass workbook verification, queue validation, promotion safeguards, or rollback archive checks.

See also `docs/TROUBLESHOOTING.md` for common finding IDs and safe next steps.

## Debate Summaries

Run:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC
```

Use `--all` for all configured hypotheses:

```bash
python -m belief_dashboard.cli debate-summary --all
```

Output options:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --short
python -m belief_dashboard.cli debate-summary --hypothesis EC --long
python -m belief_dashboard.cli debate-summary --hypothesis EC --discord
```

Useful filters:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --min-weight 3
python -m belief_dashboard.cli debate-summary --hypothesis EC --exported-only
python -m belief_dashboard.cli debate-summary --hypothesis EC --source-id SRC0001
python -m belief_dashboard.cli debate-summary --hypothesis EC --category "Philosophical argument"
```

Save reports under `reports/debate_summaries/`:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --save
```

Support and challenge sections are based on MI5 labels for the selected hypothesis and ranked by approved weight. Treat the output as a debate-prep summary of approved records, not as a command telling you what to believe.

See also `docs/DEBATE_SUMMARIES.md`.

## Debate Packets

Run:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC
```

Use topic filtering:

```bash
python -m belief_dashboard.cli debate-packet --topic "moral realism"
python -m belief_dashboard.cli debate-packet --hypothesis EC --topic "moral realism"
```

Output options:

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

`debate-summary` gives a concise hypothesis summary. `debate-packet` gives a fuller printable prep packet with source trace, claim context, objections, counter-objections, criteria highlights, open questions, debate framing, Discord copy text, and a trace appendix.

Use the trace appendix to return to original queue records by `proposal_id`, `claim_id`, and `source_id`. Treat the packet as a summary of approved records, not as a command telling you what to believe.

See also `docs/DEBATE_PACKETS.md`.
