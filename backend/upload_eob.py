"""Handlers and helpers for multipart EOB uploads.

This module tries to extract text from uploaded files using pure-Python
libraries if available and degrades gracefully when optional packages
or external OCR binaries are missing.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from docx import Document  # python-docx
except Exception:  # pragma: no cover - optional
    Document = None

try:  # PDF extraction if available
    import PyPDF2  # type: ignore
except Exception:  # pragma: no cover - optional
    PyPDF2 = None

try:  # image OCR support (optional)
    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional
    Image = None
    pytesseract = None

from fastapi import HTTPException

from backend import extractors
from backend.session import (
    SESSION_ROOT,
    append_claim_rows,
    append_raw_pages,
    ensure_session_dirs,
    ensure_session_files,
)
from backend.upload import redact_text


BASE_SESSION_PATH = SESSION_ROOT

MAX_BYTES = 15 * 1024 * 1024  # 15 MB

ALLOWED_EXT = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}


def _make_session_dirs(session_id: str) -> Tuple[Path, Path]:
    ensure_session_files(session_id)
    _, raw, extracted = ensure_session_dirs(session_id)
    return raw, extracted


def _safe_doc_id() -> str:
    """Return a sequential persistent doc id in the form EOB-###.

    Stores a tiny JSON file under data/user_sessions/_counter.json with
    structure {counter, created_by, created_at, updated_at}. If an older
    _counter.txt exists (legacy), attempt to migrate it.
    """
    import datetime

    counter_file = BASE_SESSION_PATH / "_counter.json"
    # migrate legacy text file
    legacy = BASE_SESSION_PATH / "_counter.txt"
    try:
        if legacy.exists() and not counter_file.exists():
            try:
                raw = legacy.read_text(encoding="utf-8").strip()
                n = int(raw)
            except Exception:
                n = 0
            payload = {
                "counter": max(1, n),
                "created_by": "migrated",
                # timezone-aware timestamps
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            counter_file.write_text(json.dumps(payload), encoding="utf-8")

        if not counter_file.exists():
            payload = {
                "counter": 1,
                "created_by": "system",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            counter_file.write_text(json.dumps(payload), encoding="utf-8")
            num = 1
        else:
            raw = counter_file.read_text(encoding="utf-8").strip()
            data = {}
            try:
                data = json.loads(raw)
                num = int(data.get("counter", 0)) + 1
            except Exception:
                num = secrets.randbelow(1000)

            created_by = "system"
            created_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                if isinstance(data, dict):
                    created_by = data.get("created_by", created_by)
                    created_at = data.get("created_at", created_at)
            except Exception:
                pass

            payload = {
                "counter": int(num),
                "created_by": created_by,
                "created_at": created_at,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            counter_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # fallback to random when filesystem is unavailable
        num = secrets.randbelow(1000)

    return f"EOB-{int(num):03d}"


def _preview_snippet(text: str, length: int = 200) -> str:
    s = " ".join(text.strip().split())
    return s[:length]


def _detect_file_ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def _save_raw_file(raw_dir: Path, filename: str, content: bytes) -> Path:
    target = raw_dir / filename
    with open(target, "wb") as fh:
        fh.write(content)
    return target


def _save_extracted_json(extracted_dir: Path, doc_id: str, payload: Dict[str, Any]) -> None:
    path = extracted_dir / f"{doc_id}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _extract_from_docx_bytes(content: bytes) -> Tuple[str, int]:
    if Document is None:
        raise RuntimeError("python-docx not installed")
    from io import BytesIO

    buf = BytesIO(content)
    doc = Document(buf)
    text_parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    text = "\n".join(text_parts)
    # docx doesn't have pages in this context; report paragraphs as pages approximation
    pages = max(1, len(doc.paragraphs) // 40)
    return text, pages


def _extract_from_pdf_bytes(content: bytes) -> Tuple[str, int]:
    if PyPDF2 is None:
        raise RuntimeError("PyPDF2 not installed")
    from io import BytesIO

    reader = PyPDF2.PdfReader(BytesIO(content))
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    pages = len(reader.pages)
    return "\n".join(texts), pages


def _extract_from_image_bytes(content: bytes) -> Tuple[str, int]:
    if Image is None or pytesseract is None:
        raise RuntimeError("PIL/pytesseract not available")
    from io import BytesIO

    img = Image.open(BytesIO(content))
    text = pytesseract.image_to_string(img)
    return text, 1


def handle_upload_file(filename: str, content: bytes, session_id: str | None = None) -> Dict[str, Any]:
    """Validate, save the raw file, attempt extraction, redact, and save artifacts.

    Returns a dict with session_id, doc_id, file_type, pages, notes, preview.
    Raises HTTPException for friendly errors.
    """

    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")

    ext = _detect_file_ext(filename)
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large; maximum allowed is 15MB")

    if session_id is None:
        raise HTTPException(status_code=400, detail="No session. Call /session/start first.")

    raw_dir, extracted_dir = _make_session_dirs(session_id)
    safe_name = "".join(ch for ch in filename if ch in (string.ascii_letters + string.digits + ".-_"))
    saved_path = _save_raw_file(raw_dir, safe_name or filename, content)

    notes_parts = []
    extracted_text = ""
    pages = 0
    parsed_rows: list = []
    raw_pages: list = []

    # Try format-specific extraction (text layer) and parsers for structured rows
    try:
        if ext == ".docx":
            if Document is None:
                notes_parts.append("DOCX parsing unavailable")
            else:
                extracted_text, pages = _extract_from_docx_bytes(content)
                # parse docx tables/text for structured rows
                try:
                    parsed_rows, raw_pages, parse_notes = extractors.parse_docx(str(saved_path))
                    notes_parts.extend(parse_notes or [])
                except Exception as _:
                    parsed_rows, raw_pages = [], []
        elif ext == ".pdf":
            if PyPDF2 is None:
                notes_parts.append("PDF text extraction unavailable")
            else:
                extracted_text, pages = _extract_from_pdf_bytes(content)
                try:
                    parsed_rows, raw_pages, parse_notes = extractors.parse_pdf(str(saved_path))
                    notes_parts.extend(parse_notes or [])
                except Exception:
                    parsed_rows, raw_pages = [], []
        elif ext in {".png", ".jpg", ".jpeg"}:
            # try OCR
            try:
                extracted_text, pages = _extract_from_image_bytes(content)
                try:
                    parsed_rows, raw_pages, parse_notes = extractors.parse_image(str(saved_path))
                    notes_parts.extend(parse_notes or [])
                except Exception:
                    parsed_rows, raw_pages = [], []
            except RuntimeError:
                notes_parts.append("OCR unavailable; text layer only")
    except Exception as exc:  # pragma: no cover - defensive
        notes_parts.append(f"extraction_failed: {str(exc)}")

    # If we failed to extract any text, keep minimal placeholder
    if not extracted_text:
        extracted_text = ""

    # Redact PHI
    redacted = redact_text(extracted_text)

    # Save extracted artifact
    doc_id = _safe_doc_id()
    artifact: Dict[str, Any] = {
        "doc_id": doc_id,
        "session_id": session_id,
        "filename": safe_name,
        "file_type": ext.lstrip("."),
        "pages": pages,
        "notes": notes_parts,
        "extracted_text_preview": _preview_snippet(redacted),
    }

    # Persist extracted text and metadata
    _save_extracted_json(extracted_dir, doc_id, {**artifact, "redacted_text": redacted})

    # If parser produced structured rows/raw pages, append them to per-session files
    sanitized_rows: list[dict[str, Any]] = []
    sanitized_pages: list[dict[str, Any]] = []

    try:
        claims_struct_path = extracted_dir / "claims_struct.json"
        claims_raw_path = extracted_dir / "claims_raw.json"

        parsed_rows = locals().get("parsed_rows", []) or []
        raw_pages = locals().get("raw_pages", []) or []

        for row in parsed_rows:
            if not isinstance(row, dict):
                continue
            cleaned = dict(row)
            cleaned["doc_id"] = doc_id
            for key, value in list(cleaned.items()):
                if isinstance(value, str) and value.strip():
                    cleaned[key] = redact_text(value)
            sanitized_rows.append(cleaned)

        existing_struct = []
        if claims_struct_path.exists():
            try:
                existing_struct = json.loads(claims_struct_path.read_text(encoding="utf-8"))
                if not isinstance(existing_struct, list):
                    existing_struct = []
            except Exception:
                existing_struct = []

        if sanitized_rows:
            existing_struct.extend(sanitized_rows)
            claims_struct_path.write_text(json.dumps(existing_struct, ensure_ascii=False, indent=2), encoding="utf-8")
            append_claim_rows(session_id, sanitized_rows)

        existing_raw = []
        if claims_raw_path.exists():
            try:
                existing_raw = json.loads(claims_raw_path.read_text(encoding="utf-8"))
                if not isinstance(existing_raw, list):
                    existing_raw = []
            except Exception:
                existing_raw = []

        for index, txt in enumerate(raw_pages, start=1):
            snippet = redact_text(str(txt))
            entry = {"doc_id": doc_id, "page": index, "text": snippet}
            existing_raw.append(entry)
            sanitized_pages.append(entry)

        if sanitized_pages:
            claims_raw_path.write_text(json.dumps(existing_raw, ensure_ascii=False, indent=2), encoding="utf-8")
            append_raw_pages(session_id, sanitized_pages)
    except Exception:
        # non-fatal; do not block the upload if writing artifacts fails
        pass

    rows_preview = sanitized_rows[:3]

    text_snippets: list[str] = []
    for entry in sanitized_pages[:2]:
        snippet = _preview_snippet(str(entry.get("text", "")), length=200)
        if snippet:
            text_snippets.append(snippet)

    if not text_snippets:
        text_snippets.append(artifact["extracted_text_preview"])

    return {
        "session_id": session_id,
        "doc_id": doc_id,
        "preview": {
            "rows": rows_preview,
            "text_snippets": text_snippets,
        },
    }
