from __future__ import annotations

import pytest

from backend.math_guard import explain_bill


def _risk_labels(doc_id: str) -> set[str]:
    return {flag.get("label", "") for flag in explain_bill(doc_id).get("risk_flags", [])}


@pytest.mark.parametrize("doc_id", ["EOB-003", "EOB-004", "EOB-005"])
def test_sample_corpus_quality(doc_id: str) -> None:
    payload = explain_bill(doc_id)
    breakdown = payload.get("breakdown", []) or []
    assert len(breakdown) == 5
    assert payload.get("verifiability_score", 0.0) >= 0.9
    assert payload.get("unverifiable_fields", []) == []


@pytest.mark.parametrize(
    "doc_id", [
        pytest.param("EOB-005", id="duplicate"),
        pytest.param("EOB-006", id="missing_adjustment"),
    ],
)
def test_sample_risk_flags(doc_id: str) -> None:
    flags = _risk_labels(doc_id)
    if doc_id == "EOB-005":
        assert "Duplicate charge risk" in flags
    elif doc_id == "EOB-006":
        assert "Missing adjustment risk" in flags
        payload = explain_bill(doc_id)
        unverifiable = set(payload.get("unverifiable_fields", []))
        assert {"Adjustments", "Patient Responsibility"}.issubset(unverifiable)
    else:  # pragma: no cover
        pytest.fail(f"Unexpected doc id {doc_id}")
