"""Construct evidence graphs linking financial figures to their sources."""

from __future__ import annotations

from typing import Any

from backend.math_guard import _load_struct, explain_bill


def _format_amount(label: str, value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        suffix = "unknown" if value in (None, "") else str(value)
        return f"{label}: {suffix}"
    return f"{label}: ${numeric:,.2f}"


def build_evidence_graph(doc_id: str, session_id: str | None = None) -> dict:
    """Create a lightweight evidence graph for the requested document."""

    explain_payload = explain_bill(doc_id, session_id=session_id)
    rows = _load_struct(doc_id, session_id=session_id)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def ensure_node(node_id: str, **attrs: Any) -> None:
        if node_id not in nodes:
            node = {"id": node_id}
            node.update(attrs)
            nodes[node_id] = node

    def add_edge(source: str, target: str, edge_type: str) -> None:
        if source and target:
            edges.append({"source": source, "target": target, "type": edge_type})

    # Amount nodes from breakdown
    for item in explain_payload.get("breakdown", []):
        label = item.get("label", "Unknown")
        value = item.get("value")
        node_id = f"amount:{label}"
        ensure_node(node_id, label=_format_amount(label, value), kind="amount")

        source = item.get("source") or {}
        page = source.get("page")
        cell = source.get("cell")
        if page is not None and cell:
            cell_node_id = f"cell:{page}:{cell}"
            ensure_node(cell_node_id, label=f"Page {page} • {cell}", kind="source")
            add_edge(node_id, cell_node_id, "derived_from")

    # Ensure anchor amount nodes exist even if missing from breakdown
    ensure_node("amount:Allowed Amount", label="Allowed Amount", kind="amount")
    ensure_node("amount:Adjustments", label="Adjustments", kind="amount")
    ensure_node("amount:Patient Responsibility", label="Patient Responsibility", kind="amount")

    # CPT and modifier nodes
    for row in rows:
        if getattr(row, "cpt", None):
            cpt_node_id = f"cpt:{row.cpt}"
            ensure_node(cpt_node_id, label=f"CPT {row.cpt}", kind="code")
            add_edge(cpt_node_id, "amount:Allowed Amount", "supports")
        if getattr(row, "modifier", None):
            modifier_node_id = f"modifier:{row.modifier}"
            ensure_node(modifier_node_id, label=f"Modifier {row.modifier}", kind="code")
            add_edge(modifier_node_id, "amount:Adjustments", "modifies")

    # Policy knobs provide context, even if placeholders
    ensure_node("policy:deductible", label="Policy: Deductible", kind="policy")
    ensure_node("policy:coinsurance", label="Policy: Coinsurance", kind="policy")
    add_edge("policy:deductible", "amount:Patient Responsibility", "influences")
    add_edge("policy:coinsurance", "amount:Patient Responsibility", "influences")

    # Highlight warnings as contradicting edges when present
    for warning in explain_payload.get("warnings", []):
        warn_node_id = f"warning:{hash(warning)}"
        ensure_node(warn_node_id, label=str(warning), kind="warning")
        add_edge(warn_node_id, "amount:Patient Responsibility", "contradicts")

    return {"nodes": list(nodes.values()), "edges": edges}
