"""The startup's own website — a small, polite crawl of the pages that describe the company.

Pages: the homepage plus the about / team / customers / pricing / careers / press pages discovered from the
homepage's own navigation (anchor text or path), capped at `MAX_PAGES`. Every page is stored with its text
hash so a re-crawl re-extracts only what changed. Client-rendered pages are read from their embedded JSON
(`__NEXT_DATA__`, JSON-LD) when present; otherwise the page yields little text and that is recorded honestly.
Nothing here judges meaning — the extractor does."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse

from . import http

MAX_PAGES = 8
_WANT = (("about", ("about", "about-us", "company", "our-story", "mission", "who-we-are")),
         ("team", ("team", "people", "founders", "leadership", "our-team")),
         ("customers", ("customers", "case-studies", "case-study", "success-stories", "clients")),
         ("pricing", ("pricing", "plans")),
         ("careers", ("careers", "jobs", "join", "join-us", "work-with-us", "hiring")),
         ("press", ("press", "news", "newsroom", "announcements", "blog")))
_MIN_TEXT = 200


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8", "ignore")).hexdigest()[:32]


def _embedded_json_text(h: str) -> str:
    """Text worth reading from client-rendered pages: JSON-LD and Next.js data blobs (strings only)."""
    out: list[str] = []
    for m in re.finditer(r'(?is)<script[^>]*(?:type="application/ld\+json"|id="__NEXT_DATA__")[^>]*>(.*?)</script>', h or ""):
        try:
            data = json.loads(m.group(1))
        except Exception:   # noqa: BLE001
            continue
        def walk(x, depth=0):
            if depth > 8:
                return
            if isinstance(x, str):
                s = x.strip()
                if 20 <= len(s) <= 2000 and not s.startswith(("http", "/", "{", "<")):
                    out.append(s)
            elif isinstance(x, dict):
                for v in x.values():
                    walk(v, depth + 1)
            elif isinstance(x, list):
                for v in x[:200]:
                    walk(v, depth + 1)
        walk(data)
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return "\n".join(uniq)[:20_000]


def _same_site(url: str, domain: str) -> bool:
    return http.registrable_domain(url) == domain


def crawl(website: str, *, max_pages: int = MAX_PAGES, min_gap: float = 2.0) -> dict:
    """{'domain', 'pages': [{'kind','url','final_url','status','text','html','sha'}], 'failed': [...]}."""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    domain = http.registrable_domain(website)
    pages: list[dict] = []
    failed: list[dict] = []
    home = http.get(website, min_gap=min_gap)
    if not home.ok:
        # one retry on the bare https://domain (a dead www / http redirect chain is common)
        alt = f"https://{domain}/"
        home = http.get(alt, min_gap=min_gap) if alt.rstrip("/") != website.rstrip("/") else home
    if not home.ok:
        return {"domain": domain, "pages": [], "failed": [{"kind": "home", "url": website, "status": home.status, "error": home.error}]}
    base = home.final_url or website
    text = http.html_to_text(home.text)
    if len(text) < _MIN_TEXT:
        text = (text + "\n" + _embedded_json_text(home.text)).strip()
    pages.append({"kind": "home", "url": website, "final_url": base, "status": home.status, "text": text, "html": home.text,
                  "title": http.html_title(home.text), "sha": _sha(text)})
    # candidate pages from the homepage's own links (anchor text or last path segment)
    cands: dict[str, str] = {}
    for href, anchor in http.links(home.text, base):
        if not _same_site(href, domain):
            continue
        path = urllib.parse.urlsplit(href).path.strip("/").lower()
        seg = path.split("/")[-1] if path else ""
        a = anchor.lower().strip()
        for kind, words in _WANT:
            if kind in cands:
                continue
            if seg in words or a in words or a.replace(" ", "-") in words or any(a == w.replace("-", " ") for w in words):
                cands[kind] = href.split("#")[0]
    for kind, words in _WANT:          # fall back to conventional paths for the two most valuable pages
        if kind not in cands and kind in ("about", "team", "careers"):
            cands[kind] = urllib.parse.urljoin(base, "/" + words[0])
    for kind, url in cands.items():
        if len(pages) >= max_pages:
            break
        f = http.get(url, min_gap=min_gap)
        if not f.ok:
            failed.append({"kind": kind, "url": url, "status": f.status, "error": f.error})
            continue
        if not _same_site(f.final_url, domain):
            continue
        t = http.html_to_text(f.text)
        if len(t) < _MIN_TEXT:
            t = (t + "\n" + _embedded_json_text(f.text)).strip()
        if len(t) < 80 or any(p["sha"] == _sha(t) for p in pages):
            continue
        pages.append({"kind": kind, "url": url, "final_url": f.final_url, "status": f.status, "text": t, "html": f.text,
                      "title": http.html_title(f.text), "sha": _sha(t)})
    return {"domain": domain, "pages": pages, "failed": failed}
