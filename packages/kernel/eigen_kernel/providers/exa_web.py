"""ExaWebSearch — a real WebSearchClient over the Exa (exa.ai) neural search API.

Same port as TavilyWebSearch: returns WebResult with a `body` (page text) so the provenance
gate can verify a cited quote exists in the fetched page. Lazy httpx call; optional dep. Wrap
in a cassette for free replay. Auth via the `x-api-key` header; content requested inline so a
single call returns both the ranked results and their text.
"""
from __future__ import annotations

import os

from .websearch import WebResult

EXA_URL = "https://api.exa.ai/search"


class ExaWebSearch:
    def __init__(self, *, api_key: str | None = None, timeout: float = 10.0,
                 include_domains: list[str] | None = None, start_published_date: str = ""):
        self._api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self._timeout = timeout
        # Restrict results to a whitelist of trusted domains (the VERTICAL supplies these — e.g.
        # peer-reviewed journals, guideline bodies, gov/authoritative sources). Empty → open web.
        self._include_domains = [d for d in (include_domains or []) if d]
        # freshness: ISO date floor (Exa startPublishedDate) so "latest state" queries return recent
        # pages, not the most-linked older ones. "" = no floor (byte-identical to today).
        self._start_published_date = start_published_date

    async def search(self, query: str, *, max_results: int = 8) -> list[WebResult]:
        import httpx
        payload = {
            "query": query,
            "numResults": max_results,
            "type": "auto",                       # let Exa pick neural vs keyword
            # text: inline page body for provenance. highlights: QUERY-AWARE extracts pulled from
            # anywhere in the page — the discriminating paragraph of a long guideline surfaces even
            # when it sits beyond the text-budget truncation window.
            "contents": {"text": {"maxCharacters": 4000},
                         "highlights": {"numSentences": 5, "highlightsPerUrl": 2, "query": query}},
        }
        if self._include_domains:
            payload["includeDomains"] = self._include_domains   # trusted-sources-only
        if self._start_published_date:
            payload["startPublishedDate"] = self._start_published_date   # freshness floor
        headers = {"x-api-key": self._api_key, "content-type": "application/json"}
        # Exa is the ONLY web leg (no funded fallback provider): retry transient failures
        # (network / 5xx / 429) with a short backoff before giving up. A 4xx other than 429 is a
        # real request problem — no retry. Total added latency worst-case ~3.5s.
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
                    raise                      # genuine request error — retrying can't help
            except httpx.HTTPError as e:       # timeouts, connect errors — transient
                last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
        if data is None:
            raise last_err or RuntimeError("exa search failed")
        out: list[WebResult] = []
        for r in data.get("results", []):
            text = r.get("text") or ""
            out.append(WebResult(
                url=r.get("url", ""),
                title=r.get("title") or r.get("url", ""),
                snippet=(text[:400] if text else (r.get("summary") or "")),
                body=text or r.get("summary") or "",
                published=r.get("publishedDate") or None,
                highlights=tuple(h for h in (r.get("highlights") or []) if h and h.strip()),
            ))
        return out
