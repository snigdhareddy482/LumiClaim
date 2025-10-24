"""Session lifecycle helpers and filesystem utilities for LumiClaim."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

DATA_ROOT = Path("data")
SESSION_ROOT = DATA_ROOT / "user_sessions"
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_BUILTIN_DOC_IDS = {"EOB-001", "EOB-002"}

_current_session_id: str | None = None


def _claim_row_key(row: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        str(row.get("doc_id", "")),
        str(row.get("line_id", "")),
        row.get("page"),
        row.get("cell_id"),
    )


def _raw_page_key(entry: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        str(entry.get("doc_id", "")),
        entry.get("page"),
        entry.get("text"),
    )


def _ensure_session_root() -> None:
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)


def _write_json(target: Path, payload: Any) -> None:
    try:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"unable to persist session artifact: {exc}") from exc


def _load_sample_claims() -> list[dict[str, Any]]:
    """Return flattened claim rows from the built-in sample corpus."""

    samples_path = DATA_ROOT / "samples" / "claims_struct.json"
    if not samples_path.exists():
        return []

    try:
        payload = json.loads(samples_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for doc_id, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                row = dict(entry)
                row.setdefault("doc_id", doc_id)
                rows.append(row)
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                rows.append(dict(entry))

    return rows


def _seed_session_with_samples(session_id: str) -> None:
    """Populate a fresh session with the bundled sample claim rows."""

    rows = _load_sample_claims()
    if not rows:
        return

    claims_path = session_dir(session_id) / "claims_struct.json"
    if claims_path.exists() and _read_json_list(claims_path):
        return

    _write_json(claims_path, rows)

    extracted_dir = session_dir(session_id) / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    extracted_claims_path = extracted_dir / "claims_struct.json"
    if not extracted_claims_path.exists() or not _read_json_list(extracted_claims_path):
        _write_json(extracted_claims_path, rows)

    doc_ids = {str(entry.get("doc_id")) for entry in rows if entry.get("doc_id")}
    for doc_id in doc_ids:
        if not doc_id:
            continue
        doc_path = extracted_dir / f"{doc_id}.json"
        if doc_path.exists():
            continue
        stub_payload = {
            "doc_id": doc_id,
            "session_id": session_id,
            "filename": f"{doc_id}.pdf",
            "file_type": "sample",
            "pages": 1,
            "notes": ["bootstrap-sample"],
        }
        _write_json(doc_path, stub_payload)


def _read_json_list(path: Path) -> list[Any]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def set_current_session(session_id: str | None) -> None:
    """Remember the active session id for subsequent requests."""

    global _current_session_id
    _current_session_id = session_id


def get_current_session() -> str | None:
    """Return the active session id if one is registered."""

    return _current_session_id


def session_dir(session_id: str) -> Path:
    return SESSION_ROOT / session_id


def ensure_session_dirs(session_id: str) -> tuple[Path, Path, Path]:
    """Ensure base directories exist for the session and return (base, raw, extracted)."""

    base = session_dir(session_id)
    if not base.exists():
        raise HTTPException(status_code=404, detail={"error": "session not found", "session_id": session_id})
    raw = base / "raw"
    extracted = base / "extracted"
    audits = base / "audits"
    for path in (raw, extracted, audits):
        path.mkdir(parents=True, exist_ok=True)
    return base, raw, extracted


def ensure_session_files(session_id: str) -> None:
    base, _, _ = ensure_session_dirs(session_id)
    defaults: dict[str, Any] = {
        "claims_struct.json": [],
        "claims_raw.json": [],
        "profile.json": {},
    }
    for filename, payload in defaults.items():
        target = base / filename
        if not target.exists():
            _write_json(target, payload)


def record_audit_entry(session_id: str, prefix: str, payload: Any) -> None:
    """Persist an audit payload under the session's audits directory."""

    try:
        base, _, _ = ensure_session_dirs(session_id)
    except HTTPException:
        # surface session-specific errors (not found) to the caller
        raise
    except Exception:
        return

    audits_dir = base / "audits"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = audits_dir / f"{prefix}_{timestamp}.json"

    try:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # auditing is best-effort; ignore persistence failures
        pass


def resolve_session(session_id: str | None, *, required: bool = True) -> str | None:
    """Return a usable session id, optionally falling back to the in-memory current session."""

    normalized = str(session_id or "").strip()
    if normalized:
        if not _SAFE_ID_PATTERN.fullmatch(normalized):
            raise HTTPException(status_code=400, detail="invalid session_id")
        _target = session_dir(normalized)
        if not _target.exists():
            available = list_available_sessions()["sessions"]
            raise HTTPException(
                status_code=404,
                detail={"error": "session not found", "session_id": normalized, "available_sessions": [item["session_id"] for item in available]},
            )
        ensure_session_files(normalized)
        set_current_session(normalized)
        return normalized

    fallback = get_current_session()
    if fallback:
        ensure_session_files(fallback)
        return fallback

    if required:
        raise HTTPException(status_code=400, detail="No session. Call /session/start first.")
    return None


