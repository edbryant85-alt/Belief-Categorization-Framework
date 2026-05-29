# Operator Workflow

This tool is a guarded CLI workflow for moving reviewed queue data into timestamped workbook copies before any promotion to the main workbook.

## Normal Safe Flow

1. Inspect the workbook:
   `python -m belief_dashboard.cli inspect-workbook`
2. Validate queues:
   `python -m belief_dashboard.cli validate-queues`
3. Register a source and generate schema-locked manual extraction materials:
   `register-source`, `create-claim-template`, `generate-extraction-workspace`
4. For complex topics, create an evidence cluster before extraction:
   `init-cluster-queues`, `create-cluster`, `add-source-to-cluster`, `generate-cluster-triage-packet`
5. For larger clusters, run guarded batch passes before real append:
   `python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --mode prepare`,
   then `--mode qa`, then `--mode dry-run`
6. Validate and append manual imports:
   `validate-import`, optionally `clean-import`, then `append-import`
7. Review proposals:
   `list-proposals`, optionally `batch-review-guide`, then `approve-proposal`, `reject-proposal`, or `defer-proposal`
8. Preview export:
   `python -m belief_dashboard.cli preview-workbook-export`
9. Dry-run or apply export to a timestamped output copy:
   `python -m belief_dashboard.cli apply-approved-to-workbook --dry-run`
10. Verify output workbook:
   `python -m belief_dashboard.cli verify-workbook-export --workbook data/outputs/...xlsx`
11. Compose promotion command:
   `python -m belief_dashboard.cli compose-promote-command --latest`
12. Run operator preflight:
   `python -m belief_dashboard.cli operator-preflight --mode before-promotion`
13. Run doctor if anything is unclear or blocked:
   `python -m belief_dashboard.cli doctor --mode before-promotion`
14. Generate debate-prep summaries from approved records:
   `python -m belief_dashboard.cli debate-summary --hypothesis EC`
15. Generate a fuller printable debate packet:
   `python -m belief_dashboard.cli debate-packet --hypothesis EC`
16. Generate a prioritized study/reflection queue:
   `python -m belief_dashboard.cli study-queue`

Promotion and rollback remain explicit guarded commands. Command composition and preflight do not execute them.

## Real Source Intake

For a Discord thread, YouTube transcript, or book note source:

```bash
python -m belief_dashboard.cli register-source --file data/raw_sources/example.txt --source-type discord_thread --title "Example Thread"
python -m belief_dashboard.cli find-source example
python -m belief_dashboard.cli generate-extraction-workspace --source-id SRC0001
python -m belief_dashboard.cli validate-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims.csv
python -m belief_dashboard.cli clean-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims.csv
python -m belief_dashboard.cli validate-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims_cleaned.csv
python -m belief_dashboard.cli append-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims_cleaned.csv --dry-run
python -m belief_dashboard.cli append-import --type extracted_claims --file data/manual_imports/SRC0001_extracted_claims_cleaned.csv
```

Paste the schema-locked prompt packet into ChatGPT and save the three returned CSVs as:

```text
data/manual_imports/SRC0001_extracted_claims.csv
data/manual_imports/SRC0001_criteria_matrix.csv
data/manual_imports/SRC0001_proposed_updates.csv
```

Repeat validate, clean if needed, dry-run append, and real append for `criteria_matrix` and `proposed_updates`. Append only after all three cleaned files validate.

`find-source` is read-only and helps recover an existing `SRC####` without re-registering. `generate-extraction-workspace` writes a schema-locked prompt packet plus blank CSV templates under `data/manual_imports/templates/`; use it for source extraction instead of the older `generate-prompt-packet` workflow.

For short sources, keep the default first-packet strategy:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0001 \
  --packet-strategy first
```

For long scholarly articles, prefer section-aware packets so later sections are not silently omitted:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0014 \
  --packet-strategy section \
  --max-chars-per-packet 12000 \
  --force
```

For long books, register the book as one source, generate a section-aware workspace, then run the guarded packet-cycle planner before extracting anything:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0018 \
  --packet-strategy section \
  --max-chars-per-packet 12000 \
  --force

python -m belief_dashboard.cli plan-source-packet-cycle \
  --source-id SRC0018 \
  --max-batch-size 10
