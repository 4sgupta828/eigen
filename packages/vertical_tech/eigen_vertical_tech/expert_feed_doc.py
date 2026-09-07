"""Turn an expert-newsletter/blog feed item (RSS/Atom) into a labeled EXPERT-ANALYSIS document + facets.

Expert newsletters and technical blogs are a NAMED expert's interpretation / foresight — the
product's most distinctive gap (curated tech-trend opinion). `source_kind="essay"` maps to a new
"expert_analysis" tier the orchestrator wires separately. It is INTERPRETATION, not a peer-reviewed
or primary fact: the byline/answer format must present it as a named expert's opinion, never as an
established finding. STRUCTURAL only (Rule 18): author/publication/year are metadata the feed
published about itself — read off, not judged.

A parsed feed item is a plain dict with (best-effort across RSS+Atom shapes):
    id / guid / link, title, author, publication, published (pubDate/updated string),
    summary (description), content (content:encoded / full content).
"""
from __future__ import annotations

import html
import re

from .feed_dates import iso_date

_MAX_BODY = 16000


def item_id(rec: dict) -> str:
    # Stable native id: prefer the feed's own guid/id, else the permalink.
    return str(rec.get("guid") or rec.get("id") or rec.get("link") or "").strip()


def title(rec: dict) -> str:
    return " ".join(str(rec.get("title") or "").split()).strip()


def _year(rec: dict) -> str:
    published = str(rec.get("published") or "")
    m = re.search(r"(19|20)\d{2}", published)   # structural: 4-digit year from pubDate/updated
    return m.group(0) if m else ""


_PIXEL = re.compile(r"(pixel|1x1|spacer|tracking|beacon|open\.gif|\.svg$)", re.I)


def lead_image(rec: dict) -> str:
    """The essay's own lead image, taken from the body the feed already sent.

    Cards without pictures next to cards with pictures read as broken, and every one of these feeds
    ships the artwork inside the post — so there is no reason to fetch the page for it. Tracking
    pixels are skipped: a 1x1 beacon is not a picture, and rendering one wastes a card's whole
    visual slot on nothing.
    """
    body = str(rec.get("content") or rec.get("summary") or "")
    for m in re.finditer(r"<img[^>]+src=[\"']([^\"']+)[\"']", body):
        src = m.group(1).strip()
        if src.startswith("http") and not _PIXEL.search(src):
            return src
    return ""


def facets(rec: dict) -> dict:
    f = {
        "source_kind": "essay",           # → NEW "expert_analysis" tier (wired separately)
        # The permalink belongs in the FACETS, not only in the document body: a card renders from
        # facets, so an essay whose link lives only in its prose reaches the reader with no way to
        # go and read it.
        "url": str(rec.get("link") or "").strip(),
        "image": str(rec.get("image") or "").strip() or lead_image(rec),
        "source_country": "global",
        "entity_type": "essay",
        "author": " ".join(str(rec.get("author") or "").split()).strip(),
        "publication": " ".join(str(rec.get("publication") or "").split()).strip(),
        "year": _year(rec),
        "published_at": iso_date(rec.get("published")),
    }
    return {k: v for k, v in f.items() if v}


def _strip_html(raw: str) -> str:
    """Tags out, entities decoded. Feeds double-escape often enough (&amp;#8217;) that one pass
    leaves "I&#8217;m" on the card, so unescape twice — the second pass is a no-op on clean text."""
    txt = html.unescape(html.unescape(raw or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt)).strip()


def to_markdown(rec: dict) -> str:
    author = " ".join(str(rec.get("author") or "").split()).strip()
    publication = " ".join(str(rec.get("publication") or "").split()).strip()
    published = str(rec.get("published") or "").strip()

    parts: list[str] = [f"# {title(rec)}", ""]

    # Byline: WHO said it, WHERE, WHEN — plus the explicit expert-opinion framing.
    lead = " — ".join(x for x in [publication, author] if x) or "Expert analysis"
    byline = lead + (f", {published}" if published else "")
    parts += [
        byline
        + "  (expert analysis / opinion — a named expert's interpretation, "
        + "not a peer-reviewed or primary fact)",
        "",
    ]

    if rec.get("link"):
        parts += [f"URL: {rec['link']}", ""]

    body = rec.get("content") or rec.get("summary") or rec.get("description") or ""
    if isinstance(body, str) and body.strip():
        clean = _strip_html(body)
        if clean:
            if len(clean) > _MAX_BODY:
                clean = clean[:_MAX_BODY].rstrip() + " …"
            parts += ["## Analysis", clean, ""]

    return "\n".join(parts).strip() + "\n"
