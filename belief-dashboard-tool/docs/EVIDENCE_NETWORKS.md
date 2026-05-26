# Evidence Networks

Phase 22 adds read-only network-style views over queue records:

- `evidence-clusters`: groups evidence into structural clusters.
- `source-network`: summarizes source centrality and source relationships.

These commands do not modify workbooks, queues, source files, proposals, approvals, export tracking fields, or operational reports. Files are written only with `--save`.

## Evidence Clusters

```bash
python -m belief_dashboard.cli evidence-clusters
python -m belief_dashboard.cli evidence-clusters --hypothesis EC
python -m belief_dashboard.cli evidence-clusters --topic "moral realism"
python -m belief_dashboard.cli evidence-clusters --category "Philosophical argument"
```

Cluster types:

```bash
python -m belief_dashboard.cli evidence-clusters --cluster-type hypotheses
python -m belief_dashboard.cli evidence-clusters --cluster-type categories
python -m belief_dashboard.cli evidence-clusters --cluster-type defeaters
python -m belief_dashboard.cli evidence-clusters --cluster-type conflicts
python -m belief_dashboard.cli evidence-clusters --cluster-type salience
python -m belief_dashboard.cli evidence-clusters --cluster-type uncertainty
```

Cluster IDs are deterministic within a report:

- `HYP_EC`
- `CAT_Philosophical_argument`
- `DEF_EC`
- `CONFLICT_EC`
- `SALIENCE_001`
- `UNCERTAINTY_001`

Cluster IDs are not persisted to queue files.

## Source Network

```bash
python -m belief_dashboard.cli source-network
python -m belief_dashboard.cli source-network --hypothesis EC
python -m belief_dashboard.cli source-network --topic "moral realism"
python -m belief_dashboard.cli source-network --source-id SRC0001
```

Source centrality is based on approved row count, hypotheses touched, total and maximum approved weight, and high uncertainty/defeater/salience signals. It is a navigation aid, not a belief calculation.

## Conflict Detection

An apparent tension is flagged when approved records for the same hypothesis include support and challenge signals. Stronger tensions are not treated as logical contradictions unless the underlying records explicitly say so.

## Topic Filtering

`--topic` uses simple case-insensitive substring matching over evidence text, category, source book, notes, source title, source summary, claim text, claim context, and criteria notes. There is no semantic search in Phase 22.

## Output And Saving

```bash
python -m belief_dashboard.cli evidence-clusters --discord
python -m belief_dashboard.cli source-network --format json
python -m belief_dashboard.cli evidence-clusters --save
python -m belief_dashboard.cli source-network --hypothesis EC --save
```

Saved markdown and JSON reports go to `reports/evidence_networks/`.

## Trace IDs

The trace appendix links cluster/source-network summaries back to source IDs, claim IDs, proposal IDs, categories, hypotheses, weights, and MI5 labels. Use it to audit the queue rows behind a network view.

## Limitations

Network views summarize existing queue records. They do not extract new claims, decide truth, approve proposals, export updates, or change workbooks.
