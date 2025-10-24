"""Profile storage and validation for per-session insurance plan settings.

Profiles are persisted under data/user_sessions/<session_id>/profile.json
and contain user-provided values for deductible, coinsurance, OOP, copays, etc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DATA_ROOT = Path("data")


def _profile_path(session_id: str) -> Path:
    return DATA_ROOT / "user_sessions" / session_id / "profile.json"


def save_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(profile.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required in profile")

    # Normalize and validate numeric fields
    def _to_float(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            raise ValueError("numeric profile fields must be numeric")

    deductible_individual = _to_float(profile.get("deductible_individual"))
    deductible_remaining = _to_float(profile.get("deductible_remaining"))
    coinsurance = _to_float(profile.get("coinsurance"))
    oop_max = _to_float(profile.get("oop_max"))
    oop_remaining = _to_float(profile.get("oop_remaining"))

    # Copays
    copays = profile.get("copays") or {}
    if not isinstance(copays, dict):
        raise ValueError("copays must be an object with primary/specialist/er values")
    def _copay_val(key: str):
        v = copays.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"copays.{key} must be numeric")

    copays_clean = {
        "primary": _copay_val("primary"),
        "specialist": _copay_val("specialist"),
        "er": _copay_val("er"),
    }

    # Basic range validation
    if coinsurance is not None and not (0.0 <= coinsurance <= 1.0):
        raise ValueError("coinsurance must be between 0.0 and 1.0")
    for name, val in (
        ("deductible_individual", deductible_individual),
        ("deductible_remaining", deductible_remaining),
        ("oop_max", oop_max),
        ("oop_remaining", oop_remaining),
    ):
        if val is not None and val < 0:
            raise ValueError(f"{name} must be non-negative")

    # Inference: if deductible_remaining missing but deductible_individual present -> set remaining to individual
    if deductible_remaining is None and deductible_individual is not None:
        deductible_remaining = deductible_individual

    # Inference: if oop_remaining missing but oop_max present -> set remaining to oop_max
    if oop_remaining is None and oop_max is not None:
        oop_remaining = oop_max

    # sensible default for coinsurance
    if coinsurance is None:
        coinsurance = 0.2

    safe_profile: Dict[str, Any] = {
        "session_id": session_id,
        "plan_year_start": profile.get("plan_year_start"),
        "plan_name": profile.get("plan_name"),
        "deductible_individual": deductible_individual,
        "deductible_remaining": deductible_remaining,
        "coinsurance": coinsurance,
        "oop_max": oop_max,
        "oop_remaining": oop_remaining,
        "copays": copays_clean,
    }

    path = _profile_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(safe_profile, fh, indent=2, ensure_ascii=False)

    return safe_profile


def load_profile(session_id: str) -> Dict[str, Any]:
    path = _profile_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"profile not found for session {session_id}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
