"""Runs one customer message through the five deployed Endeavor tasks.

Order: input guardrail -> classification -> response/deflection
       -> output guardrail -> routing (only if not answered).
"""
import json
import os
import re

AGENT = os.environ.get("ENDEAVOR_AGENT", "customer-service-triage-and-routing-agent")
# Leave these unset to use Endeavor's default environment and latest release.
ENVIRONMENT = os.environ.get("ENDEAVOR_ENVIRONMENT") or None
VERSION = os.environ.get("ENDEAVOR_VERSION") or None

_client = None


def _endeavor():
    """Connect once, using ENDEAVOR_URL / ENDEAVOR_CLIENT_ID / ENDEAVOR_CLIENT_SECRET."""
    global _client
    if _client is None:
        import guidelight as gdl
        _client = gdl.connect()
    return _client


def _parse(result):
    """Turn whatever Endeavor returns into a dict of the task's JSON output."""
    out = result
    if isinstance(out, dict) and "output" in out:
        out = out["output"]
    if isinstance(out, str):
        text = out.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        out = json.loads(text)
    if not isinstance(out, dict):
        raise ValueError(f"unexpected task output: {out!r}")
    return out


def run_task(task, **context):
    kwargs = {"context": context}
    if ENVIRONMENT:
        kwargs["environment"] = ENVIRONMENT
    if VERSION:
        kwargs["version"] = VERSION
    return _parse(_endeavor().run(AGENT, task, **kwargs))


def handle_case(message, customer_tier="standard", account="", kb_articles=None, run=run_task):
    """Return {"status": deflected|routed|blocked|error, ...} plus a full trace."""
    kb_articles = kb_articles or []
    trace = {}

    # 1. Input guardrail. Fails closed: empty input or any error blocks.
    if not message or not message.strip():
        return {"status": "blocked", "reason": ["Empty message"], "trace": trace}
    try:
        g_in = run("input-guardrail", message=message)
    except Exception as exc:
        return {"status": "blocked", "reason": [f"Input guardrail unavailable: {exc}"], "trace": trace}
    trace["input_guardrail"] = g_in
    decision = g_in.get("decision")
    if decision not in ("pass", "redact"):
        return {"status": "blocked", "reason": g_in.get("reasons") or [], "trace": trace}
    clean = (g_in.get("sanitized_message") or message) if decision == "redact" else message

    try:
        # 2. Classify
        case = run("case-classification", message=clean)
        trace["classification"] = case

        # 3. Answer or not
        resp = run("response-and-deflection", message=clean,
                   category=case.get("category"), priority=case.get("priority"),
                   summary=case.get("summary"), kb_articles=kb_articles)
        trace["response"] = resp

        # 4. Output guardrail on a reply the agent intends to send.
        # A deflection counts as "attempted" only if the guardrail stops it.
        action = resp.get("action")
        reply = resp.get("reply") if action == "deflect" else None
        attempted = False
        if reply:
            g_out = run("output-guardrail", original_message=clean,
                        draft_reply=reply, kb_articles=kb_articles)
            trace["output_guardrail"] = g_out
            if g_out.get("decision") == "block":
                action, reply, attempted = "route", None, True
            elif g_out.get("decision") == "revise":
                reply = g_out.get("revised_reply") or None
                if reply is None:
                    action, attempted = "route", True

        if action == "deflect" and reply:
            return {"status": "deflected", "reply": reply,
                    "cited_articles": resp.get("cited_articles") or [], "trace": trace}

        # 5. Route to a person with context
        route = run("case-routing", message=clean,
                    category=case.get("category"), priority=case.get("priority"),
                    sentiment=case.get("sentiment"), complexity=case.get("complexity"),
                    summary=case.get("summary"), deflection_attempted=attempted,
                    customer_tier=customer_tier, account=account)
        trace["routing"] = route
        return {"status": "routed", "routing": route, "trace": trace}
    except Exception as exc:
        # Never leave a customer without an answer: hand to a person.
        trace["error"] = str(exc)
        return {"status": "error", "reason": [str(exc)], "trace": trace}
