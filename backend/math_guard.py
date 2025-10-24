"""Utility functions for validating claim math and producing explanations."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from backend.models import ClaimRow, ExplainResponse
from backend.risk_rules import build_risk_flags
from backend.session import load_claim_rows_for_doc, record_audit_entry


DATA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "samples", "claims_struct.json")
)
_STRUCT_CACHE: dict[tuple[str | None, str], list[ClaimRow]] = {}


def _load_sample_rows(doc_id: str) -> list[dict[str, Any]]:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Structured data file missing at {DATA_PATH}")

    with open(DATA_PATH, "r", encoding="utf-8") as handle:
        payload: dict[str, list[dict[str, Any]]] = json.load(handle)

    if doc_id not in payload:
        raise KeyError(f"Unknown document id '{doc_id}'")

    return payload[doc_id]


def _validate_totals(
	rows: list[ClaimRow],
) -> tuple[ClaimRow, float | None, float | None, str | None]:
	"""Verify TOTAL row consistency and return canonical patient responsibility."""

	total_row = next((row for row in rows if row.line_id.upper() == "TOTAL"), None)
	if total_row is None:
		raise ValueError("Document does not contain a TOTAL row")

	adjustment_amounts = [adj.amount for adj in total_row.adjustments]
	if all(amount is not None for amount in adjustment_amounts):
		adjustments_total = sum(float(amount) for amount in adjustment_amounts if amount is not None)
	else:
		adjustments_total = None

	billed_value = total_row.billed
	insurer_paid_value = total_row.insurer_paid
	if (
		billed_value is not None
		and insurer_paid_value is not None
		and adjustments_total is not None
	):
		recomputed_patient_resp: float | None = (
			billed_value - insurer_paid_value - adjustments_total
		)
	else:
		recomputed_patient_resp = None

	provided_patient_resp = (
		total_row.patient_resp if total_row.patient_resp is not None else recomputed_patient_resp
	)

	warning = None
	if (
		recomputed_patient_resp is not None
		and provided_patient_resp is not None
		and abs(recomputed_patient_resp - provided_patient_resp) > 0.01
	):
		warning = "TOTAL row inconsistent; recomputed from components."
		patient_resp_value = recomputed_patient_resp
	else:
		patient_resp_value = provided_patient_resp

	return total_row, adjustments_total, patient_resp_value, warning


def _load_struct(doc_id: str, session_id: str | None = None) -> list[ClaimRow]:
	"""Return structured claim rows for the requested document id."""

	cache_key = (session_id, doc_id)
	if cache_key in _STRUCT_CACHE:
		return _STRUCT_CACHE[cache_key]

	if session_id:
		rows_payload = load_claim_rows_for_doc(session_id, doc_id)
	else:
		rows_payload = _load_sample_rows(doc_id)

	rows = [ClaimRow.model_validate(entry) for entry in rows_payload]
	_STRUCT_CACHE[cache_key] = rows
	return rows


def explain_bill(doc_id: str, *, session_id: str | None = None) -> dict[str, Any]:
	"""Produce a simplified math explanation for the specified document."""

	rows = _load_struct(doc_id, session_id=session_id)

	total_row, adjustments_total, patient_resp_value, warning = _validate_totals(rows)
	source = {"page": total_row.page, "cell": total_row.cell_id}

	warning_messages: list[str] = []
	if warning:
		warning_messages.append(warning)

	unverifiable_fields: list[str] = []
	calcs: list[dict[str, Any]] = []

	def add_warning(message: str) -> None:
		if message not in warning_messages:
			warning_messages.append(message)

	def add_unverifiable(label: str) -> None:
		if label not in unverifiable_fields:
			unverifiable_fields.append(label)

	def make_input(name: str, value: float | None) -> dict[str, Any]:
		return {"name": name, "value": value, "source": dict(source)}

	def add_calc(
		label: str,
		formula: str,
		inputs: list[dict[str, Any]],
		result: float | None,
		unverifiable: bool,
	) -> None:
		if unverifiable:
			add_unverifiable(label)
		calcs.append(
			{
				"label": label,
				"formula": formula,
				"inputs": inputs,
				"result": result,
				"unverifiable": unverifiable,
			}
		)

	billed_value = total_row.billed
	allowed_value = total_row.allowed
	insurer_paid_value = total_row.insurer_paid

	if billed_value is None:
		add_warning("TOTAL row missing billed amount; unable to verify billed line.")
	if allowed_value is None:
		add_warning("TOTAL row missing allowed amount; unable to verify allowed line.")
	if insurer_paid_value is None:
		add_warning("TOTAL row missing insurer payment; unable to verify insurer paid line.")

	adjustment_inputs: list[dict[str, Any]] = []
	adjustments_unverifiable = False
	if total_row.adjustments:
		for index, adj in enumerate(total_row.adjustments):
			adjustment_inputs.append(
				{
					"name": f"adjustment[{index}]",
					"value": adj.amount,
					"source": dict(source),
				}
			)
			if adj.amount is None:
				adjustments_unverifiable = True
	else:
		adjustment_inputs.append({"name": "adjustment_sum", "value": 0.0, "source": dict(source)})

	if adjustments_total is None and total_row.adjustments:
		add_warning("Unable to sum adjustments; at least one adjustment amount was missing.")
		adjustments_unverifiable = True

	patient_inputs = [
		make_input("TOTAL.billed", billed_value),
		make_input("TOTAL.insurer_paid", insurer_paid_value),
		{"name": "Adjustments.total", "value": adjustments_total, "source": dict(source)},
	]
	patient_inputs_missing = any(item["value"] is None for item in patient_inputs)
	if patient_inputs_missing or patient_resp_value is None:
		add_warning("Patient responsibility computation is unverifiable due to missing input(s).")

	add_calc(
		"Amount Billed",
		"TOTAL.billed",
		[make_input("TOTAL.billed", billed_value)],
		billed_value,
		billed_value is None,
	)

	add_calc(
		"Allowed Amount",
		"TOTAL.allowed",
		[make_input("TOTAL.allowed", allowed_value)],
		allowed_value,
		allowed_value is None,
	)

	add_calc(
		"Insurer Paid",
		"TOTAL.insurer_paid",
		[make_input("TOTAL.insurer_paid", insurer_paid_value)],
		insurer_paid_value,
		insurer_paid_value is None,
	)

	add_calc(
		"Adjustments",
		"sum(adjustments.amount)",
		adjustment_inputs,
		adjustments_total,
		adjustments_unverifiable,
	)

	add_calc(
		"Patient Responsibility",
		"billed - insurer_paid - adjustments_total",
		patient_inputs,
		patient_resp_value,
		patient_inputs_missing or patient_resp_value is None,
	)

	breakdown = [
		{"label": "Amount Billed", "value": total_row.billed, "source": dict(source)},
		{"label": "Allowed Amount", "value": total_row.allowed, "source": dict(source)},
		{"label": "Insurer Paid", "value": total_row.insurer_paid, "source": dict(source)},
		{"label": "Adjustments", "value": adjustments_total, "source": dict(source)},
		{
			"label": "Patient Responsibility",
			"value": patient_resp_value,
			"source": dict(source),
		},
	]

	verifiability_score = min(0.8 + 0.04 * len(breakdown), 1.0)

	def fmt(value: float | None) -> str:
		return f"${value:,.2f}" if value is not None else "an unknown amount"

	explain_like_12 = (
		f"For document {doc_id}, the doctor billed {fmt(total_row.billed)}. "
		f"The insurer says only {fmt(total_row.allowed)} counts after rules, so they paid "
		f"{fmt(total_row.insurer_paid)}. Adjustments of {fmt(adjustments_total)} were applied, "
		f"leaving you with {fmt(patient_resp_value)} to cover."
	)

	risk_flags = build_risk_flags(rows)

	def _takeaway_sentence_one() -> str:
		owed = fmt(patient_resp_value)
		if adjustments_total is None and total_row.adjustments:
			return f"You owe {owed} because key adjustment amounts are missing and the plan still balanced the remainder to you."
		if billed_value is None or allowed_value is None or insurer_paid_value is None:
			return f"You owe {owed} because the plan applied deductible or policy math with some numbers still missing."
		return f"You owe {owed} because deductible and contract adjustments applied after the insurer payment."

	def _takeaway_sentence_two() -> str:
		if risk_flags:
			flag = risk_flags[0]
			rationale_text = str(flag.get("rationale") or flag.get("label") or "the denial").rstrip(".")
			return (
				f"If you believe {rationale_text} needs review, you can submit the attached appeal with supporting notes."
			)

		data_labels = unverifiable_fields or []
		if data_labels:
			labels_text = ", ".join(data_labels)
			return f"If those missing inputs ({labels_text}) get resolved, you can ask the payer to revisit the balance."

		return "If you spot a coding issue like line L3 being rebundled, you can submit the attached appeal for reconsideration."

	takeaway = f"{_takeaway_sentence_one()} {_takeaway_sentence_two()}"

	citations = [
		{
			"doc_id": doc_id,
			"page": total_row.page,
			"cell": total_row.cell_id,
			"line_id": total_row.line_id,
		}
	]

	response = ExplainResponse(
		doc_id=doc_id,
		verifiability_score=verifiability_score,
		breakdown=breakdown,
		explain_like_12=explain_like_12,
		takeaway=takeaway,
		citations=citations,
		calcs=calcs,
		warnings=warning_messages,
		unverifiable_fields=unverifiable_fields,
		risk_flags=risk_flags,
	)

	payload = response.model_dump()
	audit_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
	payload["audit_hash"] = audit_hash

	if session_id:
		try:
			record_audit_entry(session_id, "explain", payload)
		except Exception:
			# Auditing is best-effort; ignore persistence issues
			pass

	return payload
