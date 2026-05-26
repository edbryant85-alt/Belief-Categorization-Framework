# Demo Walkthrough

The end-to-end demo assets live in:

```text
data/sample/end_to_end_demo/
```

The automated integration test copies those assets into a temporary project directory and runs the safe pipeline there. It does not modify the real workbook or real queues.

Run the demo test:

```bash
python -m pytest tests/test_end_to_end_demo.py
```

The test covers:

- workbook inspection;
- queue initialization and validation;
- source registration;
- claim template and prompt packet generation;
- manual import validation and append;
- proposal approval;
- workbook export preview;
- timestamped output workbook export;
- export verification;
- promotion command composition;
- operator preflight;
- product readiness reporting.

The demo intentionally stops before real promotion. Promotion remains an explicit operator action.
