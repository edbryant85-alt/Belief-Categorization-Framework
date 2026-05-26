from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from belief_dashboard.dossiers import find_source_dossier
from belief_dashboard.schemas import QUEUE_SCHEMAS


def create_claim_template(
    source_id: str,
    queue_dir: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    dossier = find_source_dossier(source_id, queue_dir, config)
    source_path = Path(dossier["original_file_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"Registered source file no longer exists: {source_path}")

    output_path = Path(output_dir) / f"{source_id}_extracted_claims_template.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(QUEUE_SCHEMAS["extracted_claims"])

    return {"source_id": source_id, "template_path": str(output_path)}
