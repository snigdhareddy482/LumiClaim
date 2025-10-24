"""Simple policy simulation helpers for projecting patient responsibility."""

from __future__ import annotations

from typing import Any

from backend.math_guard import _load_struct


def simulate_policy(
	doc_id: str,
	deductible_remaining: float,
	coinsurance: float,
	oop_remaining: float,
	*,
	session_id: str | None = None,
) -> dict[str, Any]:
	"""Estimate the patient's responsibility under a basic deductible/coinsurance model."""

	rows = _load_struct(doc_id, session_id=session_id)
	allowed_total = sum(row.allowed for row in rows)

	deductible_applied = min(allowed_total, max(deductible_remaining, 0.0))
	remaining_after_deductible = max(allowed_total - deductible_applied, 0.0)

	coinsurance_rate = max(min(coinsurance, 1.0), 0.0)
	coinsurance_applied = remaining_after_deductible * coinsurance_rate

	expected_patient_resp = deductible_applied + coinsurance_applied

	if oop_remaining >= 0:
		oop_cap = min(expected_patient_resp, oop_remaining)
		expected_patient_resp = oop_cap
	else:
		oop_cap = expected_patient_resp

	return {
		"doc_id": doc_id,
		"allowed_total": allowed_total,
		"expected_patient_resp": expected_patient_resp,
		"details": {
			"deductible_applied": deductible_applied,
			"coinsurance_applied": coinsurance_applied,
			"oop_cap": oop_cap,
		},
	}
