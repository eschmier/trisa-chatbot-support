"""Customer chat page."""
import time

import streamlit as st

import core

st.set_page_config(page_title="Customer support", page_icon=":speech_balloon:")
core.load_secrets(st.secrets)
core.help_site()  # starts reading the help website in the background, if one is set

MAX_PER_MINUTE = 10

st.title("Customer support")
st.caption("Ask a question. I'll answer if I can, or pass it to the right person.")

if "chat" not in st.session_state:
    st.session_state.chat = [{"role": "assistant", "content": "Hi! How can I help today?"}]
    st.session_state.sent = []

def clear_chat():
    # Only clears what is on screen. Saved cases and the message-rate limit are untouched.
    st.session_state.chat = [{"role": "assistant", "content": "Hi! How can I help today?"}]


st.sidebar.button("Clear chat", on_click=clear_chat, use_container_width=True)

email = st.text_input("Your email (so a person can follow up)", placeholder="you@example.com")

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("ref"):
            st.caption(f"Reference: {msg['ref']}")

prompt = st.chat_input("Describe your issue")
if prompt:
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    now = time.time()
    st.session_state.sent = [t for t in st.session_state.sent if now - t < 60] + [now]

    with st.chat_message("assistant"):
        if len(st.session_state.sent) > MAX_PER_MINUTE:
            kind, text, ref = "blocked", "Too many messages. Please wait a minute.", None
        else:
            with st.spinner("Working on it…"):
                ref, result = core.run_case(prompt, "customer", email=email)
            kind, text = core.customer_view(result)
        if kind == "blocked":
            st.warning(text)
        elif kind == "handoff":
            st.info(text)
        else:
            st.markdown(text)
        if ref:
            st.caption(f"Reference: {ref}")
    st.session_state.chat.append({"role": "assistant", "content": text, "ref": ref})
