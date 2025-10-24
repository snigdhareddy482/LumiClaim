from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_appeal_docx_export() -> None:
    docx_module = pytest.importorskip("docx")
    document_cls = docx_module.Document

    response = client.post("/appeal_docx", json={"doc_id": "EOB-001"})
    assert response.status_code == 200
    assert (
        response.headers.get("content-type")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    payload = response.content
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) > 1024, "DOCX payload unexpectedly small"

    doc = document_cls(BytesIO(payload))
    paragraph_text = [p.text for p in doc.paragraphs if p.text.strip()]
    assert paragraph_text, "Generated DOCX contains no visible paragraphs"


def test_appeal_pdf_export() -> None:
    pdf_module = pytest.importorskip("PyPDF2")
    pdf_reader_cls = pdf_module.PdfReader

    response = client.post("/appeal_pdf", json={"doc_id": "EOB-001"})
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"

    payload = response.content
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) > 1024, "PDF payload unexpectedly small"

    reader = pdf_reader_cls(BytesIO(payload))
    assert reader.pages, "Generated PDF has no pages"
