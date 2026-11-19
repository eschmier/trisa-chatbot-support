"""Shared logic for both pages: secrets, help articles, case storage, customer wording."""
import json
import math
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

import pipeline

BASE = Path(__file__).parent
SECRET_KEYS = ["ENDEAVOR_URL", "ENDEAVOR_AUTH_URL", "ENDEAVOR_CLIENT_ID", "ENDEAVOR_CLIENT_SECRET",
               "ENDEAVOR_AGENT", "ENDEAVOR_ENVIRONMENT", "ENDEAVOR_VERSION", "STAFF_PASSWORD", "DB_PATH",
               "HELP_SITE_URL", "HELP_SITE_MAX_PAGES", "SEMANTIC_SEARCH", "SEMANTIC_MIN", "EMBEDDING_MODEL"]


def load_secrets(secrets):
    """Copy Streamlit secrets into the environment, where the Endeavor SDK reads them."""
    for key in SECRET_KEYS:
        try:
            if key in secrets and key not in os.environ:
                os.environ[key] = str(secrets[key])
        except Exception:
            pass
    pipeline.ENVIRONMENT = os.environ.get("ENDEAVOR_ENVIRONMENT") or None
    pipeline.VERSION = os.environ.get("ENDEAVOR_VERSION") or None
    if os.environ.get("ENDEAVOR_AGENT"):
        pipeline.AGENT = os.environ["ENDEAVOR_AGENT"]


# ---------- help articles ----------

def load_kb():
    try:
        return json.loads((BASE / "kb.json").read_text())
    except Exception:
        return []


STOP = set("the and for you your our are was were with this that have has how can not but from what when where why who "
           "will would could should there their them they its into about please thanks thank help need want get got".split())


_ENDINGS = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s")


def _stem(word):
    """Ignore common endings so 'webhooks' matches 'webhook' and 'deployment' matches 'deploy'."""
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)] + ("y" if end == "ies" else "")
    return word


def _words(text):
    return {_stem(w) for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOP}


SEMANTIC_TOP = 8


def semantic_enabled():
    """Meaning search is off unless the secret SEMANTIC_SEARCH is set to "on"."""
    return os.environ.get("SEMANTIC_SEARCH", "off").strip().lower() in ("on", "true", "1", "yes")


def _semantic_min():
    """How close in meaning a section must be (0 to 1)."""
    try:
        return float(os.environ.get("SEMANTIC_MIN", "0.55"))
    except ValueError:
        return 0.55


def _semantic_scores(message, help_sections):
    """Similarity of the question to each help-site section, or None if meaning search isn't ready."""
    vecs = _site.get("vectors")
    emb = _site.get("embedder")
    if vecs is None or emb is None or _site.get("vectors_for") is not help_sections or len(vecs) != len(help_sections):
        return None
    try:
        return vecs @ emb.query(message)
    except Exception:
        return None


def pick_articles(message, help_sections=(), limit=5, per_page=2):
    """Send the most relevant passages to the agent: kb.json entries plus help-site sections.

    Two searches are combined. Meaning search (when ready) finds pages worded differently from
    the question. Word search (always on) counts rare words more than common ones, so "webhook"
    beats "deploy" when "deploy" is all over the site. No single page can fill every slot."""
    kb = list(load_kb())
    docs = kb + list(help_sections)
    if not docs:
        return []
    words = _words(message)

    # word search
    kw_rank = []
    if words:
        parts = [(art, _words(art.get("title", "")), _words(art.get("body", ""))) for art in docs]
        n = len(parts)
        weight = {}
        for w in words:
            df = sum(1 for _, t, b in parts if w in t or w in b)
            if df:
                weight[w] = math.log(1 + n / df)
        scored = []
        for i, (_, t, b) in enumerate(parts):
            score = sum(wt * (2 if w in t else 1) for w, wt in weight.items() if w in t or w in b)
            if score >= 1.5:
                scored.append((score, i))
        kw_rank = [i for _, i in sorted(scored, reverse=True)]

    # meaning search (sections only; kb.json entries are word-search only)
    sem_rank = []
    sims = _semantic_scores(message, help_sections)
    if sims is not None:
        order = sorted(range(len(sims)), key=lambda j: -float(sims[j]))[:SEMANTIC_TOP]
        sem_rank = [len(kb) + j for j in order if float(sims[j]) >= _semantic_min()]

    # combine: reciprocal rank fusion
    fused = {}
    for rank_list in (kw_rank, sem_rank):
        for pos, i in enumerate(rank_list):
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + pos)
    picked, per = [], {}
    for i, _ in sorted(fused.items(), key=lambda kv: -kv[1]):
        art = docs[i]
        key = art.get("url") or art.get("id")
        if per.get(key, 0) >= per_page:
            continue
        per[key] = per.get(key, 0) + 1
        picked.append(art)
        if len(picked) >= limit:
            break
    return picked


# ---------- help website (read in the background, refreshed daily) ----------

