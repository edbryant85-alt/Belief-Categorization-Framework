from __future__ import annotations


def missing_items(expected: list[str], found: list[str]) -> list[str]:
    found_set = set(found)
    return [item for item in expected if item not in found_set]


def present_items(expected: list[str], found: list[str]) -> list[str]:
    found_set = set(found)
    return [item for item in expected if item in found_set]


def overall_status(
    *,
    workbook_exists: bool,
    missing_expected_sheets: list[str],
    missing_required_columns: list[str],
    missing_hypothesis_mi5_columns: list[str],
) -> str:
    if not workbook_exists:
        return "fail"
    if missing_expected_sheets or missing_required_columns:
        return "fail"
    if missing_hypothesis_mi5_columns:
        return "warning"
    return "pass"
