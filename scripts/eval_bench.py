"""Quick benchmarking script for LumiClaim explain endpoint."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPO_ROOT / "data" / "samples" / "claims_struct.json"
REPORTS_DIR = REPO_ROOT / "reports"

from backend.math_guard import explain_bill
from backend.copywriter import explain_plain
from backend.appeal import build_appeal_docx, build_appeal_pdf


def load_doc_ids() -> list[str]:
	with open(DATA_PATH, "r", encoding="utf-8") as handle:
		payload = json.load(handle)
	return list(payload.keys())


def benchmark() -> dict[str, Any]:
	doc_ids = load_doc_ids()
	rows: list[dict[str, Any]] = []

	for doc_id in doc_ids:
		start = time.perf_counter()
		response = explain_bill(doc_id)
		end = time.perf_counter()

		latency_ms = (end - start) * 1000
		copy_start = time.perf_counter()
		explain_plain(
			doc_id,
			response.get("breakdown"),
			response.get("calcs"),
			response.get("risk_flags"),
			persona="patient",
			level="grade6",
			language="en",
		)
		copy_end = time.perf_counter()
		copy_ms = (copy_end - copy_start) * 1000

		try:
			docx_bytes = build_appeal_docx(doc_id)
			docx_size = len(docx_bytes)
		except Exception:  # pragma: no cover - export failures captured via metrics
			docx_size = 0
		try:
			pdf_bytes = build_appeal_pdf(doc_id)
			pdf_size = len(pdf_bytes)
		except Exception:
			pdf_size = 0

		risk_flags = response.get("risk_flags", [])
		row = {
			"doc_id": doc_id,
			"latency_ms": round(latency_ms, 2),
			"verifiability": round(response.get("verifiability_score", 0.0), 4),
			"warnings": len(response.get("warnings", [])),
			"risk_flag_count": len(risk_flags),
			"copy_ms": round(copy_ms, 2),
			"docx_size_bytes": docx_size,
			"pdf_size_bytes": pdf_size,
		}
		rows.append(row)

	aggregate = {
		"documents": len(rows),
		"avg_latency_ms": round(sum(row["latency_ms"] for row in rows) / len(rows), 2) if rows else 0.0,
		"avg_verifiability": round(sum(row["verifiability"] for row in rows) / len(rows), 4) if rows else 0.0,
		"total_warnings": sum(row["warnings"] for row in rows),
		"total_risk_flags": sum(row["risk_flag_count"] for row in rows),
		"avg_copy_ms": round(sum(row["copy_ms"] for row in rows) / len(rows), 2) if rows else 0.0,
		"avg_docx_size_bytes": round(sum(row["docx_size_bytes"] for row in rows) / len(rows), 2) if rows else 0.0,
		"avg_pdf_size_bytes": round(sum(row["pdf_size_bytes"] for row in rows) / len(rows), 2) if rows else 0.0,
	}

	return {"rows": rows, "aggregate": aggregate}


def main() -> None:
	REPORTS_DIR.mkdir(parents=True, exist_ok=True)
	results = benchmark()
	generated_at = datetime.now(UTC).isoformat(timespec="seconds")
	payload = {
		"generated_at": generated_at,
		"results": results,
	}
	output_path = REPORTS_DIR / "bench.json"
	with open(output_path, "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2)
	print(f"Benchmark results written to {output_path}")


if __name__ == "__main__":
	main()
