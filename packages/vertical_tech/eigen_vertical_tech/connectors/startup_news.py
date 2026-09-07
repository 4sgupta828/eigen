"""Startup-activity press connector — funding, launches and acquisitions, keyless RSS.

Startup activity is reported before it is filed, and often it is only ever reported: a seed round
covered by Crunchbase News may never produce a Form D we can find, and a launch produces no filing at
all. So the press leg is how the corpus learns that something HAPPENED — and the tier keeps it in its
place, because reporting a round is not attesting one.

Every feed was measured on 2026-09-07 and kept only if it ships usable article text (median item
body ≥ 200 characters). Feeds that ship a one-line teaser are excluded: an index of headlines with
no reporting under them cannot answer a question, and TechCrunch's own feeds fall in that bucket at
roughly 130 characters an item.

Geography is deliberate: Europe, India and the wider world are represented as well as the US,
because a US-only press leg quietly makes the whole index US-only.
"""
from __future__ import annotations

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import press_doc
from ._feed import parse_feed
from ._http import HttpStrategy

# ── Curated allowlist: url → (publication, beat). Median body length measured, in comments. ──────
FEEDS: dict[str, tuple[str, str]] = {
    "https://news.crunchbase.com/feed/":        ("Crunchbase News", "venture"),        # 4,467
    "https://www.eu-startups.com/feed/":        ("EU-Startups", "europe"),             # 4,230
    "https://tech.eu/feed/":                    ("Tech.eu", "europe"),                 # 2,435
    "https://www.alleywatch.com/feed/":         ("AlleyWatch", "venture"),             # 3,473
    "https://inc42.com/feed/":                  ("Inc42", "india"),                    # 3,708
    "https://yourstory.com/feed":               ("YourStory", "india"),                # 3,770
    "https://api.axios.com/feed/":              ("Axios", "business"),                 # 3,364
    "https://fortune.com/feed/fortune-feeds/?id=3230629": ("Fortune", "business"),     # 6,873
    "https://feeds.businessinsider.com/custom/all": ("Business Insider", "business"),  # 5,179
    "https://www.pymnts.com/feed/":             ("PYMNTS", "fintech"),                 # 2,680
    "https://siliconangle.com/feed/":           ("SiliconANGLE", "enterprise"),        # 490
    "https://techstartups.com/feed/":           ("TechStartups", "venture"),           # 403
    "https://www.techmeme.com/feed.xml":        ("Techmeme", "aggregator"),            # 339
    "https://www.theverge.com/rss/index.xml":   ("The Verge", "consumer"),             # 699
    # Measured and REJECTED — teaser-only or unreachable: TechCrunch and its venture/startups
    # categories (~130 chars an item), Sifted (empty bodies), Startup Daily, Tech in Asia, Rest of
    # World, FinSMEs (403), VentureBeat (429), Axios Pro Rata and Entrackr (404).
}

TOTAL_CAP = 120


class StartupNewsConnector:
    key = "startup_news"

    def __init__(self, *, items: list[dict] | None = None, page_size: int = 40):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for r in (items or []):
            if press_doc.item_id(r):
                self._by_id[press_doc.item_id(r)] = r

    @staticmethod
    def _select(query: str) -> list[str]:
        """Narrow the fetch fan-out by a beat when the query names one; otherwise fetch everything.

        Relevance is retrieval's job. This only avoids pulling India and fintech feeds when the
        caller explicitly asked for, say, europe — and it never returns an empty list, so a stray
        query cannot silently starve the lane.
        """
        q = (query or "").lower()
        hit = [u for u, (_pub, beat) in FEEDS.items() if beat in q]
        return hit or list(FEEDS)

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        window = window or {}
        query = (window.get("query") or "").strip()
        if self._by_id and not query:
            items = list(self._by_id.values())
        else:
            limit = int(window.get("limit", self._page_size) or self._page_size)
            urls = self._select(query)
            per = max(1, limit // max(1, len(urls)))
            items = []
            for url in urls:
                pub, _beat = FEEDS.get(url, ("", ""))
                try:                                  # best-effort: one dead feed ≠ dead batch
                    recs = parse_feed(await self.fetch_strategy.fetch(url))
                except Exception:
                    continue
                for r in recs[:per]:
                    if not press_doc.item_id(r):
                        continue
                    if pub:
                        r["publication"] = pub        # the feed's own title is often branding noise
                    items.append(r)
                if len(items) >= TOTAL_CAP:
                    break
            items = items[:TOTAL_CAP]
            for r in items:
                self._by_id[press_doc.item_id(r)] = r
        return [EntityRef(source_key=self.key, native_id=press_doc.item_id(r),
                          title=press_doc.title(r), facets=press_doc.facets(r))
                for r in items if press_doc.item_id(r)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        r = self._by_id.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=press_doc.facets(r) if r else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        r = self._by_id.get(doc.native_id) or {"id": doc.native_id, "title": doc.title}
        return press_doc.to_markdown(r).encode("utf-8")
