# Fix Python path for Streamlit Cloud
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from utils import ui, api
import time

# Check if we are the main script run
if __name__ == "__main__":
    st.set_page_config(
        page_title="LumiClaim Login",
        page_icon="🏥",
        layout="centered", # Centered layout for login
        initial_sidebar_state="collapsed"
    )
    
    ui.inject_css()
    
    # Auto-redirect if already logged in (optional, but good UX)
    # if api.get_session_id():
    #     st.switch_page("pages/1_Upload_&_Dashboard.py")

    st.markdown("<br><br>", unsafe_allow_html=True) # Spacer
    
    with ui.card_container():
        c1, c2 = st.columns([1, 2])
        with c1:
             st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=120)
        with c2:
            st.title("LumiClaim")
            st.caption("Proof-first Medical Billing Copilot")
        
        st.divider()
        
        st.markdown("### 🏥 Patient Portal Login")
        
        # Auth State Management
        if "auth_stage" not in st.session_state:
            st.session_state["auth_stage"] = "identify"
            
        # --- Stage 1: Identification ---
        if st.session_state["auth_stage"] == "identify":
            st.info("Enter your Name or Patient ID to access your dashboard.")
            username = st.text_input("Patient Name / ID", key="login_username_input", 
                                   on_change=lambda: st.session_state.update({"auth_stage": "identify"}))
            
            if st.button("Continue", type="primary", use_container_width=True):
                if username.strip():
                    clean_id = username.strip()
                    # Check status
                    try:
                        res = api.get(f"/auth/status/{clean_id}")
                        status = res.get("status", "unknown")
                        st.session_state["auth_status"] = status
                        st.session_state["target_user"] = clean_id
                        st.session_state["auth_stage"] = "authenticate"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Connection failed: {e}")
                else:
                    st.warning("Please enter a name.")

        # --- Stage 2: Authentication ---
        elif st.session_state["auth_stage"] == "authenticate":
            target = st.session_state["target_user"]
            status = st.session_state["auth_status"]
            
            # Back button
            if st.button("← Back"):
                st.session_state["auth_stage"] = "identify"
                st.rerun()
            
            st.markdown(f"**User**: `{target}`")
            
            if status == "active":
                st.success("Account found. Please log in.")
                password = st.text_input("Password", type="password", key="login_pw")
                
                if st.button("🔐 Log In", type="primary", use_container_width=True):
                    res = api.post("/auth/login", json={"username": target, "password": password})
                    if res and res.get("success"):
                        # Login Success -> Start Session
                        api.post("/session/start", json={"session_id": target})
                        st.session_state["session_id"] = target
                        
                        # Load Profile Name
                        current_profile = st.session_state.get("profile_data", {})
                        current_profile["patient_name"] = target
                        st.session_state["profile_data"] = current_profile
                        
                        st.success("Login successful!")
                        time.sleep(0.5)
                        st.switch_page("pages/1_Upload_&_Dashboard.py")
                    else:
                        st.error("Incorrect password.")
                        
            elif status == "migrate_required":
                st.warning("⚠️ **Security Update**: Please protect your profile with a password.")
                password = st.text_input("Set New Password", type="password", key="reg_pw")
                confirm = st.text_input("Confirm Password", type="password", key="reg_pw_conf")
                
                if st.button("🛡️ Secure Account", type="primary", use_container_width=True):
                    if password and password == confirm:
                        res = api.post("/auth/register", json={"username": target, "password": password})
                        if res and res.get("success"):
                            # Registered -> Start Session
                            api.post("/session/start", json={"session_id": target})
                            st.session_state["session_id"] = target
                            
                            st.success("Account secured! Logging in...")
                            time.sleep(0.5)
                            st.switch_page("pages/1_Upload_&_Dashboard.py")
                        else:
                            st.error("Registration failed. Try again.")
                    else:
                        st.error("Passwords do not match.")
                        
            else: # unknown -> New User
                st.info("New profile detected. Create a password to get started.")
                password = st.text_input("Create Password", type="password", key="new_pw")
                
                if st.button("🚀 Create Profile", type="primary", use_container_width=True):
                    if password:
                        res = api.post("/auth/register", json={"username": target, "password": password})
                        if res and res.get("success"):
                            # Registered -> Start Session
                            api.post("/session/start", json={"session_id": target})
                            st.session_state["session_id"] = target
                            
                            st.success("Welcome to LumiClaim!")
                            time.sleep(0.5)
                            st.switch_page("pages/1_Upload_&_Dashboard.py")
                        else:
                            st.error("Could not register.")
                    else:
                        st.error("Password is required.")
                
    st.markdown("<div style='text-align: center; color: #6b7280; font-size: 0.8rem; margin-top: 2rem;'>© 2025 LumiClaim Health. Secure & Private.</div>", unsafe_allow_html=True)
