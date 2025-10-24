import json
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_manual_entry_and_explain_flow(tmp_path):
    """End-to-end: POST manual entry, then call /explain/{doc_id} and check response shape."""

    session_id = "testsession1"

    # Build a simple manual rows payload without TOTAL — backend should synthesize TOTAL
    rows = [
        {
            "line_id": "L1",
            "page": 1,
            "cell_id": "manual:R1C1",
            "cpt": "99213",
            "billed": 200.0,
            "allowed": 150.0,
            "insurer_paid": 100.0,
            "adjustments": [{"type": "contractual", "amount": 50.0}],
            "patient_resp": 50.0,
        }
    ]

    payload = {"session_id": session_id, "rows": rows}

    # Post manual entry
    resp = client.post("/session/manual_entry", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok"
    doc_id = body.get("doc_id")
    assert doc_id and doc_id.startswith("EOB-")

    # Now call explain for the returned doc_id
    explain_resp = client.get(f"/explain/{doc_id}")
    # explain may raise if explain pipeline requires a proper TOTAL; assert 200 or an informative error
    assert explain_resp.status_code == 200, f"Explain failed: {explain_resp.status_code} {explain_resp.text}"
    explain_body = explain_resp.json()
    # Basic shape checks
    assert explain_body.get("doc_id") == doc_id
    assert "breakdown" in explain_body
    assert "calcs" in explain_body
    assert "takeaway" in explain_body
    # Ensure the audit_hash exists
    assert "audit_hash" in explain_body
