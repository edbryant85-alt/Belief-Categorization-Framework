# Study Queue

`study-queue` creates a read-only prioritized study and reflection checklist from approved records, deferred updates, extracted claims, criteria scores, and optional reflection journal notes.

It does not modify workbooks, queue CSVs, source files, export reports, verification reports, promotion reports, or recovery reports. It only writes reports when `--save` is supplied.

## Basic Usage

General study queue:

```bash
python -m belief_dashboard.cli study-queue
```

Filter by hypothesis or topic:

```bash
python -m belief_dashboard.cli study-queue --hypothesis EC
python -m belief_dashboard.cli study-queue --topic "moral realism"
```

Other filters:

```bash
python -m belief_dashboard.cli study-queue --source-id SRC0001
python -m belief_dashboard.cli study-queue --category "Philosophical argument"
python -m belief_dashboard.cli study-queue --min-priority 3
python -m belief_dashboard.cli study-queue --limit 10
```

Output options:

```bash
python -m belief_dashboard.cli study-queue --short
python -m belief_dashboard.cli study-queue --long
python -m belief_dashboard.cli study-queue --discord
python -m belief_dashboard.cli study-queue --format json
```

Save reports:

```bash
python -m belief_dashboard.cli study-queue --save
```

## Candidate Types

Study candidates can come from:

- Approved evidence with uncertainty, defeater strength, low clarity, high salience, or conflicting MI5 impacts.
- Deferred updates.
- Extracted claims marked as objection, defeater, counter-defeater, personal reflection, or with uncertainty notes.
- Reflection journal notes.

## Priority Scoring

The score is deterministic and intentionally simple. It combines approved weight with criteria signals such as uncertainty, defeater strength, existential salience, moral stakes, emotional salience, and a low-clarity bonus.

Priority categories:

- `urgent`: 8+
- `high`: 5 to 7.99
- `medium`: 3 to 4.99
- `low`: below 3

This score prioritizes study. It is not a belief calculation.

## Salience Caveat

High existential, moral, or emotional salience means an item may deserve reflection. It is surfaced separately from evidential strength and should not be treated as stronger evidence by itself.

## Trace IDs

Use `proposal_id`, `claim_id`, and `source_id` to return to:

- `approved_updates.csv`
- `deferred_updates.csv`
- `extracted_claims.csv`
- `criteria_matrix.csv`
- `source_dossiers.csv`

## Difference From Debate Commands

`debate-summary` gives a concise evidence overview by hypothesis. `debate-packet` creates a printable debate prep packet. `study-queue` asks what to read, clarify, revisit, or reflect on next.
