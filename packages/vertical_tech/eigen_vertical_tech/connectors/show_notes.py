"""Show-notes connector — timestamped CHAPTER POINTERS from founder/investor podcasts (keyless RSS).

The companion to `podcast.py`, not a replacement. That connector ingests publisher TRANSCRIPTS and
skips any episode without one — the right contract for shows that ship transcripts (the Changelog
network, Latent Space). Founder and investor shows do not: measured on 2026-09-07 over the last 60
episodes of seven of them, `<podcast:transcript>` appeared zero times outside Acquired. What those
publishers do write is a timestamped chapter list, on 88-100% of episodes for the shows below.

So this connector ingests the chapter list and nothing else. Each chapter becomes one block carrying
its offset and a deep link to that moment. `source_kind="chapter_pointer"` grades to the "pointer"
tier, which is NOT EVIDENCE (`authority.is_evidence` is False for it): a chapter title says where to
listen, never what was said. Audio is never fetched, never transcribed, never scraped.

The allowlist is EVIDENCE, not taste: every feed URL was resolved through Apple's keyless podcast
search and kept only after measuring that the publisher actually writes chapters. A show that stops
writing them simply yields nothing, which is the failure mode we want.
"""
from __future__ import annotations

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import show_notes_doc
from ._feed import channel_meta, parse_feed
from ._http import HttpStrategy

# ── Curated show allowlist (chapter yield measured 2026-09-07, last 25 episodes) ──────────────────
SHOWS: list[str] = [
    "https://rss.libsyn.com/shows/61840/destinations/240976.xml",        # 20VC — Harry Stebbings (100%)
    "https://api.substack.com/feed/podcast/10845.rss",                   # Lenny's Podcast (100%)
    "https://feeds.megaphone.fm/CLS2859450455",                          # Invest Like the Best (100%)
    "https://rss.libsyn.com/shows/624860/destinations/5500155.xml",      # This Week in Startups (100%)
    "https://anchor.fm/s/e231a4ec/podcast/rss",                          # The Peel — Turner Novak (100%)
    "https://feeds.megaphone.fm/nopriors",                               # No Priors (100%)
    "https://rss2.flightcast.com/ordbkg8yojpehffas7vr7qpc.xml",          # The Startup Ideas Podcast (100%)
    "https://anchor.fm/s/f06c2370/podcast/rss",                          # BG2Pod — Gerstner/Gurley (96%)
    "https://rss2.flightcast.com/jlx9l0yn04wt3r710o051jtm.xml",          # The Logan Bartlett Show (92%)
    "https://feeds.megaphone.fm/HS2300184645",                           # My First Million (88%)
    "https://rss2.flightcast.com/xmsftuzjjykcmqwolaqn6mdn",              # The Diary of a CEO (64%)
    "https://feeds.megaphone.fm/YFL6537156961",                          # Equity — TechCrunch (60%)
    "https://rss.art19.com/how-i-built-this",                            # How I Built This (52%)
    "https://feeds.transistor.fm/acquired",                              # Acquired (28%)
    "https://feeds.megaphone.fm/DSLLC6297708582",                        # Founders — David Senra (20%)
    # Measured and REJECTED (0% chapters): Indie Hackers, Lightcone, the a16z show, Masters of Scale,
    # Modern CTO. They are not excluded on quality — there is simply nothing here to index.
]

TOTAL_CAP = 60          # cap episodes emitted per discovery pass


class ShowNotesConnector:
    key = "show_notes"

    def __init__(self, *, episodes: list[dict] | None = None, page_size: int = 20):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for r in (episodes or []):
            if show_notes_doc.episode_id(r):
                self._by_id[show_notes_doc.episode_id(r)] = r

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        """One EntityRef per episode THAT HAS a chapter list. Episodes without one are skipped, so
        the chapter-only contract is enforced at discovery — structurally, not by later filtering."""
        window = window or {}
        if self._by_id and not (window.get("query") or "").strip():
            items = list(self._by_id.values())
        else:
            limit = int(window.get("limit", self._page_size) or self._page_size)
            per = max(1, limit // max(1, len(SHOWS)))
            items = []
            for url in SHOWS:
                try:                                        # best-effort: one bad feed ≠ dead batch
                    raw = await self.fetch_strategy.fetch(url)
                    recs = parse_feed(raw)
                    cover = channel_meta(raw).get("image", "")
                except Exception:
                    continue
                kept = 0
                for r in recs:
                    if kept >= per:
                        break
                    if not show_notes_doc.episode_id(r):
                        continue
                    if not show_notes_doc.chapters(str(r.get("summary") or r.get("content") or "")):
                        continue                            # no chapter list → nothing to index
                    if cover and not r.get("image"):
                        r["image"] = cover                  # every episode of a show has its cover
                    items.append(r)
                    kept += 1
                if len(items) >= TOTAL_CAP:
                    break
            items = items[:TOTAL_CAP]
            for r in items:
                self._by_id[show_notes_doc.episode_id(r)] = r
        # The chapter-only contract is enforced HERE, on every path — fixtures included. An episode
        # with no chapter list has nothing to point at, so it never becomes an entity.
        return [EntityRef(source_key=self.key, native_id=show_notes_doc.episode_id(r),
                          title=show_notes_doc.title(r), facets=show_notes_doc.facets(r))
                for r in items
                if show_notes_doc.episode_id(r)
                and show_notes_doc.chapters(str(r.get("summary") or r.get("content") or ""))]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        r = self._by_id.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=show_notes_doc.facets(r) if r else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        r = self._by_id.get(doc.native_id) or {"id": doc.native_id, "title": doc.title}
        return show_notes_doc.to_markdown(r).encode("utf-8")