def is_builtin_doc(doc_id: str) -> bool:
    return doc_id in _BUILTIN_DOC_IDS


def append_claim_rows(session_id: str, rows: Iterable[dict[str, Any]]) -> None:
    ensure_session_files(session_id)
    path = session_dir(session_id) / "claims_struct.json"
    existing = [row for row in _read_json_list(path) if isinstance(row, dict)]
    order: list[tuple[Any, Any, Any, Any]] = []
    mapping: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
    for row in existing:
        key = _claim_row_key(row)
        order.append(key)
        mapping[key] = row
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _claim_row_key(row)
        mapping[key] = dict(row)
        if key not in order:
            order.append(key)
    _write_json(path, [mapping[key] for key in order])


def append_raw_pages(session_id: str, pages: Iterable[dict[str, Any]]) -> None:
    ensure_session_files(session_id)
    path = session_dir(session_id) / "claims_raw.json"
    existing = [entry for entry in _read_json_list(path) if isinstance(entry, dict)]
    order: list[tuple[Any, Any, Any]] = []
    mapping: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for entry in existing:
        key = _raw_page_key(entry)
        order.append(key)
        mapping[key] = entry
    for entry in pages:
        if not isinstance(entry, dict):
            continue
        key = _raw_page_key(entry)
        mapping[key] = dict(entry)
        if key not in order:
            order.append(key)
    _write_json(path, [mapping[key] for key in order])


def load_claim_rows(session_id: str) -> list[dict[str, Any]]:
    ensure_session_files(session_id)
    return _read_json_list(session_dir(session_id) / "claims_struct.json")


def load_claim_rows_for_doc(session_id: str, doc_id: str) -> list[dict[str, Any]]:
    rows = load_claim_rows(session_id)
    filtered = [row for row in rows if str(row.get("doc_id")) == doc_id]
    if not filtered:
        raise KeyError(f"Unknown document id '{doc_id}' for session {session_id}")
    return filtered


def load_raw_pages(session_id: str) -> list[dict[str, Any]]:
    ensure_session_files(session_id)
    return _read_json_list(session_dir(session_id) / "claims_raw.json")


def _profile_has_content(profile_path: Path) -> bool:
    if not profile_path.exists():
        return False
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(data) if isinstance(data, dict) else False


def _count_documents(session_dir_path: Path) -> int:
    extracted_dir = session_dir_path / "extracted"
    if not extracted_dir.exists():
        return 0
    count = 0
    for candidate in extracted_dir.glob("*.json"):
        if candidate.name == "claims_struct.json":
            continue
        if candidate.is_file():
            count += 1
    return count


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def list_available_sessions() -> dict[str, list[dict[str, Any]]]:
    return list_sessions()


def list_sessions() -> dict[str, list[dict[str, Any]]]:
    """Return metadata about known sessions."""

    if not SESSION_ROOT.exists():
        return {"sessions": []}

    current = get_current_session()
    sessions: list[dict[str, Any]] = []
    for session_dir_path in SESSION_ROOT.iterdir():
        if not session_dir_path.is_dir():
            continue
        try:
            created_at = _format_timestamp(session_dir_path.stat().st_mtime)
        except Exception:
            created_at = _format_timestamp(datetime.now(tz=timezone.utc).timestamp())
        sessions.append(
            {
                "session_id": session_dir_path.name,
                "created_at": created_at,
                "doc_count": _count_documents(session_dir_path),
                "has_profile": _profile_has_content(session_dir_path / "profile.json"),
                "is_current": session_dir_path.name == current,
            }
        )

    sessions.sort(key=lambda item: item["created_at"], reverse=True)
    return {"sessions": sessions}


def start_session() -> dict[str, str]:
    """Create a new session directory tree with bootstrap artifacts and register it as current."""

    _ensure_session_root()
    for _ in range(8):
        session_id = str(uuid.uuid4())
        base = session_dir(session_id)
        try:
            base.mkdir(mode=0o755, exist_ok=False)
        except FileExistsError:
            continue
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"unable to create session directory: {exc}") from exc

        try:
            ensure_session_files(session_id)
        except Exception:
            shutil.rmtree(base, ignore_errors=True)
            raise

        try:
            _seed_session_with_samples(session_id)
        except Exception:
            shutil.rmtree(base, ignore_errors=True)
            raise

        set_current_session(session_id)
        return {"session_id": session_id}

    raise HTTPException(status_code=500, detail="unable to allocate unique session id")


def delete_session(session_id: str) -> dict[str, Any]:
    """Delete all artifacts for the specified session."""

    session_id = str(session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if not _SAFE_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="invalid session_id")

    target = session_dir(session_id)
    if not target.exists():
        available = [item["session_id"] for item in list_sessions()["sessions"]]
        raise HTTPException(
            status_code=404,
            detail={"error": "session not found", "available_sessions": available},
        )

    try:
        shutil.rmtree(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"unable to delete session: {exc}") from exc

    if get_current_session() == session_id:
        set_current_session(None)

    return {"status": "deleted", "session_id": session_id}
