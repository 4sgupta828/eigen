"""Turn a podcast episode's SHOW NOTES into a timestamped CHAPTER-POINTER document.

WHY THIS EXISTS. Founder/investor shows do not publish transcripts. Measured on 2026-09-07 over the
last 60 episodes of seven such shows: `<podcast:transcript>` appears 0 times in 20VC, Lenny's, Invest
Like the Best, a16z, My First Million and Indie Hackers, and YouTube's caption endpoint returns zero
bytes without a signed token. What those publishers DO write is a timestamped chapter list — Lenny's
98% of episodes, Invest Like the Best 98%, My First Million 85%, 20VC 48%. A chapter is a real
lesson-level unit ("13:00 Is Series A the hardest stage at which to invest") and it deep-links to the
exact moment.

WHAT A CHAPTER IS NOT. A chapter title is written by the publisher's producer. It is NOT speech, so it
is NOT testimony and may never be quoted as if a founder said it. `source_kind="chapter_pointer"`
marks it as a POINTER: indexed so a question can find the moment, barred from the evidence path so no
claim can rest on it. The honest register is "listen from 13:00", never "the founder said".

ATTRIBUTION. A guest is bound only from the TITLE, never the body copy. The measurement that forced
this: an episode whose guest was one person bound to a different founder entirely, because the body
mentioned that founder and their company. A mention is stamped `mentions`, never `guest`.
"""
from __future__ import annotations

import html
import re

# "13:00 Title", "(00:02:16) Title", "[1:02:33] - Title" — an offset then the chapter's words.
_CHAPTER = re.compile(
    r"(?:^|[\s(\[])(\d{1,2}:\d{2}(?::\d{2})?)\s*[)\]]?\s*[-–—:|]*\s*([^\n<|]{6,110})")

# "20VC: Why X | Guest Name, CEO @ Acme" / "Jane Doe - Lessons - [Show]" / "… with Jane Doe"
_GUEST_HINTS = (
    re.compile(r"\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,2})"),
    re.compile(r"\bft\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,2})"),
    re.compile(r"\bfeaturing\s+([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,2})"),
    re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,2})\s*[-–—|]"),
)

MIN_CHAPTERS = 3          # fewer than this is a stray timestamp, not a chapter list
MAX_CHAPTERS = 60


def strip_html(raw: str) -> str:
    txt = html.unescape(html.unescape(raw or ""))
    txt = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", txt).strip()


def to_seconds(stamp: str) -> int:
    """'13:00' → 780, '01:02:33' → 3753. The unit the deep link needs."""
    parts = [int(p) for p in stamp.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def hhmmss(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def chapters(description: str) -> list[dict]:
    """Timestamped chapters, in order, deduplicated by offset. Empty when the notes have no list.

    A chapter must move FORWARD: publishers put stray times in prose ("we raised at 3:00 am"), so a
    non-increasing offset ends the list rather than corrupting it.
    """
    text = strip_html(description)
    out: list[dict] = []
    last = -1
    for stamp, raw_title in _CHAPTER.findall(text):
        try:
            secs = to_seconds(stamp)
        except (ValueError, IndexError):
            continue
        title = " ".join(raw_title.split()).strip(" -–—:•|")
        if len(title) < 6 or secs <= last or secs > 6 * 3600:
            continue
        # a chapter title is a phrase, not a paragraph of body copy
        if len(title) > 110 or title.count(".") > 2:
            continue
        out.append({"t_start": secs, "stamp": hhmmss(secs), "title": title})
        last = secs
        if len(out) >= MAX_CHAPTERS:
            break
    return out if len(out) >= MIN_CHAPTERS else []


def guest_from_title(title: str) -> str:
    """The guest as the TITLE names them, or "". Body copy is never consulted — a name in the notes
    is a mention, and binding a mention to the episode is how a quote lands on the wrong person."""
    t = " ".join((title or "").split())
    for pat in _GUEST_HINTS:
        m = pat.search(t)
        if m:
            name = " ".join(m.group(1).split())
            if 2 <= len(name.split()) <= 3:
                return name
    return ""


def episode_id(rec: dict) -> str:
    return str(rec.get("guid") or rec.get("id") or rec.get("link") or "").strip()


def deep_link(link: str, t_start: int) -> str:
    """The episode URL pointed at the moment. Sends the listener to the publisher, which is the whole
    point of a pointer: we hold the index, they hold the work."""
    if not link:
        return ""
    if t_start <= 0:
        return link
    sep = "&" if "?" in link else "?"
    return f"{link}{sep}t={int(t_start)}"


def _year(rec: dict) -> str:
    m = re.search(r"(19|20)\d{2}", str(rec.get("published") or ""))
    return m.group(0) if m else ""


def facets(rec: dict) -> dict:
    f = {
        "source_kind": "chapter_pointer",     # NOT evidence — a navigation aid (see module docstring)
        "entity_type": "episode",
        "publication": " ".join(str(rec.get("publication") or "").split()).strip(),
        "guest": guest_from_title(str(rec.get("title") or "")),
        "episode_url": str(rec.get("link") or "").strip(),
        "published": str(rec.get("published") or "").strip()[:64],
        "year": _year(rec),
    }
    return {k: v for k, v in f.items() if v}


def title(rec: dict) -> str:
    return " ".join(str(rec.get("title") or "").split()).strip()


def to_markdown(rec: dict) -> str:
    """One paragraph per chapter, each opening with its offset, so the kernel's paragraph splitter
    yields ONE BLOCK PER CHAPTER and every block carries the offset its deep link needs."""
    chs = chapters(str(rec.get("summary") or rec.get("content") or ""))
    show = " ".join(str(rec.get("publication") or "").split()).strip()
    guest = guest_from_title(title(rec))
    link = str(rec.get("link") or "").strip()
    published = str(rec.get("published") or "").strip()

    head = " — ".join(x for x in [show, title(rec)] if x)
    parts = [f"# {head}", ""]
    who = f"Guest: {guest}. " if guest else ""
    parts += [
        f"{who}{show or 'Podcast'}{', ' + published if published else ''}. "
        "Chapter pointers written by the publisher — where to listen, not what was said. "
        "Nothing here is a quotation.",
        "",
    ]
    if link:
        parts += [f"URL: {link}", ""]
    parts += ["## Chapters", ""]
    for ch in chs:
        parts += [f"[{ch['stamp']}] {ch['title']} — {deep_link(link, ch['t_start'])}", ""]
    return "\n".join(parts).strip() + "\n"
