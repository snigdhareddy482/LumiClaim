from __future__ import annotations

import pytest

from backend.math_guard import explain_bill


@pytest.fixture(scope="module")
def explain_payload() -> dict:
	return explain_bill("EOB-001")


def test_breakdown_values(explain_payload: dict) -> None:
	expected = {
		"Amount Billed": 2300.0,
		"Allowed Amount": 1800.0,
		"Insurer Paid": 1300.0,
		"Adjustments": 500.0,
		"Patient Responsibility": 500.0,
	}

	recorded = {item["label"]: float(item["value"]) for item in explain_payload["breakdown"]}

	for label, expected_value in expected.items():
		assert label in recorded, f"Missing breakdown label: {label}"
		assert recorded[label] == pytest.approx(expected_value, abs=0.01)


def test_unverifiable_and_score(explain_payload: dict) -> None:
	assert explain_payload["unverifiable_fields"] == []
	assert explain_payload["verifiability_score"] >= 0.9


def test_takeaway_two_sentences(explain_payload: dict) -> None:
	takeaway = explain_payload["takeaway"]
	assert isinstance(takeaway, str)
	sentence_breaks = takeaway.count(". ")
	assert sentence_breaks == 1
	assert takeaway.endswith(".")
	assert takeaway.startswith("You owe")
	expected_amount = "$500.00"
	assert expected_amount in takeaway
	assert "appeal" in takeaway.lower()