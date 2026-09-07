"""Founder/investor/operator essay connector — first-person startup writing (keyless RSS/Atom).

The sibling of `expert_feed.py`. That connector curates DEEP-TECH experts (Karpathy, Raschka, BAIR);
this one curates people writing about BUILDING AND FUNDING COMPANIES — what worked, what failed, what
they would do differently. Same mechanics, different vocabulary, so the tier is the same:
`source_kind="essay"` → `expert_analysis`, a named person's interpretation, never controlling.

Every feed here was kept only after measuring that it ships FULL TEXT (median item body >= 2,500
characters on 2026-09-07). A teaser feed is excluded: an index of first paragraphs answers nothing.
`voice_role` records what the writer IS — investor, founder, operator, analyst — because "a Series A
investor's view of Series A" and "a founder's view of Series A" are different evidence, and the
answer must be able to say which one it is holding.
"""
from __future__ import annotations

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import expert_feed_doc
from ._feed import parse_feed
from ._http import HttpStrategy

# ── Curated allowlist: url → (writer, role). Full-text verified; public feeds only. ───────────────
# Paywalled or feed-sharing-forbidden sources (Stratechery, SemiAnalysis) do NOT belong here.
VOICES: dict[str, tuple[str, str]] = {
    "https://www.notboring.co/feed":                    ("Packy McCormick", "investor"),
    "https://www.generalist.com/feed":                  ("Mario Gabriele", "analyst"),
    "https://www.lennysnewsletter.com/feed":            ("Lenny Rachitsky", "operator"),
    "https://avc.com/feed/":                            ("Fred Wilson", "investor"),
    "https://andrewchen.com/feed/":                     ("Andrew Chen", "investor"),
    "https://blog.eladgil.com/feed":                    ("Elad Gil", "investor"),
    "https://www.tomtunguz.com/index.xml":              ("Tomasz Tunguz", "investor"),
    "https://hunterwalk.com/feed/":                     ("Hunter Walk", "investor"),
    "https://www.ben-evans.com/benedictevans?format=rss": ("Benedict Evans", "analyst"),
    "https://www.saastr.com/feed/":                     ("Jason Lemkin", "founder"),
    "https://kellblog.com/feed/":                       ("Dave Kellogg", "operator"),
    "https://steveblank.com/feed/":                     ("Steve Blank", "founder"),
    "https://newsletter.weskao.com/feed":               ("Wes Kao", "operator"),
    "https://lethain.com/feeds/":                       ("Will Larson", "operator"),
    "https://www.platformer.news/rss/":                 ("Casey Newton", "analyst"),
    # Measured and REJECTED: Sequoia Perspectives and the YC blog ship teasers, not full text;
    # First Round Review, Bessemer Atlas and Both Sides of the Table returned 404 or an empty feed.
}

TOTAL_CAP = 60


class FounderEssayConnector:
    key = "founder_essay"

    def __init__(self, *, items: list[dict] | None = None, page_size: int = 30):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for r in (items or []):
            if expert_feed_doc.item_id(r):
                self._by_id[expert_feed_doc.item_id(r)] = r

    @staticmethod
    def _facets(rec: dict, writer: str, role: str) -> dict:
        f = dict(expert_feed_doc.facets(rec))
        # The feed's own byline wins; the curated writer fills in when a feed omits one (many do).
        if not f.get("author") and writer:
            f["author"] = writer
        if role:
            f["voice_role"] = role
        f["entity_type"] = "essay"
        return {k: v for k, v in f.items() if v}

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        window = window or {}
        if self._by_id and not (window.get("query") or "").strip():
            items = [(r, r.get("_writer", ""), r.get("_role", "")) for r in self._by_id.values()]
        else:
            limit = int(window.get("limit", self._page_size) or self._page_size)
            per = max(1, limit // max(1, len(VOICES)))
            items = []
            for url, (writer, role) in VOICES.items():
                try:                                       # best-effort: one bad feed ≠ dead batch
                    recs = parse_feed(await self.fetch_strategy.fetch(url))
                except Exception:
                    continue
                for r in recs[:per]:
                    if expert_feed_doc.item_id(r):
                        r["_writer"], r["_role"] = writer, role
                        items.append((r, writer, role))
                if len(items) >= TOTAL_CAP:
                    break
            items = items[:TOTAL_CAP]
            for r, _w, _ro in items:
                self._by_id[expert_feed_doc.item_id(r)] = r
        return [EntityRef(source_key=self.key, native_id=expert_feed_doc.item_id(r),
                          title=expert_feed_doc.title(r), facets=self._facets(r, w, ro))
                for r, w, ro in items if expert_feed_doc.item_id(r)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        r = self._by_id.get(entity.native_id)
        facets = self._facets(r, r.get("_writer", ""), r.get("_role", "")) if r else dict(entity.facets)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown", facets=facets,
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        r = self._by_id.get(doc.native_id) or {"id": doc.native_id, "title": doc.title}
        return expert_feed_doc.to_markdown(r).encode("utf-8")
