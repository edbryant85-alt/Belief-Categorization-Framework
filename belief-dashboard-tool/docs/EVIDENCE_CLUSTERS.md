# Evidence Clusters

Evidence clusters group related registered sources before claim extraction. Use them when a topic is too connected to process source-by-source without overcounting duplicates, missing objections, or prematurely pushing every source toward workbook evidence.

Clusters do not extract claims, create proposals, export workbooks, verify workbooks, or promote anything. They organize sources so later extraction can focus on the best representatives.

## When To Use A Cluster

Use a cluster when:

- one topic has many papers, clips, debate threads, and notes;
- sources respond to each other;
- several sources are background or duplicate summaries;
- you need a map of major arguments and objections before extraction;
- the workbook should receive distilled evidence rather than every source individually.

Use normal source-by-source extraction when a source is self-contained and already likely to produce dashboard-worthy evidence rows. For source extraction, prefer `generate-extraction-workspace`; it creates an exact-schema prompt packet and blank CSV templates so ChatGPT does not invent import columns.

## Queue Files

Cluster metadata lives in:

```text
data/queues/evidence_clusters.csv
```

Schema:

```csv
cluster_id,cluster_title,core_question,description,hypotheses_touched,topic_tags,status,created_date,updated_date,notes
```

Source membership lives in:

```text
data/queues/source_cluster_members.csv
```

Schema:

```csv
cluster_id,source_id,source_role,subtopic,relevance_0_5,priority_0_5,status,notes
```

Allowed cluster statuses are `proposed`, `active`, `triaging`, `ready_for_extraction`, `ready_for_evidence_review`, and `archived`.

Allowed source roles are `core_argument`, `supporting_argument`, `objection`, `counter_objection`, `theological_application`, `scientific_context`, `popular_summary`, `debate_thread`, `background`, `duplicate`, and `user_notes`.

## Simulation Argument Workflow

Initialize cluster queues:

```bash
python -m belief_dashboard.cli init-cluster-queues
```

Create the first cluster:

```bash
python -m belief_dashboard.cli create-cluster \
  --cluster-id CLUST-SIM-001 \
  --title "Simulation Argument and Theological Implications" \
  --core-question "If simulated worlds are possible or likely, what does that imply for theism, naturalism, creation, divine hiddenness, incarnation, moral responsibility, and religious experience?" \
  --hypotheses "CT; MT; PT; EC; PC; IS; MS; N" \
  --topic-tags "simulation argument; Bostrom; theology; naturalism; creation; divine hiddenness; consciousness; philosophy of religion"
```

Register sources separately with `register-source` or `bulk-register-sources`. Then add existing source IDs:

```bash
python -m belief_dashboard.cli add-source-to-cluster \
  --cluster-id CLUST-SIM-001 \
  --source-id SRC0012 \
  --role core_argument \
  --subtopic "Bostrom original trilemma" \
  --relevance 5 \
  --priority 5
```

Bulk add already-registered YouTube transcripts:

```bash
python -m belief_dashboard.cli bulk-add-sources-to-cluster \
  --cluster-id CLUST-SIM-001 \
  --source-type youtube_transcript \
  --role popular_summary \
  --subtopic "video discussion" \
  --relevance 2 \
  --priority 1
```

Or bulk add by registered path prefix:

```bash
python -m belief_dashboard.cli bulk-add-sources-to-cluster \
  --cluster-id CLUST-SIM-001 \
  --source-folder data/raw_sources/clusters/simulation_argument/youtube \
  --role popular_summary
```

Summarize membership:

```bash
python -m belief_dashboard.cli cluster-summary --cluster-id CLUST-SIM-001
```

Generate a cluster-level triage packet:

```bash
python -m belief_dashboard.cli generate-cluster-triage-packet --cluster-id CLUST-SIM-001
```

List likely extraction candidates:

```bash
python -m belief_dashboard.cli cluster-candidates-for-extraction --cluster-id CLUST-SIM-001
```

Run a guarded batch controller for a 10-25 source pass:

```bash
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode prepare
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode qa
python -m belief_dashboard_agentflows cluster-extraction-batch --cluster-id CLUST-SIM-001 --limit 25 --mode dry-run
```

The batch controller coordinates existing safe steps. It can generate schema-locked extraction workspaces, diagnose import shape, run extraction QA, run native import validation, write separate cleaned candidates, and run `append-import --dry-run` only when all three import files validate. It does not perform real append, proposal review, workbook export, verification, promotion, rollback, git commit, or git push.

Generate schema-locked extraction materials for one selected source:

```bash
python -m belief_dashboard.cli generate-extraction-workspace --source-id SRC0012
```

Use `--packet-strategy first` for short sources where the default first inline packet covers the relevant source text. Use `--packet-strategy section` for long scholarly articles:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0014 \
  --packet-strategy section \
  --max-chars-per-packet 12000 \
  --force
```

Section mode writes multiple schema-locked packets plus a source map under `reports/prompt_packets/`. Each packet is scoped to a coherent heading/page range and instructs the extractor not to summarize unseen sections.

Use `--packet-strategy targeted` when a review plan defers a claim because relevant sections were truncated:

```bash
python -m belief_dashboard.cli generate-extraction-workspace \
  --source-id SRC0014 \
  --packet-strategy targeted \
  --include-heading "Neoplatonism" \
  --force
```

Do not approve broad roadmap claims from abstract-only evidence when detailed sections are absent. Defer those rows until a targeted or section packet has been processed.

Then paste the schema-locked prompt into ChatGPT, save the three returned CSVs under `data/manual_imports/` as `SRC0012_extracted_claims.csv`, `SRC0012_criteria_matrix.csv`, and `SRC0012_proposed_updates.csv`, then clean, validate, and append only after all three cleaned files pass validation.

## Deciding What Gets Extracted

Prefer full extraction for sources that are core arguments, substantial objections, counter-objections, or direct theological applications. Defer or archive sources that are merely popular summaries, duplicates, or background context unless they add a distinct claim that the cluster lacks.

Avoid overcounting: five sources repeating the same argument should usually become one distilled evidence item with notes about repetition, not five independent workbook entries.
