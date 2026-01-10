
import hashlib
import json
import secrets
from pathlib import Path
from typing import Dict, Any, Optional

# Path to the auth database
AUTH_DB_PATH = Path(__file__).resolve().parent.parent / "data/auth.json"

def _load_db() -> Dict[str, Any]:
    if not AUTH_DB_PATH.exists():
        return {}
    try:
        return json.loads(AUTH_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_db(db: Dict[str, Any]) -> None:
    # ensure parent dir exists
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")

def _hash_password(password: str, salt: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        'sha256', 
        password.encode('utf-8'), 
        salt.encode('utf-8'), 
        100000
    ).hex()

def user_exists(username: str) -> bool:
    db = _load_db()
    return username.lower().strip() in db

def has_password(username: str) -> bool:
    """Check if a registered user has a password set."""
    db = _load_db()
    user = db.get(username.lower().strip())
    if not user:
        return False
    return bool(user.get("password_hash"))

def register_user(username: str, password: str) -> bool:
    """Register a new user or set password for existing user without one."""
    username = username.lower().strip()
    db = _load_db()
    
    # Generate Salt
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    
    payload = {
        "password_hash": pw_hash,
        "salt": salt,
        "created_at": db.get(username, {}).get("created_at")  # preserve or None
    }
    
    # Update DB
    db[username] = payload
    _save_db(db)
    return True

def verify_credentials(username: str, password: str) -> bool:
    db = _load_db()
    user = db.get(username.lower().strip())
    if not user:
        return False
        
    stored_hash = user.get("password_hash")
    salt = user.get("salt")
    
    if not stored_hash or not salt:
        return False
        
    check_hash = _hash_password(password, salt)
    return secrets.compare_digest(stored_hash, check_hash)

def get_user_status(username: str) -> str:
    """Return status: 'unknown', 'migrate_required', 'active'."""
    db = _load_db()
    username = username.lower().strip()
    
    if username not in db:
        # Check if session folder exists (Existing user but not in auth DB yet)
        # This is for "Legacy Users" like Founder who exist on disk but not in auth.json
        from backend.session import session_dir
        if session_dir(username).exists():
             return "migrate_required"
        return "unknown"
        
    user = db.get(username)
    if not user.get("password_hash"):
        return "migrate_required"
        
    return "active"
