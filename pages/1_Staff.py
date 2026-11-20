"""Staff console: password protected. Every case, with routing and handoff details."""
import hmac
import os
from datetime import datetime

import time

import streamlit as st

import core

st.set_page_config(page_title="Support staff", page_icon=":clipboard:", layout="wide")
core.load_secrets(st.secrets)

# ---------- sign-in ----------
password = os.environ.get("STAFF_PASSWORD", "")
if not st.session_state.get("staff_ok"):
    st.title("Staff sign-in")
    if not password:
        st.error("No STAFF_PASSWORD is set in this app's secrets, so the staff page is locked.")
        st.stop()
    entered = st.text_input("Staff password", type="password")
    if entered:
        if hmac.compare_digest(entered, password):
            st.session_state.staff_ok = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()

st.title("Support staff console")
LABEL = {"greeting": "Greeting (friendly reply)", "off_topic": "Off topic (declined)", "deflected": "Answered by agent", "routed": "Needs a person",
         "blocked": "Blocked", "error": "Error, needs a person"}

left, right = st.columns([1, 2], gap="large")

# ---------- test a case ----------
with left:
    st.subheader("Test a case")
    with st.form("test", clear_on_submit=False):
        message = st.text_area("Customer message", height=140)
        tier = st.selectbox("Customer tier", ["standard", "enterprise"])
        account = st.text_input("Account (optional)")
        if st.form_submit_button("Run case", type="primary") and message.strip():
            with st.spinner("Running all five steps…"):
                core.run_case(message, "staff test", customer_tier=tier, account=account)
            st.success("Done. See it in the case list.")
    st.subheader("Blocked by rate limits")
    _b = core.recent_blocked(20)
    if not _b:
        st.caption("None in the last 7 days.")
    for _x in _b:
        st.caption(time.strftime("%b %d %H:%M", time.localtime(_x["ts"])) + f" · {_x['ip'] or 'address unknown'} · {_x['why']}")
    st.subheader("Help website")
    core.help_site()
    s = core.help_site_status()
    if not s["url"]:
        st.caption("No help website set. Add HELP_SITE_URL to the app's secrets.")
    else:
        st.caption(s["url"])
        if s["loading"]:
            st.info("Reading the help website… This can take a few minutes. Refresh to check.")
        elif s["error"]:
            st.error(f"Couldn't read the help website: {s['error']}")
        else:
            when = datetime.fromtimestamp(s["built_at"] or s["loaded_at"]).strftime("%b %d, %I:%M %p")
            st.write(f"**{s['sections']}** sections from **{s['pages']}** pages")
            st.caption(f"Source: {s['source']} · {'built' if s['source'] == 'saved copy' else 'read'} {when}")
            if s["source"] == "read live":
                st.caption("No saved copy in the repo yet, so the site is read at every restart. "
                           "On GitHub: Actions, then Refresh help index, then Run workflow, to add one.")
            st.caption(f"Search by meaning: {s['semantic']}")
            if s["pages"] and not s["sections"]:
                st.warning("Pages were read but no text was found. The site may need JavaScript to show its content.")
        if s["problems"]:
            with st.expander(f"{len(s['problems'])} pages couldn't be read"):
                st.markdown("\n".join(f"- {p}" for p in s["problems"]))
        if st.button("Refresh help pages now", disabled=s["loading"]):
            core.help_site(refresh=True)
            st.rerun()

    if st.button("Sign out"):
        st.session_state.staff_ok = False
        st.rerun()

# ---------- cases ----------
with right:
    top = st.columns([3, 1])
    top[0].subheader("Cases")
    if top[1].button("Refresh"):
        st.rerun()
    view = st.radio("Show", ["Needs a person", "All", "Answered by agent", "Blocked"],
                    horizontal=True, label_visibility="collapsed")

    def keep(c):
        if view == "All":
            return True
        if view == "Needs a person":
            return c["status"] in ("routed", "error") and not c["resolved"]
        if view == "Answered by agent":
            return c["status"] == "deflected"
        return c["status"] == "blocked"

    cases = [c for c in core.list_cases() if keep(c)]
    if not cases:
        st.caption("No cases here.")

    for c in cases:
        r = c["result"] or {}
        trace = r.get("trace") or {}
        route = r.get("routing") or {}
        cls = trace.get("classification") or {}
        when = datetime.fromtimestamp(c["created"]).strftime("%b %d, %I:%M %p")
        title = f"{LABEL.get(c['status'], c['status'])} · {when} · #{c['id']}"
        if c["resolved"]:
            title += " · resolved"
        with st.expander(title, expanded=(view == "Needs a person")):
            st.caption(f"From: {c['source']}" + (f" · {c['email']}" if c["email"] else ""))
            st.markdown("> " + c["message"].replace("\n", "\n> "))
            if cls:
                st.write(f"**Category:** {cls.get('category')} · {cls.get('priority')} · {cls.get('sentiment')}")
            if c["status"] == "deflected":
                st.write("**Reply sent:**")
                st.markdown(r.get("reply", ""))
            if c["status"] == "routed":
                st.write(f"**Team / queue:** {route.get('team')} / {route.get('queue')}")
                st.write(f"**SLA:** {route.get('sla_tier')} · **Escalate:** "
                         f"{'Yes, to a manager' if route.get('escalate_to_manager') else 'No'}")
                st.write(f"**Handoff:** {route.get('handoff_summary', '')}")
                if route.get("customer_context"):
                    st.write("**Customer context**")
                    st.markdown("\n".join(f"- {x}" for x in route["customer_context"]))
                if route.get("suggested_next_steps"):
                    st.write("**Suggested next steps**")
                    st.markdown("\n".join(f"- {x}" for x in route["suggested_next_steps"]))
            used = r.get("articles")
            if used is not None:
                st.write("**Help pages the agent was shown**")
                if used:
                    st.markdown("\n".join(f"- [{a['title'] or a['url']}]({a['url']})" if a.get("url")
                                         else f"- {a['title']}" for a in used))
                else:
                    st.caption("None found for this question.")
            if c["status"] in ("blocked", "error"):
                st.write("**Reason**")
                st.markdown("\n".join(f"- {x}" for x in (r.get("reason") or [])))
            if c["status"] in ("routed", "error") and not c["resolved"]:
                if st.button("Mark resolved", key="res-" + c["id"]):
                    core.resolve_case(c["id"])
                    st.rerun()
            st.caption("Every step, in detail")
            st.json(trace, expanded=False)
