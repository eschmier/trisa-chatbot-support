"""Customer chat page."""
import time

import streamlit as st

import core

core.load_secrets(st.secrets)
core.help_site()  # starts reading the help website in the background, if one is set

MAX_PER_MINUTE = 10   # quick per-tab brake; the real limits are counted in core.check_and_record
GREETING = ("Hi! I'm the TRISA Support Assistant, an AI. Ask me about the Envoy node, "
            "webhooks, configuration or setup.")
STARTERS = ["How do I configure a webhook?", "How do I set up mTLS?", "How do I deploy Envoy?"]

try:  # remembers the email in the customer's own browser; the app still works without it
    from streamlit_local_storage import LocalStorage
    _store = LocalStorage()
except Exception:
    _store = None


def clear_chat():
    # Only clears what is on screen. Saved cases and the message-rate limit are untouched.
    st.session_state.chat = [{"role": "assistant", "content": GREETING}]


def forget_email():
    st.session_state.email = ""
    st.session_state.email_saved = ""
    if _store:
        try:
            _store.deleteItem("support_email", key="del_email")
        except Exception:
            pass


def transcript(fmt):
    lines = []
    if fmt == "md":
        lines.append("# Support chat\n")
    for m in st.session_state.chat:
        who = "You" if m["role"] == "user" else "Support"
        if fmt == "md":
            lines.append(f"**{who}:** {m['content']}\n")
            if m.get("ref"):
                lines.append(f"_Reference: {m['ref']}_\n")
        else:
            lines.append(f"{who}: {m['content']}")
            if m.get("ref"):
                lines.append(f"Reference: {m['ref']}")
            lines.append("")
    return "\n".join(lines)


def show_how(how):
    if not how:
        return
    with st.expander("How I answered this"):
        for s in how["steps"]:
            st.markdown(f"- {s}")
        if how.get("why"):
            st.markdown(f"**Why I could answer this:** {how['why']}")
        if how.get("pages"):
            st.markdown("**Help pages I used:**")
            for p in how["pages"]:
                st.markdown(f"- [{p['title']}]({p['url']})" if p.get("url") else f"- {p['title']}")


st.title("TRISA Support Assistant")
st.caption("AI assistant. Answers are based on the official docs at trisa.dev and may be incomplete. "
           "If I can't answer, I'll pass your question to the right person.")

if "chat" not in st.session_state:
    st.session_state.chat = [{"role": "assistant", "content": GREETING}]
    st.session_state.sent = []
    st.session_state.email = ""
    st.session_state.email_saved = ""

# Fill the email from this browser's saved copy, once, if the box is still empty.
if _store and not st.session_state.get("email_loaded"):
    try:
        saved = _store.getItem("support_email", key="get_email")
    except Exception:
        saved = None
    if saved:
        if not st.session_state.email:
            st.session_state.email = saved
        st.session_state.email_saved = saved
        st.session_state.email_loaded = True

email = st.sidebar.text_input("Your email (so a person can follow up)", key="email",
                              placeholder="you@example.com")
st.sidebar.button("Clear chat", on_click=clear_chat, use_container_width=True)
if len(st.session_state.chat) > 1:
    st.sidebar.download_button("Download chat (.md)", transcript("md"), "support-chat.md",
                               "text/markdown", use_container_width=True)
    st.sidebar.download_button("Download chat (.txt)", transcript("txt"), "support-chat.txt",
                               "text/plain", use_container_width=True)

if email and email != st.session_state.email_saved:
    st.session_state.email_saved = email
    st.session_state.email_loaded = True
    if _store:
        try:
            _store.setItem("support_email", email, key="set_email")
        except Exception:
            pass
if _store and email:
    st.sidebar.button("Not you? Forget this email", on_click=forget_email)

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("ref"):
            st.caption(f"Reference: {msg['ref']}")
        show_how(msg.get("how"))

def pick_starter(q):
    st.session_state.starter = q


if len(st.session_state.chat) == 1:
    st.caption("Try one of these:")
    for q in STARTERS:
        st.button(q, key="starter_" + q, on_click=pick_starter, args=(q,))

prompt = st.chat_input("Describe your issue", max_chars=core.max_message_chars())
if not prompt and st.session_state.get("starter"):
    prompt = st.session_state.pop("starter")
if prompt:
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    now = time.time()
    st.session_state.sent = [t for t in st.session_state.sent if now - t < 60] + [now]

    how = None
    with st.chat_message("assistant"):
        if len(st.session_state.sent) > MAX_PER_MINUTE:
            kind, text, ref = "blocked", "Too many messages. Please wait a minute.", None
        elif not core.check_and_record(core.visitor_ip(getattr(st, "context", None) and st.context.headers or {}), email)[0]:
            kind, text, ref = "blocked", "We're getting a lot of messages right now. Please try again in a little while.", None
        else:
            with st.spinner("Working on it…"):
                ref, result = core.run_case(prompt, "customer", email=email)
            kind, text = core.customer_view(result)
            how = core.how_view(result)
        if kind == "blocked":
            st.warning(text)
        elif kind == "handoff":
            st.info(text)
        else:
            st.markdown(text)
        if ref:
            st.caption(f"Reference: {ref}")
        show_how(how)
    st.session_state.chat.append({"role": "assistant", "content": text, "ref": ref, "how": how})

