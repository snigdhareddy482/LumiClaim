"""PDF/DOCX/Image extraction helpers.

Provides parse_pdf, parse_docx, parse_image and a small normalizer that
maps common table headers to the project schema. Optional dependencies
are used when available and the functions degrade gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple, Dict, Any

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - optional
    pdfplumber = None

try:
    import camelot  # type: ignore
except Exception:  # pragma: no cover - optional
    camelot = None

try:
    from docx import Document  # type: ignore
except Exception:  # pragma: no cover - optional
    Document = None

try:
    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional
    Image = None
    pytesseract = None


SchemaRow = Dict[str, Any]


def _map_header(h: str) -> str:
    h = (h or "").strip().lower()
    mapping = {
        "cpt": "cpt",
        "procedure code": "cpt",
        "code": "cpt",
        "procedure": "cpt",
        "modifier": "modifier",
        "mod": "modifier",
        "billed": "billed",
        "amount billed": "billed",
        "charge": "billed",
        "allowed": "allowed",
        "allowed amount": "allowed",
        "insurer paid": "insurer_paid",
        "paid": "insurer_paid",
        "patient responsibility": "patient_resp",
        "patient resp": "patient_resp",
        "adjustments": "adjustments",
        "adj": "adjustments",
        "description": "description",
    }
    for key, val in mapping.items():
        if key in h:
            return val
    return h.replace(" ", "_")


def _fabricate_cell_id(table_idx: int, row_idx: int, col_idx: int) -> str:
    return f"tbl{table_idx}:R{row_idx}C{col_idx}"


def _normalize_table(table_rows: List[List[str]], page: int, table_idx: int) -> List[SchemaRow]:
    """Normalize a table (list-of-rows) into the schema rows.

    Expects first row to be headers. If headers are missing, uses positional
    guesses.
    """
    rows: List[SchemaRow] = []
    if not table_rows:
        return rows

    headers = table_rows[0]
    mapped = [(_map_header(h), idx) for idx, h in enumerate(headers)]

    for r_idx, raw_row in enumerate(table_rows[1:], start=1):
        out: SchemaRow = {
            "line_id": None,
            "page": page,
            "cell_id": _fabricate_cell_id(table_idx, r_idx, 0),
            "cpt": None,
            "modifier": None,
            "billed": None,
            "allowed": None,
            "insurer_paid": None,
            "adjustments": [],
            "patient_resp": None,
            "description": None,
        }
        for col_idx, cell in enumerate(raw_row):
            if col_idx >= len(mapped):
                # if there are more columns than headers, fabricate a key
                key = f"col_{col_idx}"
            else:
                key = mapped[col_idx][0]

            val = cell.strip() if isinstance(cell, str) else cell
            if key == "adjustments":
                # split on common separators
                parts = [p.strip() for p in str(val).split(";") if p.strip()]
                out["adjustments"] = parts
            elif key in {"billed", "allowed", "insurer_paid", "patient_resp"}:
                # try to parse numeric remove $ and commas
                try:
                    num = float(str(val).replace("$", "").replace(",", ""))
                except Exception:
                    num = None
                out[key] = num
            else:
                out[key] = val

        # ensure cell_id contains row index
        out["cell_id"] = out.get("cell_id") or _fabricate_cell_id(table_idx, r_idx, 0)
        out["line_id"] = f"L-{page}-{table_idx}-{r_idx}"
        rows.append(out)

    return rows


def parse_pdf(path: str) -> Tuple[List[SchemaRow], List[str], List[str]]:
    """Extract per-page raw text and attempt to parse tables into schema rows.

    Returns (rows, raw_text_pages, notes).
    """
    p = Path(path)
    rows: List[SchemaRow] = []
    raw_pages: List[str] = []
    notes: List[str] = []

    if pdfplumber is None:
        notes.append("pdfplumber unavailable; no text extracted")
    else:
        try:
            with pdfplumber.open(p) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    raw_pages.append(text)
        except Exception as exc:
            notes.append(f"pdfplumber_failed:{exc}")

    # Try tables with camelot if present
    if camelot is None:
        notes.append("camelot unavailable; skipping table extraction")
    else:
        try:
            tables = camelot.read_pdf(str(p), pages="all")
            for t_idx, table in enumerate(tables):
                # table.df is pandas DataFrame; convert to list-of-lists of strings
                data = table.df.fillna("").astype(str).values.tolist()
                page_no = int(table.parsing_report.get("page", 1)) if hasattr(table, "parsing_report") else 1
                norm = _normalize_table(data, page_no, t_idx)
                rows.extend(norm)
        except Exception as exc:
            notes.append(f"camelot_failed:{exc}")

    return rows, raw_pages, notes


def parse_docx(path: str) -> Tuple[List[SchemaRow], List[str], List[str]]:
    """Extract text and tables from a DOCX file.

    Returns (rows, raw_text_pages, notes).
    """
    p = Path(path)
    rows: List[SchemaRow] = []
    raw_pages: List[str] = []
    notes: List[str] = []

    if Document is None:
        notes.append("python-docx unavailable; cannot parse docx")
        return rows, raw_pages, notes

    try:
        doc = Document(str(p))
    except Exception as exc:
        notes.append(f"docx_open_failed:{exc}")
        return rows, raw_pages, notes

    # collect paragraphs as a single 'page' (docx has no pages)
    paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    raw_pages.append("\n".join(paras))

    # process tables
    for t_idx, table in enumerate(doc.tables):
        data: List[List[str]] = []
        for r in table.rows:
            data.append([c.text for c in r.cells])
        norm = _normalize_table(data, 1, t_idx)
        rows.extend(norm)

    return rows, raw_pages, notes


def parse_image(path: str) -> Tuple[List[SchemaRow], List[str], List[str]]:
    """OCR an image into text pages and return empty rows.

    Returns (rows, raw_text_pages, notes).
    """
    rows: List[SchemaRow] = []
    raw_pages: List[str] = []
    notes: List[str] = []

    if Image is None or pytesseract is None:
        notes.append("OCR unavailable")
        return rows, raw_pages, notes

    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        raw_pages.append(text)
    except Exception as exc:
        notes.append(f"ocr_failed:{exc}")

    return rows, raw_pages, notes
