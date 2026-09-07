"""Search first-person content and shape it as MOMENTS. Pure functions plus one SQL builder.

A moment is what the user actually wants back: who said or wrote it, on what, when, and a link that
opens at the exact place. Two kinds reach the surface and they are not equal:

  essay    — the person's own words. Evidence of what they argue.
  chapter  — a publisher's timestamped marker. A POINTER: where to listen, never what was said.

The distinction is carried in the data (`source_kind`), not in a prompt, and `is_quotable` is the
single place that decides whether a moment may ever be shown inside quotation marks.

Keyword-first by design: `rs_block.tsv` is a generated column, so this works with no embedding
provider at all. Semantic ranking is added when vectors exist, never required for the mode to run.
"""
from __future__ import annotations

import re

VOICE_SOURCE_KEYS = ("founder_essay", "show_notes", "expert_feed", "podcast")

# Words that carry no signal in a question about startup lessons. Dropping them matters because the
# query is OR-ed: left in, "how" and "what" would match half the corpus and drown the real terms.
_STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from",
         "how", "what", "why", "when", "who", "do", "does", "did", "is", "are", "was", "were", "be",
         "i", "we", "you", "they", "it", "that", "this", "about", "after", "before", "my", "our"}


def terms(q: str) -> list[str]:
    """Query words, cleaned for `to_tsquery`. Punctuation out, stopwords out, duplicates out."""
    out: list[str] = []
    for raw in re.split(r"[^A-Za-z0-9']+", (q or "").lower()):
        w = raw.strip("'")
        if len(w) < 2 or w in _STOP or w in out:
            continue
        out.append(w)
    return out[:12]

