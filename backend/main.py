"""Minimal FastAPI application for LumiClaim backend."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

load_dotenv()

from fastapi import File, FastAPI, HTTPException, Query, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse

from backend.appeal import build_appeal, build_appeal_docx, build_appeal_pdf
from backend.llm import generate_appeal_letter, summarize_bill
from backend.compare_docs import compare_docs
from backend.copywriter import explain_plain
from backend.llm_adapters.gemini_adapter import NotConfigured, verbalize
from backend.egraph import build_evidence_graph
from backend.exporter import build_explain_docx
from backend.math_guard import explain_bill
from backend.models import AskRequest, PSLRequest, SimulateRequest
from backend.policy_sim import simulate_policy
from backend.profile import load_profile, save_profile
from backend.rag import answer_with_citations
from backend.session import (
	delete_session,
	is_builtin_doc,
	list_sessions,
	resolve_session,
	start_session,
    track_appeal_outcome,
    list_appeal_history,
)

from backend.upload import redact_text, store_redacted_document
from backend.upload_eob import _safe_doc_id, handle_upload_file
from backend.sbc_parser import parse_sbc
from backend import auth

from pydantic import BaseModel

class AuthRequest(BaseModel):
    username: str
    password: str

class AppealTrackRequest(BaseModel):
    session_id: str
    doc_id: str
    status: str
    notes: str = ""

class AppealAIRequest(BaseModel):
    session_id: str
    doc_id: str
    user_context: str = ""

class AIExplainRequest(BaseModel):
    session_id: str
    doc_id: str
    persona: str = "patient"
    grade_level: str = "8th Grade"

DATA_ROOT = Path("data")


def _with_audit_hash(payload: dict[str, Any]) -> dict[str, Any]:
	material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	hash_value = hashlib.sha256(material.encode("utf-8")).hexdigest()
	response = dict(payload)
	response["audit_hash"] = hash_value
	return response


def _resolve_session_for_docs(session_id: str | None, doc_ids: Iterable[str]) -> str | None:
	"""Resolve a session id for document-centric endpoints with built-in fallbacks."""

	resolved = resolve_session(session_id, required=False)
	if resolved is None:
		if any(not is_builtin_doc(doc) for doc in doc_ids):
			raise HTTPException(status_code=400, detail="No session. Call /session/start first.")
	return resolved


def _parse_appeal_payload(payload: dict[str, Any]) -> tuple[str, str, str, float | None, str | None]:
	"""Normalize appeal request payload fields and validate required parameters."""

	doc_id = str(payload.get("doc_id") or "").strip()
	if not doc_id:
		raise HTTPException(status_code=400, detail="doc_id is required")

	tone = str(payload.get("tone") or "polite").strip() or "polite"
	audience = str(payload.get("audience") or "payer").strip() or "payer"

	psl_delta_raw = payload.get("psl_delta")
	psl_delta: float | None
	if psl_delta_raw is None:
		psl_delta = None
	else:
		try:
			psl_delta = float(psl_delta_raw)
		except (TypeError, ValueError) as exc:
			raise HTTPException(status_code=400, detail="psl_delta must be numeric") from exc

	session_hint_raw = payload.get("session_id")
	session_hint = None
	if isinstance(session_hint_raw, str):
		session_hint = session_hint_raw.strip() or None
	elif session_hint_raw is not None:
		session_hint = str(session_hint_raw).strip() or None

	return doc_id, tone, audience, psl_delta, session_hint




class ChatRequest(BaseModel):
    question: str
    doc_id: str | None = None
    session_id: str | None = None


app = FastAPI(title="LumiClaim", version="0.1.0")

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
	"""Redirect callers to the interactive documentation."""
	return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check() -> dict[str, object]:
	"""Return readiness metadata for external monitors."""
	return {"ok": True, "service": "LumiClaim", "version": "0.1.0"}


@app.get("/auth/status/{username}")
def auth_status(username: str) -> dict[str, str]:
    """Check if user needs migration or is active."""
    status = auth.get_user_status(username)
    return {"status": status}


@app.post("/auth/register")
def auth_register(req: AuthRequest) -> dict[str, bool]:
    """Register new user or set password for migrating user."""
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Missing fields")
        
    # Prevent overwriting existing password
    if auth.has_password(req.username):
         raise HTTPException(status_code=403, detail="User already exists. Please login.")
         
    success = auth.register_user(req.username, req.password)
    return {"success": success}


@app.post("/auth/login")
def auth_login(req: AuthRequest) -> dict[str, bool]:
    """Verify credentials."""
    valid = auth.verify_credentials(req.username, req.password)
    if not valid:
        # Return HTTP 401 for clarity? Or json success=False?
        # Frontend handles boolean cleanly.
        return {"success": False}
    return {"success": True}


@app.post("/sbc/parse")
async def sbc_parse_route(
    file: UploadFile = File(...),
    session_id: str | None = Form(None)
) -> dict[str, Any]:
    """Parse an uploaded SBC PDF and return extracted plan attributes."""
    content = await file.read()
    
    # Save to temp file for parser (which expects path)
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
        
    try:
        attrs = parse_sbc(tmp_path)
        
        # Save full text for RAG if session available
        if "full_text" in attrs:
            text = attrs.pop("full_text")
            if session_id and session_id.strip():
                try:
                    # Resolve session dir manually or use session helper
                    s_id = session_id.strip()
                    # Basic sanitization
                    if ".." not in s_id and "/" not in s_id: 
                         # Use original filename to allow multiple docs (e.g. Dental, Medical)
                         safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-")
                         dest = DATA_ROOT / "user_sessions" / s_id / "extracted" / f"SBC_{safe_name}.txt"
                         if dest.parent.exists():
                             dest.write_text(text, encoding="utf-8")
                except Exception:
                    pass
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass
            
    return _with_audit_hash(attrs)


@app.post("/upload")
async def upload(payload: dict[str, Any]) -> dict[str, object]:
	"""Accept raw document text, redact PII, and retain only the sanitized copy."""

	content = payload.get("content")
	if content is None or not str(content).strip():
		raise HTTPException(status_code=400, detail="content is required")
	doc_id_raw = str(payload.get("doc_id", "")).strip()
	doc_id = doc_id_raw or f"UPLD-{secrets.token_hex(4).upper()}"
	redacted = redact_text(str(content))
	store_redacted_document(doc_id, redacted)
	response = {"doc_id": doc_id, "content": redacted, "status": "redacted"}
	return _with_audit_hash(response)



@app.post("/upload_eob")
async def upload_eob(
	file: UploadFile = File(...),
	session_id: str | None = Query(None),
) -> dict[str, object]:
	"""Accept a multipart file (pdf/docx/png/jpg), extract text, redact PHI and store artifacts.

	Returns session_id, doc_id, file_type, pages, notes, and a small preview.
	"""

	if not file:
		raise HTTPException(status_code=400, detail="file is required")

	# Read content into memory to enforce size guard
	content = await file.read()
	resolved_session = resolve_session(session_id, required=True)
	try:
		result = handle_upload_file(file.filename or "upload", content, resolved_session)
	except HTTPException:
		raise
	except Exception as exc:
		# Defensive: return a friendly error
		raise HTTPException(status_code=500, detail=f"upload failed: {str(exc)}") from exc

	response = {
		"session_id": resolved_session,
		"doc_id": result["doc_id"],
		"preview": result.get("preview", {}),
	}
	return _with_audit_hash(response)


@app.get("/explain/{doc_id}")
async def explain(
	doc_id: str,
	persona: str = Query("patient"),
	level: str = Query("grade6"),
	language: str = Query("en"),
	session_id: str | None = Query(None),
) -> dict[str, object]:
	"""Return a high-level math breakdown for the requested document."""

	resolved_session = _resolve_session_for_docs(session_id, [doc_id])
	try:
		explain_payload = explain_bill(doc_id, session_id=resolved_session)
		# Try Gemini AI first for natural language explanation
		try:
			# We only pass keys relevant to the explanation to avoid context window bloat if heavy
			# But explain_bill payload is usually small enough.
			# We'll pass the whole thing as verbalize expects a dict.
			explain_payload["explain_like_12"] = verbalize(
				persona,
				level,
				explain_payload
			)
			explain_payload["generated_by"] = "gemini"
		except Exception as exc:
			# Fallback if AI not configured or fails
			print(f"Verbalize failed: {exc}")
			explain_payload["explain_like_12"] = explain_payload.get("explain_like_12") or "AI explanation unavailable."
			explain_payload["explain_like_12"] = explain_plain(
				doc_id,
				explain_payload.get("breakdown"),
				explain_payload.get("calcs"),
				explain_payload.get("risk_flags"),
				persona=persona,
				level=level,
				language=language,
			)
			explain_payload["generated_by"] = "deterministic"
		return _with_audit_hash(explain_payload)
	except FileNotFoundError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except KeyError as exc:
		raise HTTPException(status_code=404, detail=str(exc)) from exc
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.post("/simulate")
async def simulate(request: SimulateRequest) -> dict[str, object]:
	"""Compare policy simulation results with the billed patient responsibility."""

	resolved_session = _resolve_session_for_docs(request.session_id, [request.doc_id])

	ded_rem = request.deductible_remaining
	coins = request.coinsurance
	oop_rem = request.oop_remaining
	if (ded_rem is None or coins is None or oop_rem is None) and resolved_session:
		try:
			profile = load_profile(resolved_session)
			if ded_rem is None:
				ded_rem = profile.get("deductible_remaining")
			if coins is None:
				coins = profile.get("coinsurance")
			if oop_rem is None:
				oop_rem = profile.get("oop_remaining")
		except FileNotFoundError:
			pass

	missing: list[str] = []
	if ded_rem is None:
		missing.append("deductible_remaining")
	if coins is None:
		missing.append("coinsurance")
	if oop_rem is None:
		missing.append("oop_remaining")
	if missing:
		raise HTTPException(status_code=400, detail=f"Missing required simulation fields: {', '.join(missing)}")

	assert ded_rem is not None
	assert coins is not None
	assert oop_rem is not None

	try:
		ded_value = float(ded_rem)
		coins_value = float(coins)
		oop_value = float(oop_rem)
	except (TypeError, ValueError) as exc:
		raise HTTPException(status_code=400, detail="Simulation parameters must be numeric") from exc

	try:
		result = simulate_policy(
			request.doc_id,
			deductible_remaining=ded_value,
			coinsurance=coins_value,
			oop_remaining=oop_value,
			session_id=resolved_session,
		)
		return _with_audit_hash(result)
	except FileNotFoundError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except KeyError as exc:
		raise HTTPException(status_code=404, detail=str(exc)) from exc
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/export/explain_docx")
async def export_explain_docx(payload: dict[str, Any]) -> StreamingResponse:
	"""Export a single document explanation as a DOCX file."""

	doc_id = str(payload.get("doc_id") or "").strip()
	if not doc_id:
		raise HTTPException(status_code=400, detail="doc_id is required")

	persona = str(payload.get("persona") or "patient").strip() or "patient"
	level = str(payload.get("level") or "grade6").strip() or "grade6"
	language = str(payload.get("language") or "en").strip() or "en"

	session_hint_raw = payload.get("session_id")
	session_hint = None
	if isinstance(session_hint_raw, str):
		session_hint = session_hint_raw.strip() or None
	elif session_hint_raw is not None:
		session_hint = str(session_hint_raw).strip() or None

	resolved_session = _resolve_session_for_docs(session_hint, [doc_id])

	try:
		docx_bytes = build_explain_docx(
			doc_id,
			persona=persona,
			level=level,
			language=language,
			session_id=resolved_session,
		)
	except FileNotFoundError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except KeyError as exc:
		raise HTTPException(status_code=404, detail=str(exc)) from exc
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	headers = {
		"Content-Disposition": f'attachment; filename="explain_{doc_id}.docx"'
	}
	return StreamingResponse(
		BytesIO(docx_bytes),
		media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		headers=headers,
	)


@app.post("/export/explain_pdf")
async def export_explain_pdf(payload: dict[str, Any]) -> StreamingResponse:
	"""Export a single document explanation as a PDF.

	Expects same JSON as /export/explain_docx
	"""
	# PDF export is not available in this deployment because build_explain_pdf
	# is not provided by backend.exporter; signal explicit 501 so callers can
	# fall back to /export/explain_docx or another export mechanism.
	raise HTTPException(status_code=501, detail="PDF export not implemented on this deployment; use /export/explain_docx instead")


@app.post("/appeal_pdf")
async def appeal_pdf(payload: dict[str, Any]) -> StreamingResponse:
	"""Generate and stream a PDF version of the appeal letter."""

	doc_id, tone, audience, psl_delta, session_hint = _parse_appeal_payload(payload)
	resolved_session = _resolve_session_for_docs(session_hint, [doc_id])

	try:
		pdf_bytes = build_appeal_pdf(
			doc_id,
			tone=tone,
			audience=audience,
			psl_delta=psl_delta,
			session_id=resolved_session,
		)
	except FileNotFoundError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except KeyError as exc:
		raise HTTPException(status_code=404, detail=str(exc)) from exc
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	headers = {
		"Content-Disposition": f'attachment; filename="appeal_{doc_id}.pdf"'
	}
	return StreamingResponse(
		BytesIO(pdf_bytes),
		media_type="application/pdf",
		headers=headers,
	)



@app.post("/profile/set")
async def profile_set(payload: dict[str, Any]) -> dict[str, object]:
	"""Set or update a per-session profile. Persisted to data/user_sessions/<session_id>/profile.json.

	Expects a JSON payload containing at minimum `session_id`. Numeric fields are validated and
	missing values are inferred when possible (e.g., deductible_remaining <- deductible_individual).
	"""
	resolved_session = resolve_session(payload.get("session_id"), required=True)
	assert resolved_session is not None
	payload = dict(payload)
	payload["session_id"] = resolved_session
	try:
		profile = save_profile(payload)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc

	return _with_audit_hash({"status": "ok", "profile": profile})


@app.get("/profile/get")
async def profile_get(session_id: str | None = Query(None)) -> dict[str, object]:
	"""Return the stored profile for the provided session_id."""
	resolved_session = resolve_session(session_id, required=True)
	assert resolved_session is not None
	try:
		profile = load_profile(resolved_session)
	except FileNotFoundError:
		raise HTTPException(status_code=404, detail="profile not found")
	except Exception as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc

	return _with_audit_hash({"profile": profile})


class StartSessionRequest(BaseModel):
    session_id: str | None = None

@app.post("/session/start")
async def session_start_route(payload: StartSessionRequest | None = None) -> dict[str, str]:
    """Create and initialize a new session (or resume if session_id provided)."""
    requested_id = payload.session_id if payload else None
    return start_session(requested_id)


@app.get("/session/list")
async def session_list_route() -> dict[str, Any]:
	"""List known sessions and their metadata."""
	return list_sessions()


def _load_session_claims(resolved_session: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	base_dir = DATA_ROOT / "user_sessions" / resolved_session
	extracted_dir = base_dir / "extracted"
	if not extracted_dir.exists():
		raise HTTPException(status_code=404, detail="session not found or no extracted artifacts")

	claims_path = base_dir / "claims_struct.json"
	rows: list[dict[str, Any]] = []
	if claims_path.exists():
		try:
			data = json.loads(claims_path.read_text(encoding="utf-8"))
			if isinstance(data, list):
				rows = [row for row in data if isinstance(row, dict)]
		except Exception:
			rows = []

	docs: list[dict[str, Any]] = []
	for candidate in extracted_dir.glob("EOB-*.json"):
		if not candidate.is_file():
			continue
		try:
			payload = json.loads(candidate.read_text(encoding="utf-8"))
			if isinstance(payload, dict):
				meta = {key: payload.get(key) for key in ("doc_id", "filename", "file_type", "pages", "notes", "session_id")}
				meta = {k: v for k, v in meta.items() if v is not None}
				docs.append(meta)
		except Exception:
			continue

	docs.sort(key=lambda item: item.get("doc_id", ""))
	return rows, docs


def _latest_audit_entry(resolved_session: str, prefix: str) -> dict[str, str] | None:
	"""Return metadata for the newest audit artifact matching the prefix."""

	audits_dir = DATA_ROOT / "user_sessions" / resolved_session / "audits"
	if not audits_dir.exists():
		return None

	pattern = f"{prefix}_*.json"
	candidates = sorted(audits_dir.glob(pattern), key=lambda path: path.name, reverse=True)
	for candidate in candidates:
		stem = candidate.stem
		if "_" not in stem:
			continue
		_, timestamp = stem.split("_", 1)
		try:
			content = json.loads(candidate.read_text(encoding="utf-8"))
		except Exception:
			content = {}

		audit_hash = str(content.get("audit_hash") or "").strip()
		if not audit_hash:
			try:
				audit_hash = hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()[:16]
			except Exception:
				try:
					audit_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
				except Exception:
					audit_hash = ""

		return {"timestamp": timestamp, "audit_hash": audit_hash}

	return None


@app.get("/session/claims")
async def session_claims(session_id: str | None = Query(None)) -> dict[str, Any]:
	"""Return aggregated claim rows and document metadata for a session."""
	resolved_session = resolve_session(session_id, required=True)
	assert resolved_session is not None
	rows, docs = _load_session_claims(resolved_session)
	return _with_audit_hash({"session_id": resolved_session, "rows": rows, "docs": docs})


@app.get("/audit/latest")
async def audit_latest(session_id: str | None = Query(None)) -> dict[str, Any]:
	"""Return metadata for the most recent explain and appeal audit artifacts."""

	resolved_session = resolve_session(session_id, required=True)
	assert resolved_session is not None
	latest_explain = _latest_audit_entry(resolved_session, "explain")
	latest_appeal = _latest_audit_entry(resolved_session, "appeal")
	return _with_audit_hash(
		{
			"session_id": resolved_session,
			"latest_explain": latest_explain,
			"latest_appeal": latest_appeal,
		}
	)


def _reconcile_session(session_hint: str | None) -> dict[str, object]:
	resolved_session = resolve_session(session_hint, required=True)
	assert resolved_session is not None
	rows, _ = _load_session_claims(resolved_session)

	totals = {
		"billed": 0.0,
		"allowed": 0.0,
		"insurer_paid": 0.0,
		"adjustments": 0.0,
		"patient_resp": 0.0,
	}

	def _sum_adjustments(adjs: list[Any] | None) -> float:
		s = 0.0
		for item in adjs or []:
			try:
				val = float(str(item).replace("$", "").replace(",", ""))
				s += val
			except Exception:
				continue
		return s

	line_map: dict[str, set[str]] = {}
	cpt_map: dict[str, dict[tuple, set[str]]] = {}
	missing_adjustments_per_doc: dict[str, list[dict[str, Any]]] = {}

	for row in rows:
		doc_id = str(row.get("doc_id") or "")
		billed = float(row.get("billed") or 0.0)
		allowed = float(row.get("allowed") or 0.0)
		insurer_paid = float(row.get("insurer_paid") or 0.0)
		patient_resp = float(row.get("patient_resp") or 0.0)
		adjustments = row.get("adjustments") or []
		adjustments_sum = _sum_adjustments(adjustments)

		totals["billed"] += billed
		totals["allowed"] += allowed
		totals["insurer_paid"] += insurer_paid
		totals["adjustments"] += adjustments_sum
		totals["patient_resp"] += patient_resp

		line_id = row.get("line_id")
		if line_id:
			line_map.setdefault(str(line_id), set()).add(doc_id)

		cpt = str(row.get("cpt") or "").strip()
		modifiers = row.get("modifiers") or []
		try:
			mod_key = tuple(sorted([str(m).strip() for m in modifiers if m is not None]))
		except Exception:
			mod_key = tuple()
		if cpt:
			cpt_map.setdefault(cpt, {}).setdefault(mod_key, set()).add(doc_id)

		expected_adj = billed - allowed - insurer_paid - patient_resp
		if (not adjustments or len(adjustments) == 0) and abs(expected_adj) > 0.01:
			missing_adjustments_per_doc.setdefault(doc_id, []).append(
				{
					"line_id": row.get("line_id"),
					"cpt": cpt,
					"expected_adjustments": expected_adj,
					"billed": billed,
					"allowed": allowed,
					"insurer_paid": insurer_paid,
					"patient_resp": patient_resp,
				}
			)

	anomalies: list[dict[str, Any]] = []

	for line_id, docs in line_map.items():
		if len(docs) > 1:
			anomalies.append({"type": "duplicate_line_id", "line_id": line_id, "docs": sorted(list(docs))})

	for cpt, mod_variants in cpt_map.items():
		if len(mod_variants) > 1:
			variants = []
			for mod_key, docs in mod_variants.items():
				variants.append({"modifiers": list(mod_key), "docs": sorted(list(docs))})
			anomalies.append({"type": "cpt_modifier_mismatch", "cpt": cpt, "variants": variants})

	for doc_id, items in missing_adjustments_per_doc.items():
		anomalies.append({"type": "missing_adjustments", "doc_id": doc_id, "rows": items})

	doc_ids = {str(row.get("doc_id")) for row in rows if row.get("doc_id")}
	for doc_id in doc_ids:
		# Cross check if doc exists in extracted
		pass

	return _with_audit_hash({"session_id": resolved_session, "anomalies": anomalies})



@app.get("/reconcile/session/{session_id}")
async def reconcile_session_route(session_id: str) -> dict[str, object]:
	"""Run heuristic reconciliation for the provided session."""
	resolved_session = resolve_session(session_id, required=True)
	return _reconcile_session(resolved_session)


@app.post("/chat")
async def chat_route(payload: ChatRequest) -> dict[str, object]:
    """Answer a question about the current session's documents using RAG."""
    resolved_session = resolve_session(payload.session_id, required=True)
    
    # We pass the doc_id filter if provided
    # The answer_with_citations function uses 'policy_id' also, which we don't really have a UI for yet
    # so we'll pass None for policy_id
    
    try:
        result = answer_with_citations(
            question=payload.question, 
            doc_id=payload.doc_id, 
            policy_id=None,
            session_id=resolved_session
        )
        return _with_audit_hash(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc





@app.post("/session/manual_entry")
async def manual_entry_route(payload: dict[str, Any]) -> dict[str, object]:
	"""Append a manually entered claim line to the existing session.

	Expects: session_id, billed, allowed, date, description, etc.
	"""
	session_raw = payload.get("session_id")
	if session_raw is None:
		raise HTTPException(status_code=400, detail="session_id is required")
	
	resolved_session = resolve_session(str(session_raw), required=True)
	
	# Prepare row
	# We'll generate a dummy line_id if not present
	import uuid
	line_id = payload.get("line_id") or f"MANUAL-{uuid.uuid4().hex[:8].upper()}"
	
	row = {
		"doc_id": "MANUAL_ENTRY", # Virtual doc ID for manual entries
		"line_id": line_id,
		"page": 1,
		"cell_id": "manual",
		"description": str(payload.get("description", "Manual Entry")),
		"cpt": str(payload.get("cpt", "")),
		"billed": float(payload.get("billed") or 0.0),
		"allowed": float(payload.get("allowed") or 0.0),
		"insurer_paid": float(payload.get("insurer_paid") or 0.0),
		"patient_resp": float(payload.get("patient_resp") or 0.0),
		"adjustments": [], # manual usually doesn't capture adjustments detail
		"modifiers": [],
		"date": str(payload.get("date", "")),
	}
	
	try:
		# Use the backend.session helper
		from backend.session import append_claim_rows
		append_claim_rows(resolved_session, [row])
	except Exception as exc:
		raise HTTPException(status_code=500, detail=str(exc))
		
	return _with_audit_hash({"status": "ok", "line_id": line_id, "row": row})


@app.get("/reconcile/session")
async def reconcile_session_query(session_id: str | None = Query(None)) -> dict[str, object]:
	"""Summarize totals using an optional query parameter for the session id."""
	return _reconcile_session(session_id)

@app.post("/session/purge")
async def session_purge(payload: dict[str, str]) -> dict[str, object]:
	"""Purge all stored artifacts for a session under data/user_sessions/<session_id>.

	Expects JSON: {"session_id": "<id>"}.
	This is a destructive operation — callers should confirm intent.
	"""
	session_id = str(payload.get("session_id", "")).strip()
	if not session_id:
		raise HTTPException(status_code=400, detail="session_id is required")

	# basic validation: only allow safe characters
	import re

	if not re.match(r"^[A-Za-z0-9._-]+$", session_id):
		raise HTTPException(status_code=400, detail="invalid session_id")

	target = DATA_ROOT / "user_sessions" / session_id
	if not target.exists():
		raise HTTPException(status_code=404, detail="session not found")

	try:
		shutil.rmtree(target)
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"unable to purge session: {str(exc)}") from exc

	return _with_audit_hash({"status": "purged", "session_id": session_id})


