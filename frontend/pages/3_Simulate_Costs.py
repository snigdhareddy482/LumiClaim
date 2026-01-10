import streamlit as st
import pandas as pd
import altair as alt
from utils import api, ui

# Page Config
st.set_page_config(
    page_title="Simulate Costs | LumiClaim",
    page_icon="🎚️",
    layout="wide"
)

ui.inject_css()
api.ensure_session()

ui.render_sidebar()

ui.patient_header(last_visit="Simulation Mode")

st.markdown("### 🎚️ Policy Simulation")
st.markdown("Estimate what you *should* owe based on your specific insurance plan status.")

# --- Layout ---
col_config, col_results = st.columns([1, 1.5], gap="large")

with col_config:
    with ui.card_container():
        st.markdown("#### Configuration")
        
        # Document Selection
        default_doc = st.session_state.get("current_doc_id", "EOB-001")
        doc_id = st.text_input("Document ID", value=default_doc, key="sim_doc_id")
        
        st.divider()
        
        # Profile Toggle
        use_profile = st.toggle("Use active plan profile", value=False)
        profile_data = None
        
        if use_profile:
            sess_id = api.get_session_id()
            if sess_id:
                prof_resp = api.get("/profile/get", params={"session_id": sess_id})
                profile_data = prof_resp.get("profile") if prof_resp else None
                if profile_data:
                    st.success(f"Loaded profile: **{profile_data.get('plan_name', 'Unnamed Plan')}**")
                else:
                    st.warning("No profile found for this session.")
        
        # Inputs (Use profile defaults if available)
        def get_default(key, fallback):
            if use_profile and profile_data:
                val = profile_data.get(key)
                return float(val) if val is not None else fallback
            return fallback

        ded_rem = st.number_input(
            "Deductible Remaining ($)", 
            min_value=0.0, 
            value=get_default("deductible_remaining", 500.0),
            step=50.0
        )
        
        coins = st.slider(
            "Coinsurance (You pay %)", 
            0.0, 1.0, 
            get_default("coinsurance", 0.2), 
            0.05
        )
        
        oop_rem = st.number_input(
            "OOP Max Remaining ($)", 
            min_value=0.0, 
            value=get_default("oop_remaining", 2000.0), 
            step=50.0
        )
        
        if st.button("Simulate Fair Bill", type="primary", use_container_width=True):
             with st.spinner("Applying policy rules..."):
                payload = {
                    "doc_id": doc_id,
                    "deductible_remaining": ded_rem,
                    "coinsurance": coins,
                    "oop_remaining": oop_rem,
                    "session_id": api.get_session_id()
                }
                # If using profile, backend can infer, but explicit is safer for 'what-if'
                sim_res = api.post("/simulate", json=payload)
                st.session_state["sim_result"] = sim_res

with col_results:
    res = st.session_state.get("sim_result")
    
    if res:
        with ui.card_container():
            st.markdown("#### Simulation Results")
            
            # Extract metrics
            fair_bill = float(res.get("expected_patient_resp", 0.0)) # User calls this "Fair Bill" (what they should pay)
            allowed_total = float(res.get("allowed_total", 0.0))
            
            # 1. Big Numbers
            m1, m2 = st.columns(2)
            with m1:
                st.metric("Total Allowed Amount", f"${allowed_total:,.2f}")
            with m2:
                # Highlight the Fair Bill (My Responsibility)
                st.markdown("**Fair Bill (You Pay)**")
                st.markdown(f"<h2 style='color:#16a34a; margin:0'>${fair_bill:,.2f}</h2>", unsafe_allow_html=True)
            
            st.divider()
            
            # 2. Logic Walkthrough
            st.markdown("#### Calculation Logic")
            
            steps = []
            details = res.get("details", {})
            if details:
                # If detail breakdown exists
                steps.append({"Step": "Allowed Amount", "Value": details.get("allowed_amount", fair_bill)})
                steps.append({"Step": "Applied to Deductible", "Value": details.get("applied_deductible", 0)})
                steps.append({"Step": "Coinsurance Paid", "Value": details.get("coinsurance_paid", 0)})
            else:
                 # Simple chart data if no detailed breakdown
                 pass
            
            if steps:
                st.dataframe(pd.DataFrame(steps), hide_index=True, use_container_width=True)
            
            # 3. Chart Comparison
            # Compare vs Billed (Fetch actual from session data if possible)
            patient_exp = 0.0
            try:
                # Quick fetch of session claims to find this doc's actual billed amount
                claims_resp = api.get("/session/claims", params={"session_id": api.get_session_id()})
                if claims_resp and "rows" in claims_resp:
                    # Find matching doc_id rows
                    # Sum them up (could be multiple lines)
                    d_rows = [r for r in claims_resp["rows"] if str(r.get("doc_id")) == str(res.get("doc_id", ""))]
                    if d_rows:
                         # Use helper to safe float conversion
                        def safe_float(x):
                            try: return float(x)
                            except: return 0.0
                        patient_exp = sum(safe_float(r.get("patient_resp")) for r in d_rows)
            except:
                pass

            chart_data = pd.DataFrame({
                "Category": ["Fair Bill", "You Pay"],
                "Amount": [fair_bill, patient_exp],
                "Color": ["#3b82f6", "#ef4444"]
            })
            
            c = alt.Chart(chart_data).mark_bar().encode(
                x='Category',
                y='Amount',
                color=alt.Color('Color', scale=None),
                tooltip=['Category', 'Amount']
            ).properties(height=300)
            
            st.altair_chart(c, use_container_width=True)
            
            st.info("This is an estimate based on the extracted allowed amount and your inputs. Always verify with your payer.")
            
    else:
        with ui.card_container():
            st.info("👈 Configure and run a simulation to see the cost breakdown.")
            st.image("https://cdn-icons-png.flaticon.com/512/7486/7486831.png", width=100) # Placeholder
