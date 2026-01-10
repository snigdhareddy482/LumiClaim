import streamlit as st
import json
import base64
from utils import api, ui

st.set_page_config(
    page_title="Generate Appeal | LumiClaim",
    page_icon="📨",
    layout="wide"
)

ui.inject_css()
api.ensure_session()

ui.render_sidebar()

ui.patient_header(last_visit="Appeal Generator")

st.markdown("### 📨 Generate Appeal Packet")
st.markdown("Create a comprehensive appeal letter with supporting evidence.")

with ui.card_container():
    c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
    
    default_doc = st.session_state.get("current_doc_id", "EOB-001")
    
    with c1:
        doc_id = st.text_input("Document ID", value=default_doc)
    with c2:
        tone = st.selectbox("Tone", ["polite", "firm"], index=0)
    with c3:
        audience = st.selectbox("Audience", ["payer", "provider"], index=0)
    
    st.markdown("### 📝 Context & Notes")
    user_context = st.text_area(
        "Add specific details (e.g. 'Dr. Smith called Cigna on Tuesday')",
        placeholder="Lumi uses this context to write a stronger letter."
    )

    with c4:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        # AI Draft
        if st.button("✨ Draft with AI", type="primary", use_container_width=True):
            with st.spinner("Lumi is writing your appeal..."):
                payload = {
                    "doc_id": doc_id, 
                    "session_id": api.get_session_id(),
                    "user_context": user_context
                }
                res = api.post("/appeal/generate_ai", json=payload)
                if res:
                    st.session_state["appeal_result"] = {
                        "body": res.get("body"), 
                        "subject": res.get("subject"),
                        "doc_id": doc_id
                    }
        
        # Template Fallback
        if st.button("Use Template (Fast)", use_container_width=True):
            with st.spinner("Drafting appeal..."):
                payload = {"doc_id": doc_id, "tone": tone, "audience": audience}
                data = api.post("/appeal", json=payload)
                st.session_state["appeal_result"] = data

res = st.session_state.get("appeal_result")

if res:
    with ui.card_container():
        st.subheader(res.get("subject", "Appeal Draft"))
        
        # Adjustable Body
        current_body = res.get("body", "")
        updated_body = st.text_area("Appeal Body (Editable)", value=current_body, height=500)
        
        if updated_body != current_body:
             res["body"] = updated_body
             st.session_state["appeal_result"] = res

        # exhibits if any
        exhibits = res.get("exhibits", [])
        if exhibits:
             st.markdown("#### Included Exhibits")
             for ex in exhibits:
                 st.markdown(f"- **{ex.get('label')}**: {ex.get('title')}")

        st.markdown("---")
        
        # Download Logic
        slug = f"{doc_id}_appeal"
        api_base = api.get_api_base() 
        sid = api.get_session_id()
        
        # JS Export
        export_payload = {
            "doc_id": doc_id, "tone": tone, "audience": audience, "session_id": sid
        }
        
        import streamlit.components.v1 as components
        js_code = f"""
        <div style="display:flex; gap:10px; margin-top:1rem;">
            <button id="btn-docx-{slug}" class="lc-btn">Download Word (DOCX)</button>
            <button id="btn-pdf-{slug}" class="lc-btn">Download PDF</button>
        </div>
        <style>
            .lc-btn {{ background-color: {ui.PRIMARY_COLOR}; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: 500; }}
            .lc-btn:hover {{ opacity: 0.9; }}
        </style>
        <script>
            const payload = {json.dumps(export_payload)};
            const apiBase = "{api_base}";
            async function download(type) {{
                const endpoint = type === 'docx' ? '/appeal_docx' : '/appeal_pdf';
                try {{
                    const resp = await fetch(apiBase + endpoint, {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(payload)
                    }});
                    if (!resp.ok) {{ 
                         const err = await resp.text();
                         alert("Download failed: " + err); 
                         return; 
                    }}
                    const blob = await resp.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = "Appeal_{doc_id}." + type;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                }} catch (e) {{ alert("Error: " + e); }}
            }}
            document.getElementById("btn-pdf-{slug}").addEventListener("click", () => download('pdf'));
            document.getElementById("btn-docx-{slug}").addEventListener("click", () => download('docx'));
        </script>
        """
        components.html(js_code, height=80)

# --- Close the Loop: Outcome Tracker ---
st.markdown("---")
st.markdown("### 🏹 Close the Loop: Track Outcome")
st.info("Improve your future appeals by tracking what worked and what didn't.")

with ui.card_container():
    c1, c2, c3 = st.columns([1, 1, 1])
    
    # We allow tracking for ANY document, not just the one just appealed
    active_doc_id = st.text_input("Document ID to Track", value=doc_id, key="track_doc_id")
    
    status_options = ["Sent", "In Review", "Accepted", "Denied", "Partial Payment"]
    new_status = st.selectbox("Update Status", status_options)
    
    notes = st.text_area("Notes (optional)", placeholder="e.g. Cigna agreed to pay 80% after phone call...")
    
    if st.button("Save Status"):
        payload = {
            "session_id": api.get_session_id(),
            "doc_id": active_doc_id,
            "status": new_status,
            "notes": notes
        }
        res = api.post("/appeal/track", json=payload)
        if res:
            st.success(f"Status updated to '{new_status}'")
            st.rerun()

# --- History ---
st.markdown("#### Appeal History")
history_data = api.get("/appeal/history", params={"session_id": api.get_session_id()})
if history_data:
    st.dataframe(
        history_data, 
        column_order=["timestamp", "doc_id", "status", "notes"],
        hide_index=True,
        use_container_width=True
    )
else:
    st.caption("No appeals tracked yet.")

