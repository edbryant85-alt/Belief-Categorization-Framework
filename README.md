# Belief-Categorization-Framework

The active CLI product lives in `belief-dashboard-tool/`.

It now supports the guarded workflow from workbook inspection through queue management, source registration, prompt packet generation, manual imports, proposal review, workbook export preview, timestamped output workbook export, export verification, promotion/rollback support, artifact navigation, command composition, operator preflight, product readiness checks, and an end-to-end demo test.

Start here:

```bash
cd belief-dashboard-tool
python -m pytest
python -m belief_dashboard.cli product-readiness
```

See `belief-dashboard-tool/README.md` for the full command map, safety model, demo workflow, and real workbook workflow.
