# End-to-End Demo Assets

This folder contains non-private sample data for validating the CLI workflow from workbook inspection through export verification and preflight.

Files:

- `demo_workbook.xlsx`: small workbook with the expected dashboard sheet names and an Evidence Log sheet.
- `sample_source.md`: neutral source text about explanation scope and theory choice.
- `extracted_claims.csv`: one reviewed extracted claim for `SRC0001`.
- `criteria_matrix.csv`: one criteria row for `CLM0001`.
- `proposed_updates.csv`: one proposed Evidence Log update for `PROP0001`.

The content is placeholder philosophical material. It does not contain private user data, medical data, sensitive personal data, or real-user belief content.

The integration test copies these files into a temporary project directory before running the CLI workflow, so the real workbook and real queues are not modified.
