"""Serverless API Layer - Direct backend imports (no HTTP)."""

import os
import sys
import json
import streamlit as st
from typing import Any, Optional, Dict, List
from pathlib import Path

# Ensure backend is importable
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

# --- Direct Backend Imports ---
from backend import auth
from backend.session import start_session, session_dir, load_profile, save_profile

def get_session_id() -> Optional[str]:
    """Get the current session ID from session state."""
    return st.session_state.get("session_id")

def ensure_session():
    """Ensure a session ID exists."""
    if get_session_id():
        return
    
    # Check query params
    qp_val = st.query_params.get("session_id")
    if qp_val:
        st.session_state.session_id = qp_val
        st.session_state.session_created = True
        return

def _upload_sbc(files: Dict, sid: str) -> Dict[str, Any]:
    """Handle SBC Upload - Mock/Heuristic implementation."""
    # In a real app, we would use Gemini to parse the PDF.
    # For this demo, we verify a file was sent and return a success mock.
    if not files or "file" not in files:
        return {}
    
    # Return mock extracted data to demonstrate the UI flow
    return {
        "profile": {}, 
        "extracted": {
            "deductible_individual": 2500.00,
            "oop_individual": 7500.00
        }
    }

# --- Auth Functions (Direct Calls) ---
def get_auth_status(username: str) -> Dict[str, Any]:
    """Check user status - replaces GET /auth/status/{username}"""
    status = auth.get_user_status(username)
    return {"status": status}

def login(username: str, password: str) -> Dict[str, Any]:
    """Verify credentials - replaces POST /auth/login"""
    success = auth.verify_credentials(username, password)
    return {"success": success}

def register(username: str, password: str) -> Dict[str, Any]:
    """Register user - replaces POST /auth/register"""
    success = auth.register_user(username, password)
    return {"success": success}

def start_user_session(session_id: str) -> Dict[str, Any]:
    """Start session - replaces POST /session/start"""
    result = start_session(session_id)
    return {"session_id": result}

# --- Document Functions ---
def list_documents(sid: str) -> List[str]:
    """List documents in session."""
    if not sid:
        return []
    extracted_dir = session_dir(sid) / "extracted"
    if not extracted_dir.exists():
        return []
    return [f.stem for f in extracted_dir.glob("*.json")]

def get_session_claims(sid: str) -> Dict[str, Any]:
    """Get all claims from session - replaces GET /session/claims"""
    docs = list_documents(sid)
    all_rows = []
    doc_objs = []
    
    for doc_id in docs:
        doc_path = session_dir(sid) / "extracted" / f"{doc_id}.json"
        if doc_path.exists():
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                continue
            doc_objs.append({"doc_id": doc_id})
            claims = doc.get("claims", [])
            for claim in claims:
                claim["doc_id"] = doc_id
                all_rows.append(claim)
    
    return {"rows": all_rows, "docs": doc_objs}

def upload_eob(file_bytes: bytes, filename: str, mimetype: str, sid: str) -> Dict[str, Any]:
    """Handle EOB upload - replaces POST /upload_eob"""
    from backend.upload_eob import handle_upload_file
    from io import BytesIO
    
    # Create file-like object
    file_obj = type('UploadFile', (), {
        'filename': filename,
        'content_type': mimetype,
        'file': BytesIO(file_bytes),
        'read': lambda self: file_bytes
    })()
    
    try:
        result = handle_upload_file(file_obj, sid)
        return result
    except Exception as e:
        return {"error": str(e)}

def get_explanation(doc_id: str, sid: str, persona: str = "patient", level: str = "grade6") -> Dict[str, Any]:
    """Get document explanation - replaces GET /explain/{doc_id}"""
    from backend.explain import get_breakdown
    
    doc_path = session_dir(sid) / "extracted" / f"{doc_id}.json"
    if not doc_path.exists():
        return {"error": "Document not found"}
    
    doc = json.loads(doc_path.read_text())
    
    try:
        result = get_breakdown(doc, persona, level)
        return result
    except Exception as e:
        # Fallback
        return {
            "doc_id": doc_id,
            "takeaway": doc.get("summary", "No summary available"),
            "claims": doc.get("claims", []),
            "verifiability_score": 1.0
        }

def get_evidence_graph(doc_id: str, sid: str) -> Dict[str, Any]:
    """Get evidence graph - replaces GET /egraph/{doc_id}"""
    # This is a visualization helper, return minimal structure
    return {"nodes": [], "edges": []}

# --- Legacy API compatibility (for pages that still use api.get/api.post) ---
def get(endpoint: str, **kwargs) -> Optional[Any]:
    """Compatibility layer - routes to direct functions."""
    params = kwargs.get("params", {})
    sid = params.get("session_id") or get_session_id()
    
    # Parse endpoint
    if endpoint.startswith("/auth/status/"):
        username = endpoint.split("/")[-1]
        return get_auth_status(username)
    elif "/session/claims" in endpoint:
        return get_session_claims(sid)
    elif endpoint.startswith("/explain/"):
        doc_id = endpoint.split("/")[-1]
        return get_explanation(doc_id, sid, params.get("persona", "patient"))
    elif endpoint.startswith("/egraph/"):
        doc_id = endpoint.split("/")[-1]
        return get_evidence_graph(doc_id, sid)
    elif "/profile" in endpoint:
        return {"profile": load_profile(sid) or {}}
    elif "/documents/" in endpoint:
        return list_documents(sid)
    elif "/reconcile/" in endpoint:
        return {"anomalies": []}  # Placeholder
    elif "/appeal/history" in endpoint:
        return [] # Placeholder history
    else:
        # Unknown endpoint - try to return empty
        return {}

