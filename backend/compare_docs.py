"""Helpers for comparing structured EOB documents."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from backend.math_guard import _load_struct
from backend.models import ClaimRow


def _adjustment_sum(row: ClaimRow) -> float:
    return sum(float(adj.amount) for adj in row.adjustments if adj.amount is not None)


def _patient_responsibility(row: ClaimRow) -> float:
    if row.patient_resp is not None:
        return row.patient_resp
    return row.billed - row.insurer_paid - _adjustment_sum(row)


def _row_index(rows: Iterable[ClaimRow]) -> Dict[str, ClaimRow]:
    return {row.line_id: row for row in rows if row.line_id}


def _confidence_and_cause(row_a: ClaimRow | None, row_b: ClaimRow | None) -> Tuple[str, float]:
    if row_a is None and row_b is not None:
        return ("new service captured in latest adjudication", 0.7)
    if row_b is None and row_a is not None:
        return ("line removed or bundled", 0.7)

    assert row_a is not None and row_b is not None

    if row_a.modifier != row_b.modifier:
        if row_a.modifier and not row_b.modifier:
            return (f"modifier {row_a.modifier} removed → potential rebundling", 0.85)
        if not row_a.modifier and row_b.modifier:
            return (f"modifier {row_b.modifier} added", 0.85)
        return (f"modifier changed {row_a.modifier} → {row_b.modifier}", 0.8)

    allowed_a, allowed_b = row_a.allowed, row_b.allowed
    if allowed_a is not None and allowed_b is not None and allowed_a != allowed_b:
        return ("allowed amount shifted against contract", 0.75)

    adjustments_a = _adjustment_sum(row_a)
    adjustments_b = _adjustment_sum(row_b)
    if adjustments_a != adjustments_b:
        return ("adjustment schedule updated", 0.7)

    billed_a, billed_b = row_a.billed, row_b.billed
    if billed_a != billed_b:
        return ("billed amount changed", 0.65)

    return ("patient responsibility recalculated", 0.6)


def _impact(row_a: ClaimRow | None, row_b: ClaimRow | None) -> float:
    if row_a is None and row_b is None:
        return 0.0
    if row_a is None:
        assert row_b is not None
        return _patient_responsibility(row_b)
    if row_b is None:
        assert row_a is not None
        return -_patient_responsibility(row_a)
    return _patient_responsibility(row_b) - _patient_responsibility(row_a)


def _citation(row: ClaimRow | None, doc_id: str) -> Dict[str, Any]:
    if row is None:
        return {"doc": f"{doc_id}.pdf"}
    return {
        "doc": f"{doc_id}.pdf",
        "page": row.page,
        "cell": row.cell_id,
        "line_id": row.line_id,
    }


def compare_docs(doc_id_a: str, doc_id_b: str, session_id: str | None = None) -> dict[str, Any]:
    """Compute a diff between two structured EOB documents."""

    rows_a = _row_index(_load_struct(doc_id_a, session_id=session_id))
    rows_b = _row_index(_load_struct(doc_id_b, session_id=session_id))

    diff: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []

    all_line_ids = set(rows_a) | set(rows_b)

    for line_id in sorted(all_line_ids):
        row_a = rows_a.get(line_id)
        row_b = rows_b.get(line_id)

        if row_a is None and row_b is None:
            continue

        impact = _impact(row_a, row_b)
        cause, confidence = _confidence_and_cause(row_a, row_b)

        if row_a is None:
            change_type = "added"
        elif row_b is None:
            change_type = "removed"
        else:
            if impact == 0 and cause == "patient responsibility recalculated":
                # No meaningful change detected.
                continue
            change_type = "changed"

        diff.append(
            {
                "type": change_type,
                "line_id": line_id,
                "impact": round(impact, 2),
                "root_cause": cause,
                "confidence": round(confidence, 2),
            }
        )

        if row_b is not None:
            citations.append(_citation(row_b, doc_id_b))
        elif row_a is not None:
            citations.append(_citation(row_a, doc_id_a))

    if not diff:
        citations.append({"doc": f"{doc_id_b}.pdf"})

    return {"diff": diff, "citations": citations}
