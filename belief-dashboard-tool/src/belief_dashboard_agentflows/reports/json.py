from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2) + "\n"


def write_json_report(path: str | Path, report: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_json(report), encoding="utf-8")
    return output