# "[00:13:00] Is Series A the hardest stage — https://show.fm/ep?t=780"
_CHAPTER_LINE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.+?)(?:\s+—\s+(https?://\S+))?$")


def is_quotable(source_kind: str) -> bool:
    """False for a chapter pointer. A producer's chapter title is not speech, so quoting it would
    manufacture a statement nobody made. Everything else may be quoted with attribution."""
    return (source_kind or "").lower() != "chapter_pointer"


def kind_of(source_kind: str, source_key: str) -> str:
    sk = (source_kind or "").lower()
    if sk == "chapter_pointer" or source_key == "show_notes":
        return "chapter"
    if source_key == "podcast":
        return "transcript"
    return "essay"


def seconds_of(stamp: str) -> int:
    try:
        h, m, s = (int(p) for p in stamp.split(":"))
    except ValueError:
        return 0
    return h * 3600 + m * 60 + s


def moment(row: dict) -> dict:
    """One `rs_block` row → a card. Never invents a link, a speaker or a timestamp."""
    facets = row.get("facets") or {}
    text = (row.get("text") or "").strip()
    source_kind = str(facets.get("source_kind") or "")
    kind = kind_of(source_kind, str(row.get("source_key") or ""))

    t_start, url, body = 0, str(facets.get("episode_url") or ""), text
    if kind == "chapter":
        m = _CHAPTER_LINE.match(text)
        if m:
            t_start = seconds_of(m.group(1))
            # the stored line is "[hh:mm:ss] Title — <url>"; when the episode had no link the
            # separator is still there, and "Sales agent —" is not a chapter title anyone wrote
            body = m.group(2).strip().rstrip(" -–—")
            url = m.group(3) or url
    if kind != "chapter":
        # the passage that matched, when the query produced one; else the block's opening
        body = (row.get("snippet") or body or "").strip() or body
    speaker = str(facets.get("guest") or facets.get("author") or "")
    return {
        "id": f"{row.get('document_id')}::{row.get('block_id')}",
        "kind": kind,
        "quotable": is_quotable(source_kind),
        "text": body,
        "title": str(row.get("document_title") or ""),
        "show": str(facets.get("publication") or ""),
        "speaker": speaker,
        "role": str(facets.get("voice_role") or ("guest" if kind == "chapter" else "")),
        "published": str(facets.get("published") or facets.get("year") or ""),
        "url": url,
        "t_start": t_start,
        "company_id": str(facets.get("company_id") or ""),
        # The register the UI must print. A pointer is never presented as something anyone said.
        "register": ("Chapter marker written by the publisher — listen from this point"
                     if kind == "chapter" else "First-person account, attributed to its author"),
    }


def build_query(*, q: str, kinds: tuple[str, ...] = (), company_id: str = "", speaker: str = "",
                limit: int = 30, table: str = "rs_block", per_document: bool = False) -> tuple[str, list]:
    """Keyword search over the voice corpus. Returns (sql, params) — no I/O, so it is testable.

    An empty `q` is legitimate ("show me what founders are saying"): it degrades to the newest rows
    rather than to an error, because a mode that returns nothing when the box is empty reads broken.
    """
    # Boilerplate is excluded everywhere. Many newsletter feeds repeat a sidebar of post titles in
    # every item's body, which otherwise floods a search with the same block five times over.
    where = ["source_key = ANY($1)", "NOT (facets ? 'boilerplate')"]
    params: list = [list(VOICE_SOURCE_KEYS)]
    n = 1

    if kinds:
        by_kind = {"chapter": ["show_notes"], "essay": ["founder_essay", "expert_feed"],
                   "transcript": ["podcast"]}
        keys: list[str] = []
        for k in kinds:
            keys += by_kind.get(k, [])
        # An unrecognised kind must narrow to nothing, never widen back to everything: silently
        # returning the whole corpus for a typo'd filter is a lie about what the filter did.
        params[0] = keys
    if company_id:
        n += 1
        where.append(f"facets->>'company_id' = ${n}")
        params.append(company_id)
    if speaker:
        n += 1
        where.append(f"(facets->>'guest' ILIKE ${n} OR facets->>'author' ILIKE ${n})")
        params.append(speaker)

    q_terms = terms(q)
    if q_terms:
        # OR, not AND. `plainto_tsquery` requires EVERY word, so "pivot after a failed round"
        # returned one block in the whole corpus — a question phrased as a sentence found nothing.
        # OR-ing the terms and letting ts_rank order the result is what the kernel's own retrieval
        # does, and it is the difference between a mode that answers and a mode that shrugs.
        n += 1
        params.append(" | ".join(q_terms))
        where.append(f"tsv @@ to_tsquery('english', ${n})")
        # Normalisation 1 divides the rank by 1 + log(length). Without it a 4,000-character essay
        # that mentions a word twice outranks a chapter titled exactly that word, and the podcast
        # moments — the thing this mode exists to surface — never appear at all.
        rank = f"ts_rank(tsv, to_tsquery('english', ${n}), 1)"
        order = f"{rank} DESC, created_at DESC NULLS LAST"
        # An essay block can be thousands of characters, so the head of it is rarely the part that
        # answered the question. ts_headline returns the passage that actually matched.
        snippet = (f"ts_headline('english', text, to_tsquery('english', ${n}), "
                   f"'MaxWords=48, MinWords=20, ShortWord=3, MaxFragments=1, StartSel=\u00ab, StopSel=\u00bb')")
    else:
        rank = "0.0"
        order = "created_at DESC NULLS LAST"
        snippet = "left(text, 320)"

    n += 1
    params.append(int(max(1, min(limit, 100))))
    cols = (f"document_id, block_id, text, document_title, source_key, facets, "
            f"{rank} AS score, {snippet} AS snippet")
    if per_document:
        # One row per EPISODE. Without this a company's strip fills with the first eight chapters of
        # one episode ("00:00 Intro", "02:00 Early days") and every other episode is pushed out.
        sql = (f"SELECT * FROM (SELECT DISTINCT ON (document_id) {cols} "
               f"FROM {table} WHERE {' AND '.join(where)} ORDER BY document_id, {order}) s "
               f"ORDER BY score DESC, document_id LIMIT ${n}")
    else:
        sql = f"SELECT {cols} FROM {table} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ${n}"
    return sql, params


def dedupe(moments: list[dict], *, per_document: int = 2, per_source: int = 3,
           limit: int = 30) -> list[dict]:
    """Keep a result set readable: no repeated text, and no one voice taking it over.

    Ranking alone does not do this. One essay split into blocks can hold the top five slots with
    near-identical passages, and the most prolific writer in the corpus can hold the rest — either
    way it reads as though the corpus knows one thing. Two passes over the same ranked list, so the
    order is still the ranking's; only the crowding is removed.
    """
    seen_text: set[str] = set()
    per_doc: dict[str, int] = {}
    per_pub: dict[str, int] = {}
    out: list[dict] = []
    spill: list[dict] = []
    for m in moments:
        key = " ".join((m.get("text") or "").lower().split())[:160]
        doc = str(m.get("id", "")).split("::", 1)[0]
        pub = (m.get("speaker") or m.get("show") or "").lower()
        if not key or key in seen_text or per_doc.get(doc, 0) >= per_document:
            continue
        seen_text.add(key)
        per_doc[doc] = per_doc.get(doc, 0) + 1
        if pub and per_pub.get(pub, 0) >= per_source:
            spill.append(m)          # held back, not discarded: it still fills a thin result set
            continue
        per_pub[pub] = per_pub.get(pub, 0) + 1
        out.append(m)
        if len(out) >= limit:
            return out
    return (out + spill)[:limit]
