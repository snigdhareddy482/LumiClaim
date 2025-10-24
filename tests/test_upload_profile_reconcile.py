import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def _make_sample_docx(path: Path):
    # Create a simple docx with a single table using python-docx if available
    try:
        from docx import Document
    except Exception:
        pytest.skip("python-docx not available in test env")

    doc = Document()
    table = doc.add_table(rows=2, cols=5)
    hdr = ["CPT", "Billed", "Allowed", "Insurer Paid", "Patient Responsibility"]
    for i, h in enumerate(hdr):
        table.rows[0].cells[i].text = h
    row = ["99213", "100", "80", "50", "30"]
    for i, v in enumerate(row):
        table.rows[1].cells[i].text = str(v)
    doc.save(str(path))


def test_upload_docx_parses_table(tmp_path: Path):
    fn = tmp_path / "sample.docx"
    _make_sample_docx(fn)
    with open(fn, "rb") as fh:
        files = {"file": (fn.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        resp = client.post("/upload_eob", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "doc_id" in body
    preview = body.get("preview") or {}
    rows = preview.get("rows") or []
    # parser should find at least one row from the table
    assert len(rows) >= 1


def test_profile_set_get_and_simulate_uses_profile():
    session_id = "profile-test-session"
    payload = {
        "session_id": session_id,
        "deductible_individual": 2000.0,
        "deductible_remaining": 500.0,
        "coinsurance": 0.2,
        "oop_max": 5000.0,
        "oop_remaining": 3000.0,
    }
    r = client.post("/profile/set", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("profile")

    # load profile
    r2 = client.get("/profile/get", params={"session_id": session_id})
    assert r2.status_code == 200
    prof = r2.json().get("profile")
    assert prof and float(prof.get("coinsurance")) == 0.2

    # call simulate without numeric fields so backend should use profile
    sim_payload = {"doc_id": "EOB-001", "session_id": session_id}
    r3 = client.post("/simulate", json=sim_payload)
    assert r3.status_code == 200, r3.text
    sim = r3.json()
    assert "expected_patient_resp" in sim
    assert float(sim.get("expected_patient_resp", 0.0)) >= 0.0


def test_reconcile_with_duplicate_line_anomaly():
    session_id = "recon-test-session"
    # Post three manual entries with the same line_id so reconcile flags duplicate_line_id
    doc_ids = []
    for i in range(3):
        rows = [
            {
                "line_id": "L1",
                "page": 1,
                "cell_id": "manual:R1C1",
                "cpt": "99213",
                "billed": 100 + i * 10,
                "allowed": 80 + i * 5,
                "insurer_paid": 60 + i * 3,
                "adjustments": [],
                "patient_resp": 40 + i * 2,
            }
        ]
        resp = client.post("/session/manual_entry", json={"session_id": session_id, "rows": rows})
        assert resp.status_code == 200, resp.text
        doc_id = resp.json().get("doc_id")
        doc_ids.append(doc_id)

    # run reconcile
    r = client.get(f"/reconcile/session/{session_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    # doc_count may include previous artifacts in a shared workspace; ensure at least 3 docs
    assert body.get("doc_count", 0) >= 3
    anoms = body.get("anomalies") or []
    # find duplicate_line_id anomaly and ensure our created docs are included
    dup = next((a for a in anoms if a.get("type") == "duplicate_line_id"), None)
    assert dup is not None, f"expected duplicate_line_id anomaly, got: {anoms}"
    anomaly_docs = set(dup.get("docs") or [])
    assert set(doc_ids).issubset(anomaly_docs), f"our docs {doc_ids} not subset of anomaly docs {anomaly_docs}"