```

The planner writes markdown and JSON reports under `reports/source_packet_cycles/`. It loads the source dossier, finds the newest source map when `--source-map` is omitted, classifies generated packets, groups them into chapter/topic batches, and recommends a bounded first extraction batch. It does not extract claims, generate import CSVs, append queues, review proposals, export or verify workbooks, promote, rollback, commit, or push.

Long-book workflow:

1. Register the book as one source.
2. Generate a section-aware extraction workspace.
3. Run `plan-source-packet-cycle`.
4. Select one recommended batch.
5. Process only that batch using the schema-locked packet text.
6. Validate and dry-run before append.
7. Review proposals after human approval.
8. Repeat batch-by-batch.

Do not process all packets from a long book in one unattended run.

For deferred review items caused by a truncated packet, generate a targeted packet around the missing section:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0014 \
  --packet-strategy targeted \
  --include-heading "Neoplatonism" \
  --force
```

Defer claims that depend on missing sections until a section or targeted packet has been processed. Do not approve broad roadmap claims from abstract-only evidence when the detailed source sections are absent.

Use schema utilities when imports look malformed:

```bash
python -m belief_dashboard.cli show-import-schema --type extracted_claims
python -m belief_dashboard.cli show-import-schema --type criteria_matrix
python -m belief_dashboard.cli show-import-schema --type proposed_updates
python -m belief_dashboard.cli diagnose-import-shape --type criteria_matrix --file data/manual_imports/SRC0001_criteria_matrix.csv
```

`clean-import` writes a separate cleaned CSV and does not change queue files. It handles common first-pass CSV issues: UTF-8 BOMs, `status=extracted`, multi-label claim types such as `metaphysical; moral; interpretive`, `review_status=needs_review`, and blank `source_book` values that can be filled from the source dossier title.

If append validation says an ID already exists in the target queue, treat it as a safe stop. No rows were appended. Remove already-imported rows from the manual CSV or skip that append.

## Evidence Cluster Intake

For topics with many related sources, organize the cluster before generating claim extraction packets:

```bash
python -m belief_dashboard.cli init-cluster-queues

python -m belief_dashboard.cli create-cluster \
  --cluster-id CLUST-SIM-001 \
  --title "Simulation Argument and Theological Implications" \
  --core-question "If simulated worlds are possible or likely, what does that imply for theism, naturalism, creation, divine hiddenness, incarnation, moral responsibility, and religious experience?" \
  --hypotheses "CT; MT; PT; EC; PC; IS; MS; N" \
  --topic-tags "simulation argument; Bostrom; theology; naturalism; creation; divine hiddenness; consciousness; philosophy of religion"

python -m belief_dashboard.cli add-source-to-cluster \
  --cluster-id CLUST-SIM-001 \
  --source-id SRC0012 \
  --role core_argument \
  --subtopic "Bostrom original trilemma" \
  --relevance 5 \
  --priority 5

python -m belief_dashboard.cli cluster-summary --cluster-id CLUST-SIM-001
python -m belief_dashboard.cli generate-cluster-triage-packet --cluster-id CLUST-SIM-001
python -m belief_dashboard.cli cluster-candidates-for-extraction --cluster-id CLUST-SIM-001
```

The cluster packet asks for a research map, role recommendations, likely duplicates/background sources, extraction candidates, major arguments, objections, theological implications, unresolved questions, and next processing actions. It does not request extracted claims or workbook-ready proposals.

For repeatable 10-25 source cluster batches, use the report-first agentflow controller:

```bash
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode prepare
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode qa
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode dry-run
```

The batch controller does not run real `append-import`. After human review, run real append only through the native CLI and only for files that validated and passed dry-run checks.

See also `docs/EVIDENCE_CLUSTERS.md`.

For proposal review:

```bash
python -m belief_dashboard.cli list-proposals --source-id SRC0001 --status proposed
python -m belief_dashboard.cli batch-review-guide --source-id SRC0001 --reviewer "Your Name"
```

`batch-review-guide` prints per-proposal commands only. It does not modify queues.

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

## Study Queue

Run:

```bash
python -m belief_dashboard.cli study-queue
```

Filter by hypothesis, topic, source, or category:

```bash
python -m belief_dashboard.cli study-queue --hypothesis EC
python -m belief_dashboard.cli study-queue --topic "moral realism"
python -m belief_dashboard.cli study-queue --source-id SRC0001
python -m belief_dashboard.cli study-queue --category "Philosophical argument"
```

Output and save options:

```bash
python -m belief_dashboard.cli study-queue --min-priority 3
python -m belief_dashboard.cli study-queue --discord
python -m belief_dashboard.cli study-queue --format json
python -m belief_dashboard.cli study-queue --save
```

