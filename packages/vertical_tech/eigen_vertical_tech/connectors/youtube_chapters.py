"""YouTube connector — timestamped CHAPTER POINTERS from founder/investor channels (keyless).

WHY THIS EXISTS, having first concluded YouTube was closed. YouTube's caption endpoint is gated:
`captionTracks` is still in the watch page, but every format of its `baseUrl` returns zero bytes
without a signed token, so transcripts are genuinely unavailable and we do not scrape them. That is
a fact about CAPTIONS, and it says nothing about DESCRIPTIONS — which are public in the keyless
channel feed and, on these channels, carry the creator's own timestamped chapter list. Measured
2026-09-07 over the newest 15 videos per channel: BG2 14, a16z 13, Greg Isenberg 13, Y Combinator
12, The Logan Bartlett Show 12.

The unit is identical to a podcast's show notes — a creator-written marker and an offset — so it
grades the same way: `source_kind="chapter_pointer"`, tier "pointer", never evidence, never quoted.
A chapter deep-links to `watch?v=<id>&t=<seconds>`, which opens the creator's own video at that
moment. No audio, no video and no captions are ever fetched.

The channel feed is `https://www.youtube.com/feeds/videos.xml?channel_id=<UC…>` — public, keyless,
newest 15 videos. Channel IDs were resolved once from each channel's public page and are pinned
here, because a handle can be reassigned while an ID cannot.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import show_notes_doc
from ._http import HttpStrategy

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="

# ── Curated channels (chapter yield measured 2026-09-07, newest 15 videos) ────────────────────────
CHANNELS: dict[str, str] = {
    "UC-yRDvpR99LUc5l7i7jLzew": "BG2Pod",                    # 14/15
    "UC9cn0TuPq4dnbTY-CBsm8XA": "a16z",                      # 13/15
    "UCPjNBjflYl0-HQtUvOx0Ibw": "Greg Isenberg",             # 13/15
    "UCcefcZRL2oaA_uBNeo5UOWg": "Y Combinator",              # 12/15 — Lightcone, founder talks
    "UCugS0jD5IAdoqzjaNYzns7w": "The Logan Bartlett Show",   # 12/15
    "UCf0PBRjhf0rF8fWBIxTuoWA": "20VC",                      # 4/15
    "UCyaN6mg5u8Cjy2ZI4ikWaug": "My First Million",          # 3/15
    "UCSI7h9hydQ40K5MJHnCrQvw": "No Priors",                 # 3/15
    "UCwOILzAcxK5CM2M7oRBuWSg": "SaaStr",                    # 3/15
    "UC6t1O76G0jYXOAoYCm153dA": "Lenny's Podcast",           # 1/15
    "UCyFqFYfTW2VoIQKylJ04Rtw": "Acquired",                  # 1/15
    # Measured and dropped: This Week in Startups and All-In write no chapters on YouTube.
}

TOTAL_CAP = 90


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_channel(raw: bytes, channel_name: str = "") -> list[dict]:
    """Atom entries → the record shape `show_notes_doc` already understands.

    The description lives at `media:group/media:description`, NOT at the entry's own `description`,
    which is why an earlier probe of these feeds reported them empty and nearly cost us the source.
    """
    root = ET.fromstring(raw)
    feed_title = ""
    for ch in root:
        if _local(ch.tag) == "title" and ch.text:
            feed_title = ch.text.strip()
            break
    out: list[dict] = []
    for e in root:
        if _local(e.tag) != "entry":
            continue
        rec: dict = {"publication": channel_name or feed_title}
        vid = ""
        for ch in e:
            n = _local(ch.tag)
            if n == "videoId" and ch.text:
                vid = ch.text.strip()
            elif n == "title" and ch.text:
                rec["title"] = ch.text.strip()
            elif n == "published" and ch.text:
                rec["published"] = ch.text.strip()
            elif n == "group":
                for g in ch:
                    if _local(g.tag) == "description" and g.text:
                        rec["summary"] = g.text
        if not vid:
            continue
        rec["guid"] = f"youtube:{vid}"
        rec["link"] = f"https://www.youtube.com/watch?v={vid}"
        out.append(rec)
    return out


class YoutubeChaptersConnector:
    key = "youtube_chapters"

    def __init__(self, *, videos: list[dict] | None = None, page_size: int = 15):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for r in (videos or []):
            if show_notes_doc.episode_id(r):
                self._by_id[show_notes_doc.episode_id(r)] = r

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        window = window or {}
        if self._by_id and not (window.get("query") or "").strip():
            items = list(self._by_id.values())
        else:
            limit = int(window.get("limit", self._page_size) or self._page_size)
            per = max(1, limit // max(1, len(CHANNELS)))
            items = []
            for cid, name in CHANNELS.items():
                try:                                # best-effort: one dead channel ≠ dead batch
                    recs = parse_channel(await self.fetch_strategy.fetch(FEED + cid), name)
                except Exception:
                    continue
                kept = 0
                for r in recs:
                    if kept >= per:
                        break
                    if show_notes_doc.chapters(str(r.get("summary") or "")):
                        items.append(r)
                        kept += 1
                if len(items) >= TOTAL_CAP:
                    break
            items = items[:TOTAL_CAP]
            for r in items:
                self._by_id[show_notes_doc.episode_id(r)] = r
        # the chapter-only contract, enforced here on every path exactly as the podcast side does
        return [EntityRef(source_key=self.key, native_id=show_notes_doc.episode_id(r),
                          title=show_notes_doc.title(r), facets=show_notes_doc.facets(r))
                for r in items
                if show_notes_doc.episode_id(r) and show_notes_doc.chapters(str(r.get("summary") or ""))]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        r = self._by_id.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=show_notes_doc.facets(r) if r else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        r = self._by_id.get(doc.native_id) or {"id": doc.native_id, "title": doc.title}
        return show_notes_doc.to_markdown(r).encode("utf-8")
