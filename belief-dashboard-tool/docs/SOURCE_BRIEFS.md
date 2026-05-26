# Source Briefs

`source-brief` creates a compact read-only dossier for one `source_id`.

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001
```

It reads queue CSV files and prints a markdown-style report. It does not modify workbooks, queues, source files, proposals, approvals, export tracking fields, or reports unless `--save` is supplied.

## What It Includes

- Header with source ID, title, timestamp, type, author/speaker, date added, and processing status.
- Source metadata from `source_dossiers.csv`, including original file path, URL, context, summary, worldview, reliability notes, framing notes, and operator notes.
- Optional bounded raw excerpt from `original_file_path`.
- Extracted claims with claim IDs, claim type, preview, argument summary, hypothesis links, uncertainty notes, and status.
- Criteria highlights for high relevance, reliability, argument strength, explanatory power, defeater strength, uncertainty, existential/moral/emotional salience, and low clarity.
- Proposal/review outcomes with proposed, approved, rejected, and deferred counts plus IDs and reasons where available.
- Approved hypothesis impacts using the same MI5 support/challenge mapping as `debate-summary`.
- Source-specific unresolved study items using the study queue logic.
- Debate-use notes: strongest line of use, main caution, and best next question.
- Discord copy section and trace appendix.

## Options

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001 --format json
python -m belief_dashboard.cli source-brief --source-id SRC0001 --discord
python -m belief_dashboard.cli source-brief --source-id SRC0001 --short
python -m belief_dashboard.cli source-brief --source-id SRC0001 --long
python -m belief_dashboard.cli source-brief --source-id SRC0001 --limit 10
```

`--short` trims detail for console scanning. `--long` includes more source, claim, proposal, criteria, and trace context.

## Raw Excerpts

Raw excerpts are off by default unless enabled in config. Use:

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001 --include-raw-excerpt
```

The command reads only from the source dossier's `original_file_path`, includes up to `source_briefs.raw_excerpt_max_characters`, and marks truncated excerpts. Missing files produce a warning but do not fail the brief.

## Saving

```bash
python -m belief_dashboard.cli source-brief --source-id SRC0001 --save
```

Saved reports are written to `reports/source_briefs/`:

- `source_brief_SRC0001_YYYY-MM-DD_HHMMSS.md`
- `source_brief_SRC0001_YYYY-MM-DD_HHMMSS.json`

Without `--save`, nothing is written.

## Trace Appendix

The trace appendix lists the source ID, claim IDs, proposal IDs, review status, category, weight, and relevant MI5 labels. Use it to return to the exact queue rows behind a brief.

## Relationship To Other Commands

`debate-summary` summarizes approved evidence by hypothesis. `debate-packet` builds a fuller debate-prep packet. `study-queue` prioritizes unresolved study work. `source-brief` starts from one source and gathers all known source-level records in one place.

## Limitations

The report only summarizes queue records that already exist. It does not extract new claims, infer missing arguments, approve or reject proposals, export approved updates, or update the workbook.
