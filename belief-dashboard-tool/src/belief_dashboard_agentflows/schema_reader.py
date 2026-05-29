from __future__ import annotations

from belief_dashboard.schemas import CRITERIA_SCORE_FIELDS, MI5_COLUMNS, QUEUE_SCHEMAS


def queue_schema(queue_name: str) -> list[str]:
    return list(QUEUE_SCHEMAS[queue_name])


def all_queue_schemas() -> dict[str, list[str]]:
    return {name: list(headers) for name, headers in QUEUE_SCHEMAS.items()}


def criteria_score_fields() -> list[str]:
    return list(CRITERIA_SCORE_FIELDS)


def mi5_columns() -> list[str]:
    return list(MI5_COLUMNS)
