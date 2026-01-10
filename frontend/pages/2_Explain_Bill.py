import streamlit as st
from utils import api, ui

# Page Config
st.set_page_config(
    page_title="Explain Bill | LumiClaim",
    page_icon="🧩",
    layout="wide"
)

# Initialize
ui.inject_css()
api.ensure_session()

ui.render_sidebar()

# Header
ui.patient_header(last_visit="Explain Mode")

# --- Layout: Side-by-Side ---
# Left: Controls & Explanation
# Right: Document Viewer

col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.markdown("### 🧩 Explain Medical Bill")
    st.markdown("Break down complex claims into plain language with citations.")

    # --- Controls ---
    with ui.card_container():
        # Compact controls
        c1, c2 = st.columns(2)
        
        # Load available docs
        try:
            session_data = api.get(f"/session/claims?session_id={st.session_state.session_id}")
            doc_options = [d["doc_id"] for d in session_data.get("docs", [])] if session_data else []
        except Exception:
            doc_options = []
            
        if not doc_options:
            doc_options = ["EOB-001"]

        default_doc = st.session_state.get("current_doc_id")
        if default_doc not in doc_options:
            default_doc = doc_options[0] if doc_options else "EOB-001"
            
        doc_id = c1.selectbox("Document ID", doc_options, index=doc_options.index(default_doc) if default_doc in doc_options else 0)
        
        # Enhanced Personas
        persona_map = {
            "Patient (Simple)": "patient", 
            "Patient (5-Year-Old)": "5-year-old", 
            "Spanish Speaker": "Spanish", 
            "Hindi Speaker": "Hindi",
            "Provider (Technical)": "Professional"
        }
        
        p_label = c2.selectbox("Explanation Style", list(persona_map.keys()), index=0)
        selected_persona = persona_map[p_label]
        
        if st.button("Generate Explanation", type="primary", use_container_width=True):
            st.session_state["current_doc_id"] = doc_id
            with st.spinner("Analyzing document with AI..."):
                # 1. Get Explanation (AI)
                payload = {
                    "session_id": api.get_session_id(),
                    "doc_id": doc_id,
                    "persona": selected_persona,
                    "grade_level": "8th Grade" # Default, AI adjusts by persona
                }
                # Call AI Endpoint
                ai_resp = api.post("/explain/ai", json=payload)
                
                # Also get traditional data for math/graph
                base_data = api.get(f"/explain/{doc_id}")
                
                if base_data:
                    # Inject AI summary
                    if ai_resp and "summary" in ai_resp:
                        base_data["ai_summary"] = ai_resp["summary"]
                    else:
                        base_data["ai_summary"] = base_data.get("takeaway", "AI Summary Unavailable")
                        
                    st.session_state["explain_data"] = base_data
                    
                    # 2. Get Graph
                    graph = api.get(f"/egraph/{doc_id}")
                    st.session_state["explain_graph"] = graph

    # --- Results ---
    data = st.session_state.get("explain_data")
    graph = st.session_state.get("explain_graph")

    if data:
        # Top Metrics: Score & Risk
        c_score, c_takeaway = st.columns([1, 2])
        
        verifiability = float(data.get("verifiability_score", 0.0))
        if verifiability >= 0.9:
            v_color, v_label = "#16a34a", "High"
        elif verifiability >= 0.75:
            v_color, v_label = "#facc15", "Medium"
        else:
            v_color, v_label = "#dc2626", "Low"
            
        with c_score:
            with ui.card_container():
                st.markdown(f"<div style='color:{v_color};font-weight:700;font-size:1.5rem;text-align:center'>V-Score<br>{verifiability:.2f}</div>", unsafe_allow_html=True)
    
        with c_takeaway:
            with ui.card_container():
                # Display AI Summary here
                ai_sum = data.get("ai_summary") or data.get("takeaway", "No summary.")
                st.markdown(f"**AI Summary ({p_label})**: {ai_sum}")

        # Tabs for Content
        t_plain, t_math, t_evidence = st.tabs(["🗣️ Plain English", "🧮 Math Breakdown", "🕸️ Evidence Graph"])
        
        with t_plain:
            with ui.card_container():
                st.info("Full Narrative Explanation")
                st.markdown(data.get("ai_summary", "Generate an explanation to see results."))
                
        with t_math:
            with ui.card_container():
                calcs = data.get("calcs", [])
                if calcs:
                    for c in calcs:
                        st.latex(c.get("formula"))
                        st.caption(c.get("description"))
                        st.divider()
                else:
                    st.info("No calculation trace returned.")
                    
        with t_evidence:
            with ui.card_container():
                if graph:
                    ui.render_evidence_graph(graph)
                else:
                    st.info("No evidence graph available.")

with col_right:
    # --- Document Viewer ---
    st.markdown("### 📄 Document Source")
    
    file_bytes = st.session_state.get("current_file_bytes")
    file_type = st.session_state.get("current_file_type", "")
    file_name = st.session_state.get("current_file_name", "document")
    
    with ui.card_container():
        if file_bytes:
            # Display based on type
            if "pdf" in file_type or file_name.lower().endswith(".pdf"):
                # Use base64 embedding for PDF
                import base64
                base64_pdf = base64.b64encode(file_bytes).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
            elif "image" in file_type or file_name.lower().endswith((".png", ".jpg", ".jpeg")):
                st.image(file_bytes, use_container_width=True)
            else:
                st.warning(f"Preview not available for this file type: {file_type}")
        else:
             # Fallback if no bytes in session (e.g. came from deep link or refresh)
             # Try to see if it's a sample doc
             if doc_id == "EOB-001":
                 st.info("Viewing Sample EOB-001 (PDF Preview Placeholder)")
             else:
                 st.info("No document loaded for preview. Upload a file in Dashboard first to see it here.")
                 st.page_link("pages/1_Upload_&_Dashboard.py", label="Go to Upload", icon="📤")

