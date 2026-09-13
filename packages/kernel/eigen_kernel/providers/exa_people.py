"""ExaPeopleSearch — a PeopleSearchClient over Exa's neural search, scoped to public professional
profiles.

Discovery is PUBLIC-WEB semantic search (the compliant posture): we ask Exa for profiles matching a
natural-language expertise query and return the public profile URLs it surfaces, with the name/headline
Exa already indexed. We never scrape or re-host — the profile URL is the source the reader opens.

Same auth/transport as `exa_web.py` (x-api-key, lazy httpx). No key ⇒ empty (reported as such).
"""
from __future__ import annotations

import os
import re

from .people_search import PersonResult

EXA_URL = "https://api.exa.ai/search"


def _split_title(title: str, url: str) -> tuple[str, str]:
    """LinkedIn/profile titles read 'Name - Headline | LinkedIn' or 'Name | Headline'. Pull the name
    (the first segment) and the headline (the remainder, minus the site suffix)."""
    t = re.sub(r"\s*[\|\-–—]\s*LinkedIn\s*$", "", (title or "").strip(), flags=re.I).strip()
    parts = re.split(r"\s*[\|\-–—]\s*", t, maxsplit=1)
    name = (parts[0] or "").strip()
    headline = (parts[1].strip() if len(parts) > 1 else "")
    if not name:
        name = (url or "").rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
    if name and name == name.lower():        # Exa sometimes indexes the name lowercased — tidy it
        name = name.title()
    # a leading dangling punctuation ("- Lead ops…", ", cut costs…") is a mis-split; drop it
    headline = re.sub(r"^[\s,;:\-–—]+", "", headline)
    return name[:120], headline[:200]


class ExaPeopleSearch:
    def __init__(self, *, api_key: str | None = None, timeout: float = 10.0,
                 include_domains: list[str] | None = None):
        self._api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self._timeout = timeout
        # default to LinkedIn public profiles; the vertical/app may widen this.
        self._include_domains = [d for d in (include_domains or ["linkedin.com"]) if d]

    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]:
        if not self._api_key or not query.strip():
            return []
        import httpx
        payload = {
            "query": query,
            "numResults": int(max_results),
            "type": "auto",
            "category": "linkedin profile",     # Exa people vertical; ignored gracefully if unsupported
            "contents": {"text": {"maxCharacters": 600},
                         "highlights": {"numSentences": 2, "highlightsPerUrl": 1, "query": query}},
        }
        if self._include_domains and not (filters or {}).get("open_web"):
            payload["includeDomains"] = self._include_domains
        headers = {"x-api-key": self._api_key, "content-type": "application/json"}
        import asyncio
        data = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(EXA_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                break
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code != 429 and e.response.status_code < 500:
                    raise
            except httpx.HTTPError as e:
                last_err = e
            await asyncio.sleep(0.4 * (attempt + 1))
        if data is None:
            raise last_err or RuntimeError("exa people search failed")
        out: list[PersonResult] = []
        for r in data.get("results", []):
            url = r.get("url", "")
            if not url:
                continue
            name, headline = _split_title(r.get("title") or "", url)
            hl = [h for h in (r.get("highlights") or []) if h and h.strip()]
            if not headline and hl:
                headline = hl[0].strip()[:200]
            elif not headline:
                headline = (r.get("text") or "").strip()[:200]
            out.append(PersonResult(
                name=name, profile_url=url, headline=headline,
                relevance=float(r.get("score") or 0.0), provider="exa"))
        return out

    async def find_similar(self, *args, **kwargs) -> list[PersonResult]:   # reserved for Phase 2
        return []
