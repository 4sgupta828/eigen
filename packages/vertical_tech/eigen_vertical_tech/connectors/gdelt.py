"""GDELT connector — global news signal (GDELT DOC 2.0 API, free, no key).

discover_entities({"query": company/topic, "limit": N, "timespan": "3m"}) → recent articles about the
subject, RESTRICTED to reputable outlets (a diligence corpus shouldn't ingest random blogs) → one
EntityRef per article. fetch_artifact → a headline-level markdown doc (GDELT returns metadata, not
bodies). GDELT asks for ≤1 request / 5s, so this connector paces with a long backoff. Tests inject
`articles` for offline runs.
"""
from __future__ import annotations

import json

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import news_doc
from ._http import HttpStrategy

API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Reputable tech/business outlets — keeps the news layer diligence-grade (analysis tier), not noise.
_DOMAINS = ["reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "techcrunch.com",
            "theinformation.com", "theverge.com", "arstechnica.com", "wired.com", "forbes.com",
            "axios.com", "businessinsider.com", "nytimes.com"]


class GdeltConnector:
    key = "gdelt"

    def __init__(self, *, articles: list[dict] | None = None, page_size: int = 20):
        # GDELT: ≤1 req / 5s → patient pacing (base 6s, more retries) so a burst of jobs backs off
        # instead of 429ing rather than failing the job.
        self.fetch_strategy = HttpStrategy(base_delay=6.0, max_retries=5)
        self._page_size = page_size
        self._by_url: dict[str, dict] = {}
        for a in (articles or []):
            self._by_url[news_doc.article_url(a)] = a

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        if not (window or {}).get("query") and self._by_url:
            arts = list(self._by_url.values())
        else:
            import urllib.parse
            q = (window or {}).get("query", "").strip() or "artificial intelligence"
            limit = min(75, int((window or {}).get("limit", self._page_size)))
            span = (window or {}).get("timespan", "3m")
            dom = " OR ".join(f"domainis:{d}" for d in _DOMAINS)
            full = f"({q}) ({dom})"
            url = (f"{API}?query={urllib.parse.quote(full)}&mode=ArtList&format=json"
                   f"&maxrecords={limit}&sort=DateDesc&timespan={span}")
            try:
                arts = (json.loads(await self.fetch_strategy.fetch(url)).get("articles") or [])[:limit]
            except Exception:   # noqa: BLE001 — GDELT can return non-JSON on throttle; fail soft
                arts = []
            for a in arts:
                self._by_url[news_doc.article_url(a)] = a
        return [EntityRef(source_key=self.key, native_id=news_doc.article_url(a),
                          title=news_doc.title(a), facets=news_doc.facets(a))
                for a in arts if news_doc.article_url(a)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        a = self._by_url.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=news_doc.facets(a) if a else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        a = self._by_url.get(doc.native_id) or {"url": doc.native_id, "title": doc.title}
        return news_doc.to_markdown(a).encode("utf-8")
