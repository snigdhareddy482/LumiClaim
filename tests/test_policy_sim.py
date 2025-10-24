from __future__ import annotations

import pytest

from backend.math_guard import explain_bill
from backend.policy_sim import simulate_policy


@pytest.fixture(scope="module")
def simulation_result() -> tuple[dict, dict]:
	doc_id = "EOB-001"
	params = {
		"doc_id": doc_id,
		"deductible_remaining": 500.0,
		"coinsurance": 0.2,
		"oop_remaining": 1500.0,
	}
	sim = simulate_policy(**params)
	explain = explain_bill(doc_id)
	return sim, explain


def _patient_resp_from_breakdown(explain_payload: dict) -> float:
	for item in explain_payload.get("breakdown", []):
		if item.get("label") == "Patient Responsibility":
			return float(item.get("value", 0.0))
	raise AssertionError("Breakdown missing patient responsibility entry")


def test_simulation_outputs(simulation_result: tuple[dict, dict]) -> None:
	sim, _ = simulation_result

	assert sim["doc_id"] == "EOB-001"
	assert sim["allowed_total"] == pytest.approx(3600.0, abs=0.01)
	assert sim["expected_patient_resp"] == pytest.approx(1120.0, abs=0.01)

	details = sim["details"]
	assert details["deductible_applied"] == pytest.approx(500.0, abs=0.01)
	assert details["coinsurance_applied"] == pytest.approx(620.0, abs=0.01)
	assert details["oop_cap"] == pytest.approx(1120.0, abs=0.01)


def test_delta_vs_bill(simulation_result: tuple[dict, dict]) -> None:
	sim, explain = simulation_result

	billed_patient_resp = _patient_resp_from_breakdown(explain)
	delta = sim["expected_patient_resp"] - billed_patient_resp
	assert delta == pytest.approx(620.0, abs=0.01)