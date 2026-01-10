import streamlit as st
import pandas as pd
import altair as alt
from typing import Any
import html

# Import utils
from utils import api, ui

# Page Config
st.set_page_config(
    page_title="LumiClaim Dashboard",
    page_icon="📊",
    layout="wide"
)

# Initialize Session & UI
ui.inject_css()
api.ensure_session()

# Auth Guard
if not api.get_session_id():
    st.switch_page("app.py")

# --- Sidebar ---
ui.render_sidebar()
current_session = api.get_session_id()

# --- Main Content ---

# Top Header
ui.patient_header(
    name="Recent Patient", # In a real app, this would come from the profile
    age_sex="--",
    id_num=current_session[:8] if current_session else "--",
    last_visit="Today"
)

# Tabs
# Check if we need to force switch to manual entry
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "📤 Upload Document"

# Callback to switch tabs
def switch_to_manual():
    st.session_state["active_tab"] = "✍️ Manual Entry"

# We use a trick with st.tabs where we can't programmatically set the active tab index easily in older Streamlit versions
# But we can re-order or just guide the user. 
# Actually, Streamlit 1.39 doesn't support setting active tab index via state natively in st.tabs() constructor easily without a workaround.
# For now, we will just use the big button to guide them, or maybe render the manual entry form right there if they click it?
# Let's keep it simple: The button will set a flag to *show* the manual entry form or just tell them to click the tab.
# Better yet: We can use a different layout if they click "Manual Entry". 
# But let's stick to the tabs.
    
tab_upload, tab_manual, tab_dashboard = st.tabs(["📤 Upload Document", "✍️ Manual Entry", "📊 Dashboard"])

