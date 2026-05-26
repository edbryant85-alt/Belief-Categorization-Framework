# Debate Summaries

`debate-summary` creates read-only debate-prep summaries from approved queue records.

It does not modify workbooks, queues, exports, verification reports, promotion state, rollback archives, or source files. It only writes reports when `--save` is supplied.

## Basic Usage

Summarize one hypothesis:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC
```

Summarize all configured hypotheses:

```bash
python -m belief_dashboard.cli debate-summary --all
```

Save markdown and JSON reports:

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --save
```

## MI5 Mapping

For the selected hypothesis, approved rows are grouped as:

- Strong support: `Highly likely`, `Almost certain`
- Moderate support: `Likely / probable`
- Neutral / mixed: `Roughly even chance` or blank
- Moderate challenge: `Unlikely`
- Strong challenge: `Highly unlikely`, `Remote chance`

Rows are ranked by approved weight, MI5 impact strength, approved date, then proposal ID.

## Filters

```bash
python -m belief_dashboard.cli debate-summary --hypothesis EC --min-weight 3
python -m belief_dashboard.cli debate-summary --hypothesis EC --exported-only
python -m belief_dashboard.cli debate-summary --hypothesis EC --source-id SRC0001
python -m belief_dashboard.cli debate-summary --hypothesis EC --category "Philosophical argument"
```

`--short` is compact. `--long` includes more notes, source titles, claim context, and criteria scores. `--discord` prints a concise copy-friendly format.

## Trace IDs

Every item includes proposal, claim, and source IDs. Use them to return to:

- `approved_updates.csv` by `proposal_id`
- `extracted_claims.csv` by `claim_id`
- `source_dossiers.csv` by `source_id`
- `criteria_matrix.csv` by `claim_id` and `source_id`

## Limitations

This is a debate-prep view over approved records. It is not a final declaration of belief and does not calculate a formal posterior probability.

Defeater and objection detection is heuristic. It looks for terms such as `defeater`, `objection`, `counterargument`, and `challenge`, plus claim types like `objection`, `defeater`, and `counter_defeater`.

Emotional or existential salience is surfaced separately from evidential weight. Do not treat emotional salience as evidential strength.