@app.post("/session/manual_entry")
async def session_manual_entry(payload: dict[str, object]) -> dict[str, object]:
	"""Accept manual structured rows for a session and persist them so Explain can operate.

	Expects JSON: {
		"session_id": "<id>",
		"doc_id": "EOB-023" (optional — will be allocated if missing),
		"rows": [ { <claim row dict> }, ... ]
	}

	The endpoint will append rows to data/user_sessions/<session_id>/extracted/claims_struct.json
	and also add a mapping for the doc_id into data/samples/claims_struct.json so the
	existing explain pipeline can load the document by id.
	"""
	session_id = str(payload.get("session_id", "")).strip()
	if not session_id:
		raise HTTPException(status_code=400, detail="session_id is required")

	rows = payload.get("rows") or []
	if not isinstance(rows, list) or len(rows) == 0:
		raise HTTPException(status_code=400, detail="rows must be a non-empty list")

	# safe doc id allocation when not provided
	doc_id = str(payload.get("doc_id", "")).strip()
	if not doc_id:
		try:
			doc_id = _safe_doc_id()
		except Exception:
			doc_id = f"EOB-{secrets.token_hex(2).upper()}"

	# prepare session extracted dir
	extracted_dir = DATA_ROOT / "user_sessions" / session_id / "extracted"
	extracted_dir.mkdir(parents=True, exist_ok=True)

	# redact textual fields to avoid PHI leakage (reuse redact_text)
	sanitized_rows = []
	for r in rows:
		if not isinstance(r, dict):
			continue
		r_copy = dict(r)
		r_copy["doc_id"] = doc_id
		# ensure page and cell fields
		r_copy.setdefault("page", 1)
		if "cell" in r_copy and "cell_id" not in r_copy:
			r_copy["cell_id"] = r_copy.pop("cell")
		r_copy.setdefault("cell_id", "manual:R1C1")
		# redact string fields
		for k, v in list(r_copy.items()):
			if isinstance(v, str) and v.strip():
				try:
					r_copy[k] = redact_text(v)
				except Exception:
					# fallback: leave as-is
					r_copy[k] = v
		sanitized_rows.append(r_copy)

	# Append to per-session claims_struct.json (list form used by dashboard)
	claims_struct_path = extracted_dir / "claims_struct.json"
	existing = []
	if claims_struct_path.exists():
		try:
			existing = json.loads(claims_struct_path.read_text(encoding="utf-8"))
			if not isinstance(existing, list):
				existing = []
		except Exception:
			existing = []
	existing.extend(sanitized_rows)
	try:
		claims_struct_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
	except Exception:
		# non-fatal
		pass

	# Persist a minimal extracted document artifact for the doc_id
	doc_artifact = {
		"doc_id": doc_id,
		"session_id": session_id,
		"filename": "manual-entry",
		"file_type": "manual",
		"pages": 1,
		"notes": ["manual_entry_used"],
		"extracted_text_preview": "Manual entry provided by user",
	}
	try:
		(extracted_dir / f"{doc_id}.json").write_text(json.dumps(doc_artifact, ensure_ascii=False, indent=2), encoding="utf-8")
	except Exception:
		pass

	# Update central samples claims mapping so explain_bill can find the doc by id
	samples_path = DATA_ROOT / "samples" / "claims_struct.json"
	try:
		if samples_path.exists():
			samples = json.loads(samples_path.read_text(encoding="utf-8"))
			if not isinstance(samples, dict):
				samples = {}
		else:
			samples = {}
	except Exception:
		samples = {}

	# convert numeric-like fields and ensure TOTAL row presence if not provided
	# if a TOTAL row is not provided, compute an aggregate TOTAL
	provided_total = any(str((r.get("line_id") or "")).upper() == "TOTAL" for r in sanitized_rows)
	if not provided_total:
		# compute sums
		def _asnum(x):
			try:
				return float(x) if x is not None else 0.0
			except Exception:
				return 0.0

		billed = sum(_asnum(r.get("billed")) for r in sanitized_rows)
		allowed = sum(_asnum(r.get("allowed")) for r in sanitized_rows)
		insurer_paid = sum(_asnum(r.get("insurer_paid")) for r in sanitized_rows)
		patient_resp = sum(_asnum(r.get("patient_resp")) for r in sanitized_rows)
		adjustments_sum = 0.0
		for r in sanitized_rows:
			for adj in (r.get("adjustments") or []):
				# adjustments may be dicts like {"type":..., "amount":...} or raw numbers
				try:
					if isinstance(adj, dict):
						val = adj.get("amount")
					else:
						val = adj
					if val is None:
						continue
					adjustments_sum += float(val)
				except Exception:
					continue

		total_row = {
			"line_id": "TOTAL",
			"page": 1,
			"cell_id": "manual:TOTAL",
			"cpt": "",
			"modifier": "",
			"billed": billed,
			"allowed": allowed,
			"insurer_paid": insurer_paid,
			"adjustments": [{"type": "manual", "amount": adjustments_sum}] if adjustments_sum else [],
			"patient_resp": patient_resp,
		}
		sanitized_rows.append(total_row)

	# write into central samples mapping
	try:
		# convert rows to simple JSON-serializable form
		samples[doc_id] = sanitized_rows
		samples_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
	except Exception:
		# non-fatal
		pass

	return _with_audit_hash({"status": "ok", "session_id": session_id, "doc_id": doc_id, "rows_added": len(sanitized_rows)})