# --- TAB: UPLOAD ---
with tab_upload:
    st.markdown("### Upload Medical Documents")
    st.markdown("Upload EOBs (Explanation of Benefits), Bills, or Clinical Notes to start analysis.")
    
    col_upload, col_preview = st.columns([1, 1], gap="large")
    
    with col_upload:
        with ui.card_container():
            uploaded_file = st.file_uploader(
                "Drag and drop documents",
                type=["pdf", "docx", "png", "jpg"],
                key="eob_uploader"
            )
            
            if uploaded_file:
                st.success(f"Ready to process: **{uploaded_file.name}**")
                if st.button("Process Document", type="primary", use_container_width=True):
                    with st.spinner("Extracting data..."):
                        # Prepare upload
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                        data = api.post("/upload_eob", files=files)
                        
                        if data:
                            st.balloons()
                            st.session_state["last_upload"] = data
                            
                            # Valid upload, store bytes for the viewer page
                            st.session_state["current_file_bytes"] = uploaded_file.getvalue()
                            st.session_state["current_file_name"] = uploaded_file.name
                            st.session_state["current_file_type"] = uploaded_file.type
                            
                            doc_id = data.get("doc_id")
                            if doc_id:
                                st.session_state["current_doc_id"] = str(doc_id)
                                st.rerun()

    with col_preview:
        if st.session_state.get("last_upload"):
            last_up = st.session_state["last_upload"]
            with ui.card_container():
                st.markdown(f"**✅ Processed: `{last_up.get('doc_id')}`**")
                
                preview = last_up.get("preview", {})
                rows = preview.get("rows", [])
                
                if rows:
                    st.markdown("#### Detected Line Items")
                    df_preview = pd.DataFrame(rows)
                    # Simple clean view
                    st.dataframe(
                        df_preview[["description", "billed", "allowed", "patient_resp"]], 
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    # FAILED STATE / FALLBACK
                    st.warning("No structured table found.")
                    st.markdown("This often happens with scanned images or complex layouts.")
                    
                    st.markdown("---")
                    st.markdown("### 👇 Next Step")
                    if st.button("✍️ Enter Data Manually", type="primary", use_container_width=True):
                         # Since we can't easily switch tabs programmatically in standard st.tabs
                         # We will show a toast/message to click the tab, OR we could conditionally render content.
                         # A better UX: Just render the manual entry form HERE if they click it?
                         # No, let's keep it clean.
                         st.info("Please click the **'✍️ Manual Entry'** tab above to proceed.")
                         # In newer streamlit we could use st.switch_page or query params, but tabs are client-side.
                         
        else:
            with ui.card_container():
                st.info("Upload a document to see the extraction preview here.")

# --- TAB: MANUAL ENTRY ---
with tab_manual:
    st.markdown("### ✍️ Manual Data Entry")
    st.markdown("Add line items directly if your document is illegible or not parsing correctly.")
    

        
    with ui.card_container():
        c_desc, c_date = st.columns([3, 1])
        man_desc = c_desc.text_input("Description / Procedure", placeholder="e.g. Office Visit, X-Ray")
        man_date = c_date.text_input("Date", placeholder="MM/DD/YYYY")
        
        c_cpt, c_billed, c_allowed, c_paid, c_resp = st.columns(5)
        man_cpt = c_cpt.text_input("CPT Code", placeholder="99213")
        man_billed = c_billed.number_input("Billed ($)", min_value=0.0, step=0.01, format="%.2f")
        man_allowed = c_allowed.number_input("Allowed ($)", min_value=0.0, step=0.01, format="%.2f")
        man_paid = c_paid.number_input("Insurer Paid ($)", min_value=0.0, step=0.01, format="%.2f")
        man_resp = c_resp.number_input("You Owe ($)", min_value=0.0, step=0.01, format="%.2f")
        
        # Real-time Feedback
        if man_billed > 0:
            calc_adj = man_billed - man_allowed
            calc_owe = man_allowed - man_paid
            diff = man_resp - calc_owe
            
            if abs(diff) > 0.01:
                st.warning(f"⚠️ Math Mismatch: Allowed ({man_allowed}) - Paid ({man_paid}) = **${calc_owe:.2f}**, but you entered **${man_resp:.2f}**.")
                st.caption(f"Difference: ${abs(diff):.2f}. This might be a deductible or co-pay adjustment.")
            else:
                st.success("✅ Math looks correct!", icon="🔢")

        if st.button("➕ Add Line Item", type="primary"):
            if not man_desc:
                st.error("Description is required.")
            else:
                payload = {
                    "session_id": current_session,
                    "description": man_desc,
                    "date": man_date,
                    "cpt": man_cpt,
                    "billed": man_billed,
                    "allowed": man_allowed,
                    "insurer_paid": man_paid,
                    "patient_resp": man_resp
                }
                
                # Assume backend has /session/manual_entry or we use a helper 
                # (We added it in the previous step)
                res = api.post("/session/manual_entry", json=payload)
                if res:
                    st.success("Line item added!")
                    st.rerun()

# --- TAB: DASHBOARD ---
with tab_dashboard:
    if not current_session:
        st.warning("Please start a session or upload a document first.")
    else:
        # Fetch Session Data
        with st.spinner("Loading dashboard..."):
            resp = api.get("/session/claims", params={"session_id": current_session})
        
        # --- Quick Actions (Always Visible) ---
        st.markdown("### Quick Actions")
        qa1, qa2, qa3 = st.columns(3)
        with qa1:
            if st.button("💬 Ask Lumi a Question", use_container_width=True):
                st.switch_page("pages/7_Ask_Lumi.py")
        with qa2:
            if st.button("🛡️ Update Profile & Name", use_container_width=True):
                st.switch_page("pages/6_Benefits_Profile.py")
        with qa3:
            if st.button("🎚️ Simulate Fair Bill", use_container_width=True):
                st.switch_page("pages/3_Simulate_Costs.py")
        
        st.divider()

        if resp and resp.get("rows"):
             # Process Data
            rows = resp.get("rows", [])
            df = pd.DataFrame(rows)
            
            # Normalize columns if needed
            numeric_cols = ["billed", "allowed", "insurer_paid", "patient_resp"]
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

            # 1. Top Metrics
            st.markdown("### Session Overview")
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                 with ui.card_container():
                    st.markdown("**Total Billed**")
                    st.markdown(f"### ${df['billed'].sum():,.2f}")
            with m2:
                 with ui.card_container():
                    st.markdown("**Allowed Amount**")
                    st.markdown(f"### ${df['allowed'].sum():,.2f}")
            with m3:
                 with ui.card_container():
                    st.markdown("**Insurer Paid**")
                    st.markdown(f"### ${df['insurer_paid'].sum():,.2f}")
            with m4:
                 with ui.card_container():
                    st.markdown("**Patient Responsibility**")
                    st.markdown(f"<h3 style='color:{ui.PRIMARY_COLOR}'>${df['patient_resp'].sum():,.2f}</h3>", unsafe_allow_html=True)
            
            st.divider()

            # --- DELTA VIEW (Step 4) ---
            sim_result = st.session_state.get("sim_result")
            if sim_result:
                st.markdown("### 🔦 Delta Analysis")
                
                # Get simulation numbers
                sim_doc_id = sim_result.get("doc_id")
                sim_fair = float(sim_result.get("expected_patient_resp", 0.0))
                
                # Find the ACTUAL billed responsibility for this specific doc from our dataframe
                # df has columns: doc_id, billed, allowed, patient_resp...
                if "doc_id" in df.columns:
                     actual_row = df[df["doc_id"] == sim_doc_id]
                     if not actual_row.empty:
                         actual_resp = float(actual_row.iloc[0]["patient_resp"])
                         delta = actual_resp - sim_fair
                         
                         d1, d2, d3 = st.columns(3)
                         
                         with d1:
                             with ui.card_container():
                                 st.caption(f"Bill Says (You Owe)")
                                 st.markdown(f"### ${actual_resp:,.2f}")
                                 
                         with d2:
                             with ui.card_container():
                                 st.caption(f"Fair Bill (Simulation)")
                                 st.markdown(f"### ${sim_fair:,.2f}")
                                 
                         with d3:
                             with ui.card_container():
                                 st.caption("Potential Savings (Delta)")
                                 if delta > 0.01:
                                     st.markdown(f"<h3 style='color:#dc2626'>${delta:,.2f} ▼</h3>", unsafe_allow_html=True)
                                     st.caption("You are likely overpaying!")
                                 elif delta < -0.01:
                                      st.markdown(f"<h3 style='color:#16a34a'>${abs(delta):,.2f}</h3>", unsafe_allow_html=True)
                                      st.caption("You are paying less than expected.")
                                 else:
                                     st.markdown("### $0.00")
                                     st.caption("Matches expectation.")

                         if delta > 0:
                             st.markdown(" ")
                             # CTA to Appeal
                             if st.button("🚀 Generate Appeal Letter", type="primary"):
                                 # Set state for appeal page
                                 st.session_state["appeal_doc_id"] = sim_doc_id
                                 st.session_state["appeal_delta"] = delta
                                 st.switch_page("pages/5_Generate_Appeal.py")
            
            st.divider()

            # --- YTD PROGRESS ---
            # Try to fetch profile to see if we have Year-to-Date context
            profile_resp = api.get("/profile/get", params={"session_id": current_session})
            profile = profile_resp.get("profile") if profile_resp else None
            
            if profile:
                st.markdown("### 📅 YTD Health Spend")
                ytd_c1, ytd_c2, ytd_c3 = st.columns(3)
                
                oop_max = float(profile.get("oop_max") or 0.0)
                oop_rem = float(profile.get("oop_remaining") or 0.0)
                ded_rem = float(profile.get("deductible_remaining") or 0.0)
                
                with ytd_c1:
                   with ui.card_container():
                       st.markdown("**Deductible Remaining**")
                       st.markdown(f"## ${ded_rem:,.2f}")
                       st.progress(max(0.0, min(1.0, 1.0 - (ded_rem / (float(profile.get("deductible_individual") or 2000) or 1)))))
                
                with ytd_c2:
                   with ui.card_container():
                       st.markdown("**OOP Max Remaining**")
                       st.markdown(f"## ${oop_rem:,.2f}")
                       prog = max(0.0, min(1.0, (oop_max - oop_rem) / oop_max)) if oop_max > 0 else 0
                       st.progress(prog)
                       st.caption(f"{int(prog*100)}% met")

                with ytd_c3:
                    with ui.card_container():
                        st.markdown("**Plan Details**")
                        st.caption(f"Plan: {profile.get('plan_name', 'Unknown')}")
                        st.caption(f"Coinsurance: {float(profile.get('coinsurance') or 0)*100:.0f}%")
                st.divider()

            # --- RECONCILIATION / DELTA DETECTIVE ---
            st.markdown("### 🕵️ Delta Detective (Reconciliation)")
            
            k1, k2 = st.columns([3, 1])
            with k1:
                st.info("Analyzing session for duplicates and missing adjustments...")
            with k2:
                 if st.button("Run Full Scan", key="run_reconcile"):
                    with st.spinner("Scanning..."):
                        rec_resp = api.get(f"/reconcile/session/{current_session}")
                        st.session_state["reconcile_data"] = rec_resp

            rec_data = st.session_state.get("reconcile_data")
            if rec_data:
                anomalies = rec_data.get("anomalies", [])
                if anomalies:
                    for anomaly in anomalies:
                        with ui.card_container():
                            st.markdown(f"**⚠️ Anomaly Detected: {anomaly.get('type')}**")
                            st.write(anomaly.get("summary", str(anomaly)))
                else:
                    st.success("✅ No anomalies detected in this session.")
            
            st.divider()

            # 2. Charts & Tables
            c1, c2 = st.columns([2, 1], gap="medium")
            
            with c1:
                with ui.card_container():
                    st.markdown("#### Cost Breakdown by Document")
                    if not df.empty:
                        # Prepare for Altair
                        chart_df = df.groupby("doc_id")[numeric_cols].sum().reset_index().melt('doc_id', var_name='Metric', value_name='Amount')
                        
                        c = alt.Chart(chart_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                            x=alt.X('doc_id', axis=alt.Axis(title=None, labels=False)), # axis could be cleaner
                            y=alt.Y('Amount', axis=alt.Axis(format='$,f')),
                            color=alt.Color('Metric', scale=alt.Scale(scheme='category10')),
                            column='doc_id',
                            tooltip=['doc_id', 'Metric', 'Amount']
                        ).configure_view(stroke='transparent')
                        
                        st.altair_chart(c, use_container_width=True)
            
            with c2:
                with ui.card_container():
                    st.markdown("#### Recent Claims")
                    st.dataframe(
                        df[["doc_id", "date", "patient_resp"]].head(10) if "date" in df.columns else df[["doc_id", "patient_resp"]].head(10),
                        hide_index=True,
                        use_container_width=True
                    )
                    
        else:
            st.info("No claims data found for this session. Upload a document to get started.")

