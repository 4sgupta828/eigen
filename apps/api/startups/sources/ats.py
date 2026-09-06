"""ATS job boards — the hiring signal from public board JSON (Greenhouse, Lever, Ashby), no scraping.

Each ATS exposes a company's open roles as JSON meant for embedding on its careers page. Given a company's
site HTML (careers page or homepage) the board is DISCOVERED from the links it carries (structural URL
patterns), then fetched. Returns roles `{title, location, department, url}`; the function of each role is
typed later by the extractor (the model owns that meaning), never by a title keyword here."""
from __future__ import annotations

import re

from . import http

_GH = re.compile(r"(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io|boards-api\.greenhouse\.io/v1/boards)/([A-Za-z0-9_-]+)")
_GH_EMBED = re.compile(r"greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)")
_LEVER = re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)")
BOARD_URL = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
             "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
             "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}"}


def discover(html_pages: list[str]) -> list[tuple[str, str]]:
    """[(ats, token)] found in the pages, first-seen order, de-duplicated."""
    out: list[tuple[str, str]] = []
    for h in html_pages:
        for ats, rx in (("greenhouse", _GH), ("greenhouse", _GH_EMBED), ("lever", _LEVER), ("ashby", _ASHBY)):
            for m in rx.finditer(h or ""):
                tok = m.group(1)
                if tok.lower() in ("embed", "v1", "boards", "jobs"):
                    continue
                if (ats, tok) not in out:
                    out.append((ats, tok))
    return out


def fetch_board(ats: str, token: str) -> list[dict] | None:
    """The board's open roles, or None when the board does not exist / cannot be read."""
    url = BOARD_URL[ats].format(token=token)
    data = http.get_json(url, min_gap=0.5, respect_robots=False)
    if data is None:
        return None
    roles: list[dict] = []
    if ats == "greenhouse":
        for j in (data.get("jobs") or []):
            roles.append({"title": j.get("title") or "", "location": ((j.get("location") or {}).get("name") or ""),
                          "department": ", ".join(d.get("name", "") for d in (j.get("departments") or []) if d.get("name")),
                          "url": j.get("absolute_url") or ""})
    elif ats == "lever":
        for j in (data if isinstance(data, list) else []):
            cat = j.get("categories") or {}
            roles.append({"title": j.get("text") or "", "location": cat.get("location") or "", "department": cat.get("team") or cat.get("department") or "",
                          "url": j.get("hostedUrl") or ""})
    elif ats == "ashby":
        for j in (data.get("jobs") or []):
            roles.append({"title": j.get("title") or "", "location": j.get("location") or "", "department": j.get("department") or j.get("team") or "",
                          "url": j.get("jobUrl") or ""})
    return [r for r in roles if r["title"]]


def hiring_for(html_pages: list[str]) -> tuple[list[dict], tuple[str, str] | None]:
    """Discover the board from the pages and fetch it: (roles, (ats, token)) or ([], None)."""
    for ats, tok in discover(html_pages):
        roles = fetch_board(ats, tok)
        if roles is not None:
            return roles, (ats, tok)
    return [], None
