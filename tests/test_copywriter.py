from __future__ import annotations

import itertools
import re
from typing import Iterable, cast

import pytest

from backend.copywriter import explain_plain
from backend.math_guard import explain_bill

PERSONAS: tuple[str, ...] = ("patient", "payer", "provider")
LEVELS: tuple[str, ...] = ("grade4", "grade6", "grade8", "pro")
_NUMBER_PATTERN = re.compile(r"\$[0-9,]+\.\d{2}")


@pytest.fixture(scope="module")
def explain_payload() -> dict[str, object]:
    return cast(dict[str, object], explain_bill("EOB-001"))


@pytest.fixture(scope="module")
def allowed_numbers(explain_payload: dict[str, object]) -> set[str]:
    valid: set[str] = set()

    def _add_value(value: object) -> None:
        if isinstance(value, (int, float)):
            valid.add(f"${float(value):,.2f}")

    breakdown = explain_payload.get("breakdown", [])
    if isinstance(breakdown, Iterable):
        for entry in breakdown:
            if isinstance(entry, dict):
                _add_value(entry.get("value"))

    calcs = explain_payload.get("calcs", [])
    if isinstance(calcs, Iterable):
        for calc in calcs:
            if not isinstance(calc, dict):
                continue
            _add_value(calc.get("result"))
            inputs = calc.get("inputs", [])
            if isinstance(inputs, Iterable):
                for item in inputs:
                    if isinstance(item, dict):
                        _add_value(item.get("value"))

    return valid


@pytest.mark.parametrize("persona,level", itertools.product(PERSONAS, LEVELS))
def test_explain_plain_numbers(explain_payload: dict[str, object], allowed_numbers: set[str], persona: str, level: str) -> None:
    text = explain_plain(
        explain_payload["doc_id"],  # type: ignore[index]
        explain_payload.get("breakdown"),  # type: ignore[arg-type]
        explain_payload.get("calcs"),  # type: ignore[arg-type]
        explain_payload.get("risk_flags"),  # type: ignore[arg-type]
        persona=persona,
        level=level,
        language="en",
    )

    assert text.strip(), f"Empty output for persona={persona} level={level}"

    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "Expected at least one bullet line"
    for line in lines:
        assert line.startswith("- "), f"Line does not start with bullet prefix: {line}"

    numbers = _NUMBER_PATTERN.findall(text)
    for number in numbers:
        assert number in allowed_numbers, f"Unexpected number {number} for persona={persona} level={level}"