@app.post("/appeal/track")
def track_appeal_endpoint(payload: AppealTrackRequest):
    """Log an appeal outcome."""
    try:
        track_appeal_outcome(payload.session_id, payload.doc_id, payload.status, payload.notes)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/appeal/history")
def get_appeal_history_endpoint(session_id: str = Query(...)):
    """Retrieve appeal history."""
    return list_appeal_history(session_id)

@app.post("/profile/upload_sbc")
async def upload_sbc_endpoint(
    session_id: str = Query(...),
    file: UploadFile = File(...)
):
    """Parse an SBC PDF and update the profile."""
    try:
        # Reuse EOB upload handler to save file safely
        file_path = await handle_upload_file(file, session_id)
        
        extracted = parse_sbc(str(file_path))
        if "error" in extracted:
             raise HTTPException(status_code=400, detail=extracted["error"])
             
        # Load existing profile to merge
        try:
             current = load_profile(session_id)
        except Exception:
             current = {"session_id": session_id}
             
        # Merge logic
        if extracted.get("deductible_individual"):
            current["deductible_individual"] = extracted["deductible_individual"]
            # Also reset remaining if we are setting total
            current["deductible_remaining"] = extracted["deductible_individual"]
            
        if extracted.get("oop_individual"):
            current["oop_max"] = extracted["oop_individual"]
            current["oop_remaining"] = extracted["oop_individual"]
            
        saved = save_profile(current)
        
        return {
            "status": "ok",
            "extracted": extracted,
            "profile": saved
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/appeal_docx")
async def appeal_docx_route(payload: dict[str, Any]):
    """Generate a DOCX appeal letter."""
    doc_id, tone, audience, psl_delta, session_hint = _parse_appeal_payload(payload)
    session_id = _resolve_session_for_docs(session_hint, [doc_id])

    docx_bytes = build_appeal_docx(
        doc_id, tone=tone, audience=audience, psl_delta=psl_delta, session_id=session_id
    )
    filename = f"Appeal_{doc_id}.docx"
    return StreamingResponse(
        BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.post("/appeal/generate_ai")
def generate_appeal_ai_route(req: AppealAIRequest):
    """Generate an AI-drafted appeal letter."""
    s_id = resolve_session(req.session_id)
    if not s_id: 
        raise HTTPException(400, "Invalid session")

    # 1. Gather Claim Data (Simple approach: use explain_bill summary)
    try:
        struct = explain_bill(req.doc_id, session_id=s_id)
        breakdown = struct.get("breakdown", [])
        breakdown_text = "; ".join([f"{x['label']}: {x['value']}" for x in breakdown])
        
        # 2. Gather Policy Context
        policy_text = ""
        s_dir = DATA_ROOT / "user_sessions" / s_id / "extracted"
        if s_dir.exists():
            for f in s_dir.glob("SBC_*.txt"):
                policy_text += f.read_text(encoding="utf-8") + "\n\n"
        
        # 3. Call LLM
        draft = generate_appeal_letter(
            doc_id=req.doc_id,
            deny_code="See Attached EOB", 
            diagnosis="See Attached Records", 
            procedure=breakdown_text,
            user_context=req.user_context,
            policy_context=policy_text
        )
        return {"body": draft, "subject": f"Appeal for {req.doc_id}"}

    except Exception as e:
        raise HTTPException(500, f"Generation failed: {e}")

@app.post("/explain/ai")
def explain_ai_route(req: AIExplainRequest):
    """Generate an AI summary of the bill."""
    s_id = resolve_session(req.session_id)
    if not s_id: 
         raise HTTPException(400, "Invalid session")

    try:
        # Get data
        struct = explain_bill(req.doc_id, session_id=s_id)
        breakdown = struct.get("breakdown", [])
        breakdown_text = "; ".join([f"{x['label']}: {x['value']}" for x in breakdown])
        
        # Call LLM
        summary = summarize_bill(breakdown_text, req.persona, req.grade_level)
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(500, f"AI Explanation failed: {e}")
