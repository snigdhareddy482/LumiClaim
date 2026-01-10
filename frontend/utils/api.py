"""API Client for LumiClaim Backend."""

import os
import requests
import streamlit as st
from typing import Any, Optional, Dict

# Default API Base URL (can be overridden by env var or UI)
DEFAULT_API_BASE = os.getenv("LUMICLAIM_API_BASE", "http://127.0.0.1:8080")

def get_api_base() -> str:
    """Get the current API base URL from session state or default."""
    if "api_base" not in st.session_state:
        st.session_state.api_base = DEFAULT_API_BASE
    return st.session_state.api_base

def get_session_id() -> Optional[str]:
    """Get the current session ID from session state."""
    return st.session_state.get("session_id")

def ensure_session():
    """Ensure a session ID exists, creating one if necessary."""
    # 1. Check State
    if get_session_id():
        return

    # 2. Check Query Params (Persistence)
    qp = st.query_params.get_all("session_id") if hasattr(st.query_params, "get_all") else [st.query_params.get("session_id")]
    # Streamlit 1.30+ uses st.query_params as a dict-like object
    # Older uses st.experimental_get_query_params
    # We will assume modern Streamlit (st.query_params is a dict-like proxy)
    
    # query_params.get returns None or value. 
    qp_val = st.query_params.get("session_id")
    
    if qp_val:
        st.session_state.session_id = qp_val
        st.session_state.session_created = True
        return

    # 3. Create New (Anonymous)
    try:
        url = f"{get_api_base()}/session/start"
        resp = requests.post(url, timeout=30)
        if resp.ok:
            data = resp.json()
            sid = data.get("session_id")
            st.session_state.session_id = sid
            st.session_state.session_created = True
            # Set param for future refreshes
            st.query_params["session_id"] = sid
        else:
            st.error(f"Failed to start session: {resp.text}")
    except Exception as e:
        st.error(f"Could not connect to backend at {get_api_base()}: {e}")

def _attach_session(params: Dict[str, Any]) -> Dict[str, Any]:
    """Attach session_id to request parameters (query or body)."""
    sid = get_session_id()
    if not sid:
        return params
        
    # If param matches "params" (query args), inject session_id
    if "params" in params:
        params["params"]["session_id"] = sid
    # If param matches "json" (body), inject session_id
    elif "json" in params:
         if isinstance(params["json"], dict):
            params["json"]["session_id"] = sid
    # If param matches "data" (form data), inject if dict
    elif "data" in params:
        if isinstance(params["data"], dict):
            params["data"]["session_id"] = sid
            
    # Fallback: if we simply have a dict wrapper, try to inject
    # This covers cases where the caller passes just the payload dict
    # But usually requests.post(..., json=payload) is how it's called.
    return params

def fetch(method: str, endpoint: str, **kwargs) -> Optional[Any]:
    """Make an API request with automatic session handling."""
    url = f"{get_api_base()}{endpoint}"
    
    # Auto-inject session ID for known parameterized keys if not present
    # Case 1: GET request uses 'params'
    if method.upper() == "GET":
        kwargs.setdefault("params", {})
        if get_session_id():
            kwargs["params"].setdefault("session_id", get_session_id())
            
    # Case 2: POST/PUT uses 'json' or 'data'
    if method.upper() in ["POST", "PUT", "PATCH"]:
        if "json" in kwargs and isinstance(kwargs["json"], dict) and get_session_id():
            kwargs["json"].setdefault("session_id", get_session_id())
    
    try:
        response = requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        # Try to return friendly error message from backend
        try:
            err_data = response.json()
            st.error(f"API Error ({response.status_code}): {err_data.get('detail', str(e))}")
        except:
             st.error(f"API Error: {e}")
    except Exception as e:
        st.error(f"Connection Error: {e}")
    
    return None

def get(endpoint: str, **kwargs):
    return fetch("GET", endpoint, **kwargs)

def post(endpoint: str, **kwargs):
    return fetch("POST", endpoint, **kwargs)
