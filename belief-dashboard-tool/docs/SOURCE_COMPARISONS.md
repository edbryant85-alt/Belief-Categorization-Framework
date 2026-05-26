# Source Comparisons

Phase 21 adds two read-only commands:

- `compare-sources`: compare two or more selected source IDs.
- `source-map`: summarize all sources affecting a hypothesis or topic.

Both commands read queue records only. They do not modify workbooks, queues, sources, proposals, approvals, exports, verification reports, or promotion/recovery files. Reports are written only when `--save` is supplied.

## Compare Sources

```bash
python -m belief_dashboard.cli compare-sources --source-id SRC0001 --source-id SRC0002
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002
```

Useful filters:

```bash
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --hypothesis EC
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --topic "moral realism"
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --min-weight 3
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --exported-only
```

Output options:

```bash
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --short
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --long
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --discord
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --format json
```

The report includes source metadata, high-level counts, hypothesis impact comparison, apparent conflict map, shared themes, objections/defeaters, criteria highlights, study priorities, debate-use notes, Discord copy text, and a trace appendix.

## Source Map

```bash
python -m belief_dashboard.cli source-map --hypothesis EC
python -m belief_dashboard.cli source-map --topic "moral realism"
python -m belief_dashboard.cli source-map --hypothesis EC --topic "moral realism"
```

`source-map` ranks matching sources by approved rows, strongest approved weight, support/challenge counts, and uncertainty/defeater signals. Ranking is deterministic.

## Conflict Map Logic

A potential tension is flagged when approved rows from different sources affect the same hypothesis in opposite directions:

- one row supports or strongly supports the hypothesis;
- another row challenges or strongly challenges it.

Rows with both weights at least 3 are labeled stronger. This is a transparent heuristic, not a claim of logical contradiction.

## Topic Filtering

`--topic` uses simple case-insensitive substring matching over approved evidence, category, source book, notes, source title, source summary, claim text, claim context, and criteria notes. There is no semantic search in Phase 21.

## Saving

```bash
python -m belief_dashboard.cli compare-sources --sources SRC0001,SRC0002 --save
python -m belief_dashboard.cli source-map --hypothesis EC --save
```

Saved reports go to `reports/source_comparisons/` as markdown and JSON.

## Trace IDs

The trace appendix lists source IDs, claim IDs, proposal IDs, review status, category, weight, MI5 labels, and source book/title. Use it to inspect or audit the queue rows behind a comparison.

## Limitations

The commands summarize existing queue records. They do not extract new claims, approve/reject/defer proposals, export approved updates, modify workbooks, or decide which hypothesis is true.
