from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_export_explain_docx_contains_content() -> None:
    docx_module = pytest.importorskip("docx")
    document_cls = docx_module.Document

    # ensure a minimal document exists so explain/export can run
    client.post("/session/manual_entry", json={
        "session_id": "test-session",
        "doc_id": "EOB-TEST",
        "rows": [
            {"line_id": "R1", "billed": 100.0, "allowed": 80.0, "insurer_paid": 60.0, "patient_resp": 40.0}
        ],
    })

    payload = {"doc_id": "EOB-TEST", "persona": "patient", "level": "grade6", "language": "en"}
    response = client.post("/export/explain_docx", json=payload)
    assert response.status_code == 200
    assert (
        response.headers.get("content-type")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    data = response.content
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 1024, "DOCX payload unexpectedly small"

    doc = document_cls(BytesIO(data))
    texts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    assert texts, "Generated explain DOCX contains no visible paragraphs"


def test_export_explain_pdf_contains_pages() -> None:
    pdf_module = pytest.importorskip("PyPDF2")
    pdf_reader_cls = pdf_module.PdfReader

    # ensure the same minimal document exists for PDF export
    client.post("/session/manual_entry", json={
        "session_id": "test-session",
        "doc_id": "EOB-TEST",
        "rows": [
            {"line_id": "R1", "billed": 100.0, "allowed": 80.0, "insurer_paid": 60.0, "patient_resp": 40.0}
        ],
    })

    payload = {"doc_id": "EOB-TEST", "persona": "patient", "level": "grade6", "language": "en"}
    response = client.post("/export/explain_pdf", json=payload)
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"

    data = response.content
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 1024, "PDF payload unexpectedly small"

    reader = pdf_reader_cls(BytesIO(data))
    assert reader.pages, "Generated explain PDF has no pages"
