# Debate Packets

`debate-packet` creates a printable, traceable prep packet from approved records.

It is read-only. It does not modify workbooks, queue CSVs, source files, export reports, verification reports, promotion reports, or recovery reports. It only writes packet reports when `--save` is supplied.

## Basic Usage

Create a packet for one hypothesis:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC
```

Create a topic-filtered packet:

```bash
python -m belief_dashboard.cli debate-packet --topic "moral realism"
```

Combine both:

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --topic "moral realism"
```

## Output Modes

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --short
python -m belief_dashboard.cli debate-packet --hypothesis EC --long
python -m belief_dashboard.cli debate-packet --hypothesis EC --discord
python -m belief_dashboard.cli debate-packet --hypothesis EC --format json
```

`--discord` prints only the compact copy-ready section.

## Filters

```bash
python -m belief_dashboard.cli debate-packet --hypothesis EC --min-weight 3
python -m belief_dashboard.cli debate-packet --hypothesis EC --exported-only
python -m belief_dashboard.cli debate-packet --hypothesis EC --source-id SRC0001
python -m belief_dashboard.cli debate-packet --hypothesis EC --category "Philosophical argument"
```

Topic filtering is a simple case-insensitive substring search over evidence text, category, source book, notes, source title/summary, and claim text/context.

## Packet Structure

Packets include:

- Header and caveat
- Hypothesis/topic overview
- Position snapshot
- Strongest support and challenge
- Objections/defeaters
- Counter-objections/counter-defeaters
- Criteria highlights
- Source trace
- Open questions
- Debate framing
- Discord copy section
- Trace appendix

## Trace IDs

Use the trace appendix to return to queue records:

- `proposal_id` in `approved_updates.csv`
- `claim_id` in `extracted_claims.csv` and `criteria_matrix.csv`
- `source_id` in `source_dossiers.csv`

## Limitations

This summarizes approved records and does not tell you what to believe.

Objection and counter-objection detection is heuristic. Emotional and existential salience are surfaced separately from evidential weight and should not be treated as evidence strength by themselves.
