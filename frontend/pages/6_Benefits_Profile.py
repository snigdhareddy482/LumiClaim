import streamlit as st
import plotly.graph_objects as go
import requests
from utils import api, ui

st.set_page_config(
    page_title="Benefits Profile | LumiClaim",
    page_icon="🛡️",
    layout="wide"
)

ui.inject_css()
api.ensure_session()

ui.render_sidebar()

ui.patient_header(last_visit="Benefits Manager")

st.markdown("### 🛡️ Insurance Plan Profile")
st.markdown("Configure plan details to autofill simulations with accurate coverage info.")

# --- Logic ---
# Defaults from session or empty
current_profile = st.session_state.get("profile_data", {})

with ui.card_container():
    st.markdown("#### Plan Details")
    
    # --- Auto-Fill Section (NEW) ---
    with st.expander("✨ Auto-Fill from Document", expanded=False):
        st.write("Upload your 'Summary of Benefits and Coverage' (SBC) PDF to automatically fill these details.")
        sbc_file = st.file_uploader("Upload SBC PDF", type=["pdf"], key="sbc_uploader")
        
        if sbc_file is not None:
            if st.button("Analyze & Fill Form", type="primary"):
                with st.spinner("Analyzing document..."):
                    import requests
                    try:
                        files = {"file": (sbc_file.name, sbc_file, "application/pdf")}
                        url = f"{api.get_api_base()}/sbc/parse"
                        # Send session_id so backend can save text for RAG
                        resp = requests.post(url, files=files, data={"session_id": api.get_session_id()}, timeout=30)
                        
                        if resp.ok:
                            data = resp.json()
                            if data.get("deductible_individual"):
                                st.session_state["deductible_individual"] = float(data["deductible_individual"])
                            if data.get("deductible_family"):
                                st.session_state["deductible_family"] = float(data["deductible_family"])
                            if data.get("oop_individual"):
                                st.session_state["oop_individual"] = float(data["oop_individual"])
                            if data.get("oop_family"):
                                st.session_state["oop_family"] = float(data["oop_family"])
                                
                            st.success("Form updated! Please review the values below.")
                            st.rerun()
                        else:
                            st.error(f"Analysis failed: {resp.text}")
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    st.divider()

    col_load, col_save = st.columns([1, 1])
    
    with col_load:
        if st.button("Load Profile from Session", use_container_width=True):
             sid = api.get_session_id()
             if sid:
                p, err = api.get("/profile/get", params={"session_id": sid}), None
                if p and p.get("profile"):
                    st.session_state["profile_data"] = p["profile"]
                    st.success("Loaded!")
                    st.rerun()
                else:
                    st.error("No profile found.")
    
    # Auto-fill from SBC
    st.markdown("##### 📄 Auto-fill from SBC")
    with st.expander("Upload Summary of Benefits (SBC) PDF"):
        st.info("Upload your plan's 'Summary of Benefits and Coverage' PDF to auto-extract deductible and OOP limits.")
        sbc_file = st.file_uploader("Choose SBC PDF", type=["pdf"])
        if sbc_file:
            if st.button("Extract & Auto-fill"):
                with st.spinner("Analyzing SBC Key Facts..."):
                    try:
                        files = {"file": sbc_file.getvalue()}
                        params = {"session_id": api.get_session_id()}
                        # Use direct requests for file upload
                        url = f"{api.get_api_base()}/profile/upload_sbc"
                        resp = requests.post(url, files=files, params=params)
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            st.session_state["profile_data"] = data.get("profile")
                            extracted = data.get("extracted", {})
                            msg = "Found: "
                            if extracted.get("deductible_individual"):
                                msg += f"Deductible ${extracted['deductible_individual']:.0f} "
                            if extracted.get("oop_individual"):
                                msg += f"OOP Max ${extracted['oop_individual']:.0f}"
                            st.success(f"Success! {msg}")
                            st.rerun()
                        else:
                            st.error(f"Extraction failed: {resp.text}")
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    # Payer Presets "Quick Fill"
    st.markdown("##### ⚡ Quick Fill (Major Payers)")
    PAYER_PRESETS = {
        "Aetna (HMO)": {"plan_name": "Aetna HMO", "deductible_individual": 2000.0, "coinsurance": 0.2, "oop_max": 5000.0, "copays": {"primary": 25, "specialist": 50, "er": 300}},
        "UHC (PPO)": {"plan_name": "UnitedHealthcare PPO", "deductible_individual": 1500.0, "coinsurance": 0.2, "oop_max": 6500.0, "copays": {"primary": 30, "specialist": 60, "er": 500}},
        "BCBS (HDHP)": {"plan_name": "BlueCross BlueShield HDHP", "deductible_individual": 4000.0, "coinsurance": 0.0, "oop_max": 7500.0, "copays": {"primary": 0, "specialist": 0, "er": 0}},
    }
    
    preset_cols = st.columns(len(PAYER_PRESETS))
    for i, (name, data) in enumerate(PAYER_PRESETS.items()):
        if preset_cols[i].button(name, use_container_width=True):
            st.session_state["profile_data"] = {
                "plan_name": data["plan_name"],
                "deductible_individual": data["deductible_individual"],
                "deductible_remaining": data["deductible_individual"], # Default to full remaining
                "coinsurance": data["coinsurance"],
                "oop_max": data["oop_max"],
                "oop_remaining": data["oop_max"], # Default to full remaining
                "copays": data["copays"]
            }
            st.rerun()
    
    st.divider()
    
    # Form
    n_col, c1, c2 = st.columns(3)

    with n_col:
        patient_name = st.text_input("Patient Name", value=current_profile.get("patient_name", ""))
    
    with c1:
        plan_name = st.text_input("Plan Name", value=current_profile.get("plan_name", ""))
        ded_ind = st.number_input("Individual Deductible", value=float(current_profile.get("deductible_individual", 2000.0)), step=100.0)
        ded_rem = st.number_input("Deductible Remaining", value=float(current_profile.get("deductible_remaining", 2000.0)), step=100.0)
        
    with c2:
        coins = st.slider("Coinsurance (You Pay)", 0.0, 1.0, float(current_profile.get("coinsurance", 0.2)))
        oop_max = st.number_input("OOP Max", value=float(current_profile.get("oop_max", 5000.0)), step=100.0)
        oop_rem = st.number_input("OOP Remaining", value=float(current_profile.get("oop_remaining", 5000.0)), step=100.0)

    st.markdown("#### Copays")
    cc1, cc2, cc3 = st.columns(3)
    copays = current_profile.get("copays", {})
    
    with cc1:
        cp_prim = st.number_input("Primary Care", value=float(copays.get("primary", 25.0)))
    with cc2:
        cp_spec = st.number_input("Specialist", value=float(copays.get("specialist", 50.0)))
    with cc3:
        cp_er = st.number_input("ER", value=float(copays.get("er", 250.0)))
        
    if st.button("Save Profile", type="primary", use_container_width=True):
        payload = {
            "session_id": api.get_session_id(),
            "patient_name": patient_name,
            "plan_name": plan_name,
            "deductible_individual": ded_ind,
            "deductible_remaining": ded_rem,
            "coinsurance": coins,
            "oop_max": oop_max,
            "oop_remaining": oop_rem,
            "copays": {"primary": cp_prim, "specialist": cp_spec, "er": cp_er}
        }
        res = api.post("/profile/set", json=payload)
        if res:
            st.session_state["profile_data"] = res.get("profile")
            st.success("Profile saved successfully!")

# --- Visualization ---
if oop_max > 0:
    prog = max(0.0, min(1.0, (oop_max - oop_rem) / oop_max))
    
    c_viz, c_stat = st.columns([1, 2])
    
    with c_viz:
        with ui.card_container():
            fig = go.Figure(go.Pie(
                values=[prog, 1-prog],
                hole=0.7,
                marker_colors=["#0ea5e9", "#f1f5f9"],
                textinfo="none",
                hoverinfo="none"
            ))
            fig.update_layout(
                showlegend=False,
                margin=dict(t=0,b=0,l=0,r=0),
                height=200,
                annotations=[{
                    "text": f"{int(prog*100)}%", 
                    "font": {"size": 24, "weight": "bold"}, 
                    "showarrow": False
                }]
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("OOP Progress")

    with c_stat:
        with ui.card_container():
            st.metric("Out-of-pocket Met", f"${(oop_max - oop_rem):,.2f}")
            st.progress(prog)
            st.caption(f"Remaining to max: ${oop_rem:,.2f}")