def post(endpoint: str, **kwargs) -> Optional[Any]:
    """Compatibility layer - routes to direct functions."""
    json_data = kwargs.get("json", {})
    files = kwargs.get("files", {})
    sid = json_data.get("session_id") or get_session_id()
    
    if endpoint == "/auth/login":
        return login(json_data.get("username", ""), json_data.get("password", ""))
    elif endpoint == "/auth/register":
        return register(json_data.get("username", ""), json_data.get("password", ""))
    elif endpoint == "/session/start":
        return start_user_session(json_data.get("session_id", ""))
    elif endpoint == "/upload_eob":
        # Handle file upload
        if files and "file" in files:
            fname, fbytes, ftype = files["file"]
            return upload_eob(fbytes, fname, ftype, sid)
        return {"error": "No file provided"}
    elif endpoint == "/profile":
        return _set_profile(json_data)
    elif endpoint == "/profile/upload_sbc":
        return _upload_sbc(files, sid)
    elif "/explain/ai" in endpoint:
        return _explain_ai(json_data)
    elif "/appeal/generate_ai" in endpoint:
        return _generate_appeal_ai(json_data)
    elif "/appeal/track" in endpoint:
        # Placeholder for tracking
        return {"success": True}
    elif endpoint == "/appeal":
        # Placeholder for template
        return {"body": "Dear [Insurer], I am writing to appeal...", "subject": "Appeal Letter"}
    elif "/session/manual_entry" in endpoint:
        return _manual_entry(json_data)
    elif "/simulate" in endpoint:
        return _simulate(json_data)
    else:
        return {}

# --- Helper functions ---
def _set_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    session_id = data.pop("session_id", get_session_id())
    save_profile(session_id, data)
    return {"success": True}

def _explain_ai(data: Dict[str, Any]) -> Dict[str, Any]:
    """AI explanation - replaces POST /explain/ai"""
    try:
        from backend.llm import summarize_bill
    except ImportError:
        return {"summary": "AI module not available"}
    
    sid = data.get("session_id", get_session_id())
    doc_id = data.get("doc_id", "")
    persona = data.get("persona", "patient")
    grade = data.get("grade_level", "8th Grade")
    
    doc_path = session_dir(sid) / "extracted" / f"{doc_id}.json"
    if not doc_path.exists():
        return {"summary": "Document not found."}
    
    doc = json.loads(doc_path.read_text())
    breakdown = doc.get("breakdown_text", str(doc.get("claims", [])))
    
    try:
        summary = summarize_bill(breakdown, persona, grade)
        return {"summary": summary}
    except Exception as e:
        return {"summary": f"AI unavailable: {e}"}

def _generate_appeal_ai(data: Dict[str, Any]) -> Dict[str, Any]:
    """AI appeal - replaces POST /appeal/generate_ai"""
    try:
        from backend.llm import generate_appeal_letter
    except ImportError:
        return {"letter": "AI module not available"}
    
    sid = data.get("session_id", get_session_id())
    doc_id = data.get("doc_id", "")
    user_context = data.get("user_context", "")
    
    doc_path = session_dir(sid) / "extracted" / f"{doc_id}.json"
    if not doc_path.exists():
        return {"letter": "Document not found."}
    
    doc = json.loads(doc_path.read_text())
    profile = load_profile(sid) or {}
    
    try:
        letter = generate_appeal_letter(doc, profile, user_context)
        return {"body": letter, "subject": f"Appeal for Claim {doc_id}", "doc_id": doc_id}
    except Exception as e:
        return {"letter": f"AI unavailable: {e}"}

def _manual_entry(data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle manual entry - replaces POST /session/manual_entry"""
    sid = data.get("session_id", get_session_id())
    if not sid:
        return {"error": "No session"}
    
    # Create manual entry document
    manual_dir = session_dir(sid) / "extracted"
    manual_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate ID
    existing = list(manual_dir.glob("MANUAL-*.json"))
    next_id = len(existing) + 1
    doc_id = f"MANUAL-{next_id:03d}"
    
    doc = {
        "doc_id": doc_id,
        "claims": [{
            "description": data.get("description", ""),
            "date": data.get("date", ""),
            "cpt": data.get("cpt", ""),
            "billed": data.get("billed", 0),
            "allowed": data.get("allowed", 0),
            "insurer_paid": data.get("insurer_paid", 0),
            "patient_resp": data.get("patient_resp", 0)
        }]
    }
    
    doc_path = manual_dir / f"{doc_id}.json"
    doc_path.write_text(json.dumps(doc, indent=2))
    
    return {"success": True, "doc_id": doc_id}

def _simulate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Cost simulation - replaces POST /simulate"""
    # Simplified simulation
    sid = data.get("session_id", get_session_id())
    doc_id = data.get("doc_id", "")
    
    profile = load_profile(sid) or {}
    deductible_rem = float(profile.get("deductible_remaining", 500))
    coinsurance = float(profile.get("coinsurance", 0.2))
    
    doc_path = session_dir(sid) / "extracted" / f"{doc_id}.json"
    if not doc_path.exists():
        return {"error": "Document not found"}
    
    doc = json.loads(doc_path.read_text())
    claims = doc.get("claims", [])
    
    total_allowed = sum(float(c.get("allowed", 0)) for c in claims)
    
    # Simple calculation
    ded_applied = min(deductible_rem, total_allowed)
    after_ded = total_allowed - ded_applied
    coins_amount = after_ded * coinsurance
    expected = ded_applied + coins_amount
    
    return {
        "doc_id": doc_id,
        "expected_patient_resp": round(expected, 2),
        "deductible_applied": round(ded_applied, 2),
        "coinsurance_amount": round(coins_amount, 2)
    }