import threading

_site = {"sections": [], "pages": 0, "problems": [], "loaded_at": 0.0, "loading": False, "error": "",
         "vectors": None, "vectors_for": None, "embedder": None, "semantic": "not started"}
_site_lock = threading.Lock()
SITE_REFRESH_SECONDS = 24 * 3600


def _get_embedder():
    if _site.get("embedder") is None:
        import semantic
        _site["embedder"] = semantic.Embedder()
    return _site["embedder"]


def _build_vectors(sections):
    """Meaning search index. Word search works meanwhile; any failure just leaves word search on."""
    if not sections:
        _site["semantic"] = "off (no help pages)"
        return
    if not semantic_enabled():
        _site.update(vectors=None, vectors_for=None, semantic='off (add SEMANTIC_SEARCH = "on" to Secrets to enable)')
        return
    try:
        import semantic
        _site["semantic"] = "building"
        emb = _get_embedder()
        vecs = emb.docs([semantic.section_text(s) for s in sections])
        _site.update(vectors=vecs, vectors_for=sections, semantic="on")
    except Exception as exc:
        _site.update(vectors=None, vectors_for=None, semantic=f"off, word search only ({type(exc).__name__}: {str(exc)[:120]})")


def _load_site():
    import helpsite
    try:
        sections, pages, problems = helpsite.load_help_site()
        _site.update(sections=sections, pages=pages, problems=problems[:20], error="")
        _build_vectors(sections)
    except Exception as exc:
        _site["error"] = str(exc)
    finally:
        _site.update(loaded_at=time.time(), loading=False)


def help_site(refresh=False, wait=False):
    """Current help-site sections. Starts a background read when needed."""
    if not os.environ.get("HELP_SITE_URL"):
        return []
    with _site_lock:
        stale = time.time() - _site["loaded_at"] > SITE_REFRESH_SECONDS
        if (refresh or stale) and not _site["loading"]:
            _site["loading"] = True
            t = threading.Thread(target=_load_site, daemon=True)
            t.start()
        else:
            t = None
    if wait and t:
        t.join()
    return _site["sections"]


def help_site_status():
    return {k: _site[k] for k in ("pages", "problems", "loaded_at", "loading", "error", "semantic")} | {
        "sections": len(_site["sections"]), "url": os.environ.get("HELP_SITE_URL", "")}


# ---------- storage ----------

def _db():
    conn = sqlite3.connect(os.environ.get("DB_PATH", str(BASE / "cases.db")))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY, created REAL, source TEXT, email TEXT,
        message TEXT, status TEXT, team TEXT, queue TEXT, sla TEXT,
        result TEXT, resolved INTEGER DEFAULT 0)""")
    return conn


def save_case(source, email, message, result):
    route = result.get("routing") or {}
    case_id = uuid.uuid4().hex[:10]
    with _db() as conn:
        conn.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                     (case_id, time.time(), source, email, message, result["status"],
                      route.get("team"), route.get("queue"), route.get("sla_tier"),
                      json.dumps(result)))
    return case_id


def list_cases(limit=200):
    with _db() as conn:
        rows = conn.execute("SELECT * FROM cases ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "result": json.loads(r["result"])} for r in rows]


def resolve_case(case_id):
    with _db() as conn:
        conn.execute("UPDATE cases SET resolved=1 WHERE id=?", (case_id,))


# ---------- running a case ----------

def run_case(message, source, email="", customer_tier="standard", account="", help_sections=None):
    message = (message or "")[:4000]
    if help_sections is None:
        help_sections = help_site()
    articles = pick_articles(message, help_sections)
    result = pipeline.handle_case(message, customer_tier=customer_tier, account=account,
                                  kb_articles=articles)
    # Keep what the agent was shown, so staff can see why it answered or routed.
    result["articles"] = [{"title": a.get("title", ""), "url": a.get("url", "")} for a in articles]
    case_id = save_case(source, email, message, result)
    return case_id, result


SLA_WORDS = {"1h": "within the hour", "4h": "within 4 hours",
             "1_business_day": "within 1 business day", "2_business_days": "within 2 business days"}
TEAM_WORDS = {"help_desk": "support team", "solutions_engineering": "engineering team"}


def customer_view(result):
    """What a customer may see: never reasons, routing internals or traces."""
    status = result["status"]
    if status == "deflected":
        return "answer", result["reply"]
    if status == "routed":
        r = result.get("routing") or {}
        team = TEAM_WORDS.get(r.get("team"), "support team")
        when = SLA_WORDS.get(r.get("sla_tier"), "as soon as possible")
        return "handoff", (f"Thanks, I've passed this to our {team} with the details. "
                           f"A person will follow up {when}.")
    if status == "blocked":
        return "blocked", ("Sorry, I can't help with that request. "
                           "If you need support, please describe your issue.")
    return "handoff", "Thanks, I've passed this to our support team. A person will follow up soon."
