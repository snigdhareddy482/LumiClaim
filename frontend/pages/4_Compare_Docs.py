import streamlit as st
from utils import api, ui

st.set_page_config(
    page_title="Compare Docs | LumiClaim",
    page_icon="⚖️",
    layout="wide"
)

ui.inject_css()
api.ensure_session()

ui.render_sidebar()

ui.patient_header(last_visit="Compare Mode")

st.markdown("### ⚖️ Compare Documents")
st.markdown("Identify discrepancies between two EOBs or an EOB and a Bill.")

with ui.card_container():
    c1, c2, c3 = st.columns([1, 1, 0.5], gap="medium")
    
    # Fetch available docs
    docs_resp = api.get("/documents/")
    doc_options = docs_resp if docs_resp else []
    
    with c1:
        doc_a = st.selectbox("Document A (Baseline)", doc_options, index=0 if doc_options else None)
    with c2:
        doc_b = st.selectbox("Document B (Comparison)", doc_options, index=1 if len(doc_options) > 1 else 0)
    with c3:
        st.markdown("&nbsp;", unsafe_allow_html=True) # Spacer
        if st.button("Run Comparison", type="primary", use_container_width=True):
            with st.spinner("Comparing..."):
                params = {"a": doc_a, "b": doc_b}
                data = api.get("/compare", params=params)
                st.session_state["compare_result"] = data

res = st.session_state.get("compare_result")

if res:
    c_diff, c_cite = st.columns([2, 1])
    
    with c_diff:
        with ui.card_container():
            st.markdown("#### Differences Detected")
            diffs = res.get("diff", [])
            
            if diffs:
                for d in diffs:
                    # Render diff nicely
                    st.info(f"**{d.get('field', 'Unknown')}**: {d.get('message', '')}")
            else:
                st.success("No significant discrepancies found.")
                
    with c_cite:
        with ui.card_container():
            st.markdown("#### Citation Reference")
            st.json(res.get("citations", []))
