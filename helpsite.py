"""Reads a public help website and splits it into short sections the agent can answer from.

Set HELP_SITE_URL to the help center's home page (or its sitemap.xml).
Only pages on the same site, under the same path, are read.
"""
import os
import re
import time
import urllib.robotparser
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "support-chatbot/1.0 (help site reader)"
MAX_SECTION_CHARS = 1500
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|zip|mp4|mp3|css|js|ico|xml|json)$", re.I)


def _get(url, timeout=15):
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)


def _in_scope(url, root):
    u, r = urlparse(url), urlparse(root)
    if u.scheme not in ("http", "https") or u.netloc != r.netloc:
        return False
    prefix = r.path if r.path.endswith("/") else r.path.rsplit("/", 1)[0] + "/"
    return u.path.startswith(prefix) and not SKIP_EXT.search(u.path)


def _robots(root):
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = _get(urljoin(root, "/robots.txt"), timeout=10)
        rp.parse(resp.text.splitlines() if resp.ok else [])
    except Exception:
        rp.parse([])
    return rp


def _sitemap_urls(root, fetch):
    """Page addresses from the site's sitemap, following sitemap index files."""
    start = root if root.endswith(".xml") else urljoin(root, "/sitemap.xml")
    todo, seen, pages = [start], set(), []
    while todo and len(seen) < 20:
        sm = todo.pop()
        if sm in seen:
            continue
        seen.add(sm)
        try:
            resp = fetch(sm)
            if not resp.ok:
                continue
        except Exception:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
        if "<sitemapindex" in resp.text:
            todo.extend(locs)
        else:
            pages.extend(locs)
    return pages


def split_page(html, url):
    """Turn one HTML page into sections: [{id, title, body, url}]."""
    soup = BeautifulSoup(html, "html.parser")
    page_title = (soup.title.get_text(" ", strip=True) if soup.title else "") or url
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    h1 = main.find("h1")
    if h1:
        page_title = h1.get_text(" ", strip=True)

    sections, heading, buf = [], page_title, []

    def flush():
        text = re.sub(r"\s+", " ", " ".join(buf)).strip()
        while text:
            chunk, text = text[:MAX_SECTION_CHARS], text[MAX_SECTION_CHARS:]
            if len(chunk) > 40:
                title = page_title if heading == page_title else f"{page_title}: {heading}"
                sections.append({"title": title, "body": chunk, "url": url})

    for el in main.find_all(["h1", "h2", "h3", "p", "li", "td", "pre", "blockquote", "dd", "dt"]):
        if el.name in ("h1", "h2", "h3"):
            flush()
            buf = []
            heading = el.get_text(" ", strip=True) or heading
        elif not el.find(["p", "li"]):  # skip containers whose children are counted
            buf.append(el.get_text(" ", strip=True))
    flush()
    for i, s in enumerate(sections):
        s["id"] = f"{url}#{i + 1}"
    return sections


def load_help_site(root=None, max_pages=None, fetch=_get, delay=0.2):
    """Read the help site. Returns (sections, pages_read, problems)."""
    root = root or os.environ.get("HELP_SITE_URL", "")
    max_pages = int(max_pages or os.environ.get("HELP_SITE_MAX_PAGES", "200"))
    if not root:
        return [], 0, []
    page_root = root if not root.endswith(".xml") else urljoin(root, "/")
    robots = _robots(page_root) if fetch is _get else None

    def allowed(u):
        return robots is None or robots.can_fetch(USER_AGENT, u)

    queue = deque(u for u in _sitemap_urls(root, fetch) if _in_scope(u, page_root))
    crawl = not queue  # no sitemap: follow links instead
    if crawl:
        queue.append(page_root)

    seen, sections, problems = set(), [], []
    while queue and len(seen) < max_pages:
        url = urldefrag(queue.popleft())[0]
        if url in seen or not allowed(url):
            continue
        seen.add(url)
        try:
            resp = fetch(url)
            if not resp.ok or "html" not in resp.headers.get("Content-Type", "text/html"):
                continue
        except Exception as exc:
            problems.append(f"{url}: {exc}")
            continue
        sections.extend(split_page(resp.text, url))
        if crawl:
            for a in BeautifulSoup(resp.text, "html.parser").find_all("a", href=True):
                nxt = urldefrag(urljoin(url, a["href"]))[0]
                if _in_scope(nxt, page_root) and nxt not in seen:
                    queue.append(nxt)
        if delay:
            time.sleep(delay)
    return sections, len(seen), problems