`study-queue` differs from `debate-summary` and `debate-packet`: it is not trying to present the best case. It prioritizes what to read, clarify, revisit, or reflect on next.

Priority scoring combines approved weight with uncertainty, defeater strength, salient criteria scores, low clarity, deferred status, and matching filters. Treat the score as a study aid, not a belief calculation. High emotional, moral, or existential salience is kept separate from evidential strength.

See also `docs/STUDY_QUEUE.md`.

## Source Briefs

Run:

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001
```

Use raw excerpt, compact, detailed, Discord, or JSON output:

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001 --include-raw-excerpt
python -m belief_dashboard.cli source-brief --source-id SRC0001 --short
python -m belief_dashboard.cli source-brief --source-id SRC0001 --long
python -m belief_dashboard.cli source-brief --source-id SRC0001 --discord
python -m belief_dashboard.cli source-brief --source-id SRC0001 --format json
```

Save reports under `reports/source_briefs/`:

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001 --save
```

`source-brief` differs from `debate-summary`, `debate-packet`, and `study-queue` by starting from one source and gathering all known source-level queue records. It includes source metadata, claims, criteria highlights, review outcomes, approved hypothesis impacts, unresolved study items, debate-use notes, Discord copy text, and a trace appendix.

Use the trace appendix to return to `source_id`, `claim_id`, and `proposal_id` rows. The command summarizes queue records and does not change workbooks, queue CSV files, source files, proposals, approvals, or export tracking fields.

See also `docs/SOURCE_BRIEFS.md`.

## Source Comparisons

Compare selected sources:

```bash
python -m belief_dashboard.cli compare-sources --source-id SRC0001 --source-id SRC0002
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002
```

Map sources affecting a hypothesis or topic:

```bash
python -m belief_dashboard.cli source-map --hypothesis EC
python -m belief_dashboard.cli source-map --topic "moral realism"
python -m belief_dashboard.cli source-map --hypothesis EC --topic "moral realism"
```

Use filters and output options:

```bash
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --hypothesis EC
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --topic "moral realism"
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --short
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --long
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --discord
python -m belief_dashboard.cli source-map --hypothesis EC --format json
```

Save reports under `reports/source_comparisons/`:

```bash
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --save
python -m belief_dashboard.cli source-map --hypothesis EC --save
```

`source-brief` inspects one source. `compare-sources` compares selected sources. `source-map` ranks all matching sources for a hypothesis or topic. Conflict detection is heuristic: it flags apparent tension when approved rows from different sources support and challenge the same hypothesis. It does not prove logical contradiction.

Use the trace appendix to return to `source_id`, `claim_id`, and `proposal_id` rows.

See also `docs/SOURCE_COMPARISONS.md`.

## Evidence Networks

Build broad evidence clusters:

```bash
python -m belief_dashboard.cli evidence-clusters
python -m belief_dashboard.cli evidence-clusters --hypothesis EC
python -m belief_dashboard.cli evidence-clusters --topic "moral realism"
python -m belief_dashboard.cli evidence-clusters --category "Philosophical argument"
```

Focus on specific cluster families:

```bash
python -m belief_dashboard.cli evidence-clusters --cluster-type defeaters
python -m belief_dashboard.cli evidence-clusters --cluster-type conflicts
python -m belief_dashboard.cli evidence-clusters --cluster-type salience
python -m belief_dashboard.cli evidence-clusters --cluster-type uncertainty
```

Build a source-centered network:

```bash
python -m belief_dashboard.cli source-network
python -m belief_dashboard.cli source-network --hypothesis EC
python -m belief_dashboard.cli source-network --topic "moral realism"
python -m belief_dashboard.cli source-network --source-id SRC0001
```

Output and save options:

```bash
python -m belief_dashboard.cli evidence-clusters --discord
python -m belief_dashboard.cli source-network --format json
python -m belief_dashboard.cli evidence-clusters --save
python -m belief_dashboard.cli source-network --hypothesis EC --save
```

`source-brief` inspects one source. `source-map` ranks sources for a hypothesis or topic. `evidence-clusters` and `source-network` zoom out to the broader evidence structure. Cluster IDs such as `HYP_EC`, `DEF_EC`, and `UNCERTAINTY_001` are deterministic report aids and are not written to queues.

Apparent conflict detection is heuristic: it flags support/challenge tension on the same hypothesis, not logical contradiction. Source centrality is based on approved rows, hypotheses touched, weight, and uncertainty/defeater/salience signals. Use trace IDs to return to exact queue records.

See also `docs/EVIDENCE_NETWORKS.md`.
