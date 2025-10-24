"""Heuristic risk flagging for EOB documents."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from backend.models import ClaimRow


def _safe(value: float | None) -> float:
    return float(value) if value is not None else 0.0


def _patient_resp(row: ClaimRow) -> float:
    if row.patient_resp is not None:
        return float(row.patient_resp)
    adjustments_total = sum(_safe(adj.amount) for adj in row.adjustments)
    return _safe(row.billed) - _safe(row.insurer_paid) - adjustments_total


def _upcoding_risk(rows: Iterable[ClaimRow]) -> list[dict[str, Any]]:
    flags = []
    for row in rows:
        if row.cpt in {"99215", "99214"} and row.allowed and row.allowed > 1500:
            flags.append(
                {
                    "label": "Upcoding risk",
                    "severity": "high",
                    "rationale": f"CPT {row.cpt} allowed amount ${row.allowed:,.2f} looks unusually high.",
                }
            )
    return flags


def _duplicate_charge_risk(rows: Iterable[ClaimRow]) -> list[dict[str, Any]]:
    flags = []
    seen = defaultdict(set)
    for row in rows:
        if row.cpt:
            seen[row.cpt].add(row.modifier or "")
    for cpt, modifiers in seen.items():
        if len(modifiers) > 1:
            flags.append(
                {
                    "label": "Duplicate charge risk",
                    "severity": "medium",
                    "rationale": f"CPT {cpt} billed with multiple modifiers: {', '.join(sorted(modifiers))}.",
                }
            )
    return flags


def _missing_adjustment_risk(rows: Iterable[ClaimRow]) -> list[dict[str, Any]]:
    flags = []
    for row in rows:
        adjustments_total = sum(_safe(adj.amount) for adj in row.adjustments)
        residual = _safe(row.billed) - _safe(row.insurer_paid) - adjustments_total - _patient_resp(row)
        if residual > 100:  # heuristic threshold
            flags.append(
                {
                    "label": "Missing adjustment risk",
                    "severity": "medium",
                    "rationale": (
                        f"Line {row.line_id} residual ${residual:,.2f} exceeds recorded adjustments;"
                        " consider contractual allowances."
                    ),
                }
            )
    return flags


def build_risk_flags(rows: Iterable[ClaimRow]) -> list[dict[str, Any]]:
    """Evaluate heuristic risk flags for the provided claim rows."""

    all_rows = list(rows)
    flags: list[dict[str, Any]] = []
    flags.extend(_upcoding_risk(all_rows))
    flags.extend(_duplicate_charge_risk(all_rows))
    flags.extend(_missing_adjustment_risk(all_rows))

    # Deduplicate by label + rationale
    unique = []
    seen = set()
    for flag in flags:
        key = (flag["label"], flag["rationale"])
        if key not in seen:
            seen.add(key)
            unique.append(flag)
    return unique
