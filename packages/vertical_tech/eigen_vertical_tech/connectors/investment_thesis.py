"""Investment-thesis connector — publicly published VC theses, market maps, and thesis-grade analysis.

The library behind "Discover theses": past, publicly-available startup investment theses — a VC firm's
"why we invested" / sector thesis, a market map, a request-for-startups, a thesis-grade breakdown of a
space. It is the SAME mechanics as `founder_essay` (keyless RSS/Atom, full-text only), but a distinct
corpus SLICE: `source_kind="investment_thesis"` (and `doc_kind="investment_thesis"`) so discovery search
can scope to theses, and the tier stays honest — a thesis is a named investor's INTERPRETATION and
STATED INTENT, never an established fact and never controlling (authority discipline unchanged).

Discipline, inherited from `founder_essay`:
- Full-text feeds only. A teaser/first-paragraph feed answers nothing; measure the median item body
  before adding a source (>= ~2,500 chars). Paywalled or feed-sharing-forbidden sources do NOT belong.
- `firm` / `kind` are metadata the source published about itself — read off, never judged (Rule 18).

NB the curated list below is the STARTING allowlist; every url must be full-text-verified (a quick
median-body probe) before it is included in a real prod ingest — same rule the essay feeds were held to.
"""
from __future__ import annotations

import logging

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import expert_feed_doc
from ._feed import parse_feed
from ._http import HttpStrategy

log = logging.getLogger(__name__)

# ── Curated allowlist: url → (firm/author, kind). VC-firm theses, market maps, thesis-grade analysis.
#    Deliberately COMPLEMENTS founder_essay (the investor-newsletter slice) with FIRM theses + maps. ───
THESES: dict[str, tuple[str, str]] = {
    "https://www.nfx.com/feed":                  ("NFX", "vc_thesis"),
    "https://a16z.com/feed/":                    ("Andreessen Horowitz", "vc_thesis"),
    "https://www.usv.com/rss":                   ("Union Square Ventures", "vc_thesis"),
    "https://abovethecrowd.com/feed/":           ("Bill Gurley (Benchmark)", "vc_thesis"),
    "https://www.contrary.com/feed":             ("Contrary Research", "market_map"),
    "https://tomtunguz.com/index.xml":           ("Theory Ventures", "vc_thesis"),
    # Measured/curate note: verify full text before ingest; drop any that ship teasers or 404
    # (Sequoia Perspectives, First Round Review, Bessemer Atlas were teaser/404 for founder_essay).
}

TOTAL_CAP = 60


class InvestmentThesisConnector:
    key = "investment_thesis"

    def __init__(self, *, items: list[dict] | None = None, page_size: int = 30):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for r in (items or []):
            if expert_feed_doc.item_id(r):
                self._by_id[expert_feed_doc.item_id(r)] = r

    @staticmethod
    def _facets(rec: dict, firm: str, kind: str) -> dict:
        f = dict(expert_feed_doc.facets(rec))
        # A thesis is its own corpus slice + tier: investment_thesis, never "essay".
        f["source_kind"] = "investment_thesis"
        f["doc_kind"] = "investment_thesis"
        f["entity_type"] = "thesis"
        if firm and not f.get("publication"):
            f["publication"] = firm
        if firm:
            f["firm"] = firm
        if kind:
            f["thesis_kind"] = kind          # vc_thesis | market_map | rfs | analysis
        return {k: v for k, v in f.items() if v}

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        window = window or {}
        if self._by_id and not (window.get("query") or "").strip():
            items = [(r, r.get("_firm", ""), r.get("_kind", "")) for r in self._by_id.values()]
        else:
            limit = int(window.get("limit", self._page_size) or self._page_size)
            per = max(1, limit // max(1, len(THESES)))
            items = []
            for url, (firm, kind) in THESES.items():
                try:                                       # best-effort: one bad feed ≠ dead batch
                    recs = parse_feed(await self.fetch_strategy.fetch(url))
                except Exception as e:                     # noqa: BLE001
                    log.warning("investment_thesis: %s failed: %s: %s", url, type(e).__name__, e)
                    continue
                for r in recs[:per]:
                    if expert_feed_doc.item_id(r):
                        r["_firm"], r["_kind"] = firm, kind
                        items.append((r, firm, kind))
                if len(items) >= TOTAL_CAP:
                    break
            items = items[:TOTAL_CAP]
            for r, _f, _k in items:
                self._by_id[expert_feed_doc.item_id(r)] = r
        return [EntityRef(source_key=self.key, native_id=expert_feed_doc.item_id(r),
                          title=expert_feed_doc.title(r), facets=self._facets(r, f, k))
                for r, f, k in items if expert_feed_doc.item_id(r)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        r = self._by_id.get(entity.native_id)
        facets = self._facets(r, r.get("_firm", ""), r.get("_kind", "")) if r else dict(entity.facets)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown", facets=facets,
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        r = self._by_id.get(doc.native_id) or {"id": doc.native_id, "title": doc.title}
        return expert_feed_doc.to_markdown(r).encode("utf-8")
