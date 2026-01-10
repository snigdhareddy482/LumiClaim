import streamlit as st
from utils import api, ui
import time

# Page Config
st.set_page_config(
    page_title="Ask Lumi | LumiClaim",
    page_icon="💬",
    layout="wide"
)

# Initialize
ui.inject_css()
api.ensure_session()

ui.render_sidebar()

# Header
ui.patient_header(last_visit="Chat Mode")

st.markdown("### 💬 Ask Lumi")
st.markdown("Ask questions about your uploaded documents, insurance policy, or specific denials.")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hi! I'm Lumi. How can I help you understand your medical bills today?"}
    ]

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("Ex: Why was my MRI denied?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        with st.spinner("Thinking..."):
            # Prepare payload
            payload = {
                "question": prompt,
                "session_id": api.get_session_id(),
                # Optional: "doc_id": st.session_state.get("current_doc_id") 
                # For now, let's search globally across the session or maybe implement a filter later
            }
            
            # API Call
            resp = api.post("/chat", json=payload)
            
            if resp:
                full_response = resp.get("answer", "I'm sorry, I couldn't generate an answer.")
                citations = resp.get("citations", [])
                
                # Append citations if available
                if citations:
                    full_response += "\n\n**Sources:**"
                    for cit in citations:
                        full_response += f"\n- {cit.get('doc')} (Page {cit.get('page')})"
            else:
                 full_response = "I'm sorry, I'm having trouble connecting to my brain right now."

        # Simulate stream or just show
        message_placeholder.markdown(full_response)
        
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": full_response})
