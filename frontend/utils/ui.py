"""UI Utils and Design System for LumiClaim."""

import streamlit as st

# Design Tokens
PRIMARY_COLOR = "#F35B04"  # Vibrant Orange
BACKGROUND_COLOR = "#F7F8FA" # Soft Gray
SURFACE_COLOR = "#FFFFFF"
TEXT_COLOR = "#1A1A1A"
SECONDARY_TEXT_COLOR = "#6B7280"

def inject_css():
    """Inject custom CSS for the LumiClaim design system."""
    st.markdown(
        f"""
        <style>
            /* Global Fonts and Background */
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            
            html, body, [class*="css"] {{
                font-family: 'Inter', sans-serif;
                background-color: {BACKGROUND_COLOR};
                color: {TEXT_COLOR};
            }}

            /* Card Component Style */
            .lc-card {{
                background-color: {SURFACE_COLOR};
                border-radius: 12px;
                padding: 1.5rem;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
                border: 1px solid #E5E7EB;
                margin-bottom: 1.5rem;
            }}
            
            /* Metric Badge Style */
            .lc-metric-badge {{
                display: inline-flex;
                align-items: center;
                padding: 0.25rem 0.75rem;
                border-radius: 9999px;
                font-size: 0.875rem;
                font-weight: 500;
                background-color: #FEF3C7; /* Soft yellow/orange bg */
                color: #D97706; /* Darker orange text */
            }}
            
            /* Patient Header Style */
            .lc-patient-header {{
                background-color: {SURFACE_COLOR};
                color: {TEXT_COLOR};
                padding: 1rem 1.5rem;
                border-bottom: 1px solid #E5E7EB;
                display: flex;
                align-items: center;
                gap: 1.5rem;
                margin-bottom: 2rem;
            }}
            .lc-patient-avatar {{
                width: 48px;
                height: 48px;
                border-radius: 50%;
                background-color: #E0E7FF;
                color: #4338CA;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 700;
                font-size: 1.25rem;
            }}
            
            /* Custom Streamlit adjustments */
            .stTabs [data-baseweb="tab-list"] {{
                gap: 2rem;
            }}
            .stTabs [data-baseweb="tab"] {{
                height: 50px;
                white-space: pre-wrap;
                background-color: transparent;
                border-radius: 4px 4px 0px 0px;
                gap: 1px;
                padding-top: 10px;
                padding-bottom: 10px;
            }}
            .stTabs [aria-selected="true"] {{
                background-color: transparent;
                border-bottom: 2px solid {PRIMARY_COLOR};
                color: {PRIMARY_COLOR};
                font-weight: 600;
            }}
        </style>
        """,
        unsafe_allow_html=True
    )

def card_container(key=None):
    """Start a card container. Use with `with` statement not really possible directly with custom div in Streamlit native containers, 
    so we simulate it or just use markdown wrapper for simple things. 
    Actually, mostly used for visual separation.
    """
    return st.container(border=True) # Streamlit 1.39 supports border=True which mimics a card

def patient_header(name="Unknown Patient", age_sex="--", id_num="--", last_visit="--"):
    """Render a patient header strip."""
    # Personalization Override
    if "profile_data" in st.session_state and st.session_state["profile_data"].get("patient_name"):
        name = st.session_state["profile_data"]["patient_name"]
        
    initials = "".join([n[0] for n in name.split()[:2]]).upper()
    
    html_content = f"""
    <div class="lc-patient-header">
        <div class="lc-patient-avatar">{initials}</div>
        <div>
            <div style="font-size: 1.125rem; font-weight: 600;">{name}</div>
            <div style="color: {SECONDARY_TEXT_COLOR}; font-size: 0.875rem;">{age_sex}</div>
        </div>
        <div style="margin-left: auto; display:flex; gap: 2rem;">
             <div>
                <div style="color: {SECONDARY_TEXT_COLOR}; font-size: 0.75rem;">Patient ID</div>
                <div style="font-weight: 500;">{id_num}</div>
             </div>
             <div>
                <div style="color: {SECONDARY_TEXT_COLOR}; font-size: 0.75rem;">Last Visit</div>
                <div style="font-weight: 500;">{last_visit}</div>
             </div>
        </div>
    </div>
    """
    st.markdown(html_content, unsafe_allow_html=True)

def render_evidence_graph(graph_data):
    """Render the evidence graph using PyVis or fallback table."""
    import streamlit.components.v1 as st_components
    import html
    import tempfile
    import os
    
    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or []
    
    try:
        from pyvis.network import Network
    except ImportError:
        Network = None

    if Network and nodes and edges:
        net = Network(height="300px", width="100%", notebook=False, directed=True)
        net.toggle_physics(False)
        color_map = {
            "amount": "#3b82f6",
            "code": "#f97316",
            "source": "#22c55e",
            "policy": "#8b5cf6",
            "warning": "#ef4444",
        }
        for node in nodes:
            node_id = node.get("id")
            if not node_id: continue
            label = node.get("label") or node_id
            color = color_map.get(node.get("kind"), "#6b7280")
            net.add_node(node_id, label=label, color=color)
        
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source and target:
                net.add_edge(source, target, label=edge.get("type", ""))
        
        try:
            # Generate HTML string
            # pyvis write_html writes to file, so we use temp file
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
            net.write_html(tmp.name)
            with open(tmp.name, "r", encoding="utf-8") as f:
                html_str = f.read()
            os.unlink(tmp.name)
            
            st_components.html(html_str, height=320, scrolling=False)
            return
        except Exception as e:
            st.error(f"Graph error: {e}")

    # Fallback Table
    if nodes:
        st.markdown("#### Evidence Nodes")
        st.dataframe(nodes)

def render_sidebar():
    """Render the standardized sidebar for all pages."""
    from utils import api # Lazy import to avoid circular dependency if any
    
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=50)
        st.title("LumiClaim")
        st.markdown("---")
        
        # Debug Info
        current_session = api.get_session_id()
        if current_session:
             # Only show if explicitly requested or in debug mode? 
             # Let's keep it hidden/expander as requested
            with st.expander("Debug: Session Info"):
                st.caption("Active Session ID")
                st.code(current_session)
        
        st.markdown("### Navigation")
        # Define all pages
        st.page_link("pages/1_Upload_&_Dashboard.py", label="Dashboard", icon="📊")
        st.page_link("pages/2_Explain_Bill.py", label="Explain Bill", icon="🧩")
        st.page_link("pages/3_Simulate_Costs.py", label="Simulate Costs", icon="🎚️")
        st.page_link("pages/4_Compare_Docs.py", label="Compare Docs", icon="⚖️")
        st.page_link("pages/5_Generate_Appeal.py", label="Generate Appeal", icon="📝")
        st.page_link("pages/6_Benefits_Profile.py", label="Profile", icon="🛡️")
        st.page_link("pages/7_Ask_Lumi.py", label="Ask Lumi", icon="💬")
        
        st.markdown("---")
        if st.button("Logout", type="secondary", use_container_width=True):
            # Clear entire session state to logout
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

