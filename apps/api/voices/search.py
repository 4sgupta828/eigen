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

from eigen_vertical_tech.show_notes_doc import deep_link

# The mode's sources. The kernel's older `podcast` connector is NOT here: it holds publisher
# transcripts of deep-tech ENGINEERING shows (the Changelog network, Latent Space), which are
# first-person practitioner talk but not founders and investors on building companies. Their
# fragments — "[00:28:20.11] And these..." with no show or speaker on the card — diluted every
# result. They stay in the corpus for research answers; they are simply not this mode's material.
VOICE_SOURCE_KEYS = ("founder_essay", "show_notes", "youtube_chapters", "expert_feed", "eng_blog")

# Words that carry no signal in a question about startup lessons. Dropping them matters because the
# query is OR-ed: left in, "how" and "what" would match half the corpus and drown the real terms.
_STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from",
         "how", "what", "why", "when", "who", "do", "does", "did", "is", "are", "was", "were", "be",
         "i", "we", "you", "they", "it", "that", "this", "about", "after", "before", "my", "our"}


# Words that are near-universal in a corpus that is entirely about startups. They carry no signal
# here and, OR-ed into a query, they drown the words that do: "Physical AI startups building Robotic
# systems" matched every long essay containing "building" or "systems" and returned nothing about
# robotics. Dropped only when something more specific survives.
_GENERIC = {"startup", "startups", "company", "companies", "business", "businesses", "founder",
            "founders", "building", "build", "builds", "tech", "technology", "thing", "things",
            "people", "team", "teams", "work", "working", "system", "systems", "stuff"}


def terms(q: str) -> list[str]:
    """Query words, cleaned for `to_tsquery`. Punctuation out, stopwords out, duplicates out."""
    out: list[str] = []
    for raw in re.split(r"[^A-Za-z0-9']+", (q or "").lower()):
        w = raw.strip("'")
        if len(w) < 2 or w in _STOP or w in out:
            continue
        out.append(w)
    specific = [w for w in out if w not in _GENERIC]
    # …unless the whole question is made of them ("what do founders say"), in which case they are
    # all we have and dropping them would leave nothing to search.
    return (specific or out)[:12]


def tsqueries(words: list[str]) -> list[tuple[str, str]]:
    """The query ladder, strictest first: [(label, tsquery)].

    Strict-then-relax, the same discipline the startup search uses. Answering a six-word question by
    OR-ing all six words is not a search, it is a guess: the longest document containing the most
    common word wins. So ask for ALL the words, then for any TWO of them, and only then for any one
    — and say which rung answered.
    """
    ws = [w for w in words if w]
    if not ws:
        return []
    out = [("all words", " & ".join(ws))]
    if len(ws) > 2:
        # any two of the most distinctive words; longer words are the more distinctive ones here
        top = sorted(ws, key=len, reverse=True)[:5]
        pairs = [f"{a} & {b}" for i, a in enumerate(top) for b in top[i + 1:]]
        if pairs:
            out.append(("most words", " | ".join(pairs)))
    if len(ws) > 1:
        out.append(("any word", " | ".join(ws)))
    return out

# "[00:13:00] Is Series A the hardest stage — https://show.fm/ep?t=780"
_CHAPTER_LINE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.+?)(?:\s+—\s+(https?://\S+))?$")


def is_pointer(kind: str) -> bool:
    """Podcast and video moments are chapter pointers: navigation, never speech."""
    return kind in ("podcast", "video")


def is_quotable(source_kind: str) -> bool:
    """False for a chapter pointer. A producer's chapter title is not speech, so quoting it would
    manufacture a statement nobody made. Everything else may be quoted with attribution."""
    return (source_kind or "").lower() != "chapter_pointer"


def kind_of(source_kind: str, source_key: str) -> str:
    """A podcast and a video are not the same object to a reader: one is listened to on the move,
    the other watched. They share the chapter MECHANICS and differ in how you consume them, so the
    card kind separates them even though the tier and the gates are identical."""
    if source_key == "youtube_chapters":
        return "video"
    if source_key == "show_notes" or (source_kind or "").lower() == "chapter_pointer":
        return "podcast"
    if source_key == "podcast":
        return "transcript"
    # A company engineering blog is the same ACT as a founder essay — someone who built the thing
    # writing about it — but not the same authority: it is the company describing itself, which the
    # tier already grades below independent analysis. Falling through to "essay" would have filed it
    # beside Fred Wilson and quietly erased that difference, so it gets its own kind.
    if source_key == "eng_blog" or (source_kind or "").lower() == "corp_eng":
        return "blog"
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

    t_start, url, body = 0, str(facets.get("episode_url") or facets.get("url") or ""), text
    if is_pointer(kind):
        m = _CHAPTER_LINE.match(text)
        if m:
            t_start = seconds_of(m.group(1))
            # the stored line is "[hh:mm:ss] Title — <url>"; when the episode had no link the
            # separator is still there, and "Sales agent —" is not a chapter title anyone wrote
            body = m.group(2).strip().rstrip(" -–—")
            # the line's own link when it has one; otherwise point the episode's address at this
            # moment, so a show that ships only an audio enclosure still opens at the right second
            url = m.group(3) or deep_link(url, t_start)
    if not is_pointer(kind):
        # the passage that matched, when the query produced one; else the block's opening
        body = (row.get("snippet") or body or "").strip() or body
    speaker = str(facets.get("guest") or facets.get("author") or "")
    # How this moment can be PLAYED, if at all. A YouTube video embeds and starts at the second; an
    # audio enclosure plays inline from the same offset; everything else is a link out.
    vid, audio = str(facets.get("video_id") or ""), str(facets.get("audio_url") or "")
    if is_pointer(kind) and vid:
        media = {"kind": "youtube", "id": vid, "t": t_start}
    elif is_pointer(kind) and audio:
        media = {"kind": "audio", "url": audio, "t": t_start}
    else:
        media = {}
    return {
        "id": f"{row.get('document_id')}::{row.get('block_id')}",
        "kind": kind,
        "quotable": is_quotable(source_kind),
        "text": body,
        "title": str(row.get("document_title") or ""),
        "show": str(facets.get("publication") or ""),
        "speaker": speaker,
        "role": str(facets.get("voice_role") or ("guest" if is_pointer(kind) else "")),
        # The exact date if we have one, else the feed's own string. NEVER the bare year: a card
        # rendering "2026" as a date showed "31 Dec 2025" to a reader west of UTC, which contradicted
        # the very window that had selected it.
        "published": str(facets.get("published_at") or facets.get("published") or ""),
        "year": str(facets.get("year") or ""),
        "url": url,
        "t_start": t_start,
        "company_id": str(facets.get("company_id") or ""),
        # how strongly this episode tied the guest to a company we index — the binder's own verdict,
        # reused here to decide whether a profile link is safe to print
        "bind_basis": str(facets.get("bind_basis") or ""),
        "image": str(facets.get("image") or ""),
        # Whose engineering account this is, as somewhere you can go. For a self-reported source the
        # publisher is not decoration — it is the thing that qualifies the claim.
        "site": str(facets.get("site") or ""),
        "views": int(facets["views"]) if str(facets.get("views") or "").isdigit() else 0,
        "published_at": str(facets.get("published_at") or ""),
        "media": media,
        # The register the UI must print. A pointer is never presented as something anyone said.
        "register": (("Chapter marker written by the publisher — "
                      + ("watch from this point" if kind == "video" else "listen from this point"))
                     if is_pointer(kind) else "First-person account, attributed to its author"),
    }


def build_query(*, q: str, kinds: tuple[str, ...] = (), company_id: str = "", speaker: str = "",
                limit: int = 30, table: str = "rs_block", per_document: bool = False,
                since: str = "", order: str = "recent", tsquery: str = "") -> tuple[str, list]:
    """Keyword search over the voice corpus. Returns (sql, params) — no I/O, so it is testable.

    An empty `q` is a BROWSE, not a failed search: "show me what founders are saying". It used to
    fall back to `created_at`, which is when WE ingested a row — an ordering that means nothing to a
    reader and put whatever the last job touched at the top. A browse now orders by the piece's own
    PUBLICATION date (`published_at`, ISO text, so it sorts), optionally within a window, and can
    order by the platform's own view count where one exists.
    """
    # Boilerplate is excluded everywhere. Many newsletter feeds repeat a sidebar of post titles in
    # every item's body, which otherwise floods a search with the same block five times over.
    where = [
        "source_key = ANY($1)",
        "NOT (facets ? 'boilerplate')",
        # A document carries a header — a byline line and a "URL: …" line — and the splitter indexes
        # those as ordinary paragraphs. They surfaced as moments reading "20VC, 2026-09-07T13:59:48".
        # A pointer's real content always opens with its timestamp, so anything else in those
        # sources is furniture.
        "text NOT LIKE 'URL: %'",
        "(source_key NOT IN ('show_notes','youtube_chapters') OR text LIKE '[%')",
        # Each document builder writes a byline paragraph carrying its register in parentheses. The
        # splitter indexes it like any other paragraph, so it surfaced as a moment reading
        # "Lenny's Newsletter — Claire Vo, Mon, 07 Sep 2026". Excluded by the register phrase the
        # builder itself wrote, which is the one thing every byline reliably contains.
        "text NOT LIKE '%(expert analysis / opinion%'",
        "text NOT LIKE '%(press report — reported, not audited%'",
        # eng_blog_doc writes the same shape of byline, carrying its own register phrase. Without
        # this an engineering-blog card would open with "Stripe — Jane Doe, 2026-09-01" instead of
        # the engineering itself.
        "text NOT LIKE '%(company engineering blog — a self-reported%'",
        # A stub is not a moment. Feeds truncate, and a body that survives stripping as "…" or a
        # half-sentence renders a card with a headline, a link and nothing to read. Chapter pointers
        # are legitimately short ("[00:01:02] Intro"), and already have their own '[' format guard,
        # so the minimum applies only to prose sources.
        "(source_key IN ('show_notes','youtube_chapters') OR length(btrim(text)) >= 30)",
        "text NOT LIKE '%Chapter pointers written by the publisher%'",
    ]
    params: list = [list(VOICE_SOURCE_KEYS)]
    n = 1

    if kinds:
        by_kind = {"podcast": ["show_notes"], "video": ["youtube_chapters"],
                   "chapter": ["show_notes", "youtube_chapters"],      # kept: "both kinds of moment"
                   "essay": ["founder_essay", "expert_feed"],
                   "blog": ["eng_blog"]}
        keys: list[str] = []
        for k in kinds:
            keys += by_kind.get(k, [])
        # An unrecognised kind must narrow to nothing, never widen back to everything: silently
        # returning the whole corpus for a typo'd filter is a lie about what the filter did.
        params[0] = keys
    if since:
        # a published_at we could not parse is left out of a window rather than dated to today
        n += 1
        where.append(f"(facets->>'published_at') >= ${n}")
        params.append(since)
    if order == "watched":
        n += 1
        where.append(f"(facets->>'views') ~ ${n}")
        params.append(r"^\d+$")
    if order == "guest":
        # Podcasts publish no engagement number, so "most watched" can never rank them. What a
        # founder or investor actually wants from a podcast feed is the INTERVIEWS — an episode with
        # a named guest — rather than the weekly news round-ups that make up much of these shows.
        # It is a property of the episode, not a popularity guess we would be inventing.
        where.append("facets ? 'guest'")
    if company_id:
        n += 1
        where.append(f"facets->>'company_id' = ${n}")
        params.append(company_id)
    if speaker:
        n += 1
        where.append(f"(facets->>'guest' ILIKE ${n} OR facets->>'author' ILIKE ${n})")
        params.append(speaker)

    q_terms = terms(q)
    if q_terms and tsquery:
        q_expr = tsquery
    elif q_terms:
        q_expr = " | ".join(q_terms)
    if q_terms:
        # OR, not AND. `plainto_tsquery` requires EVERY word, so "pivot after a failed round"
        # returned one block in the whole corpus — a question phrased as a sentence found nothing.
        # OR-ing the terms and letting ts_rank order the result is what the kernel's own retrieval
        # does, and it is the difference between a mode that answers and a mode that shrugs.
        n += 1
        params.append(q_expr)
        where.append(f"tsv @@ to_tsquery('english', ${n})")
        # Normalisation 1 divides the rank by 1 + log(length). Without it a 4,000-character essay
        # that mentions a word twice outranks a chapter titled exactly that word, and the podcast
        # moments — the thing this mode exists to surface — never appear at all.
        # A moment nobody can open is worth less than one they can. Older items that scrolled out of
        # their feed before the parser learned to read enclosures have no address and can never get
        # one, so they are demoted rather than deleted — the words are still worth finding.
        rank = (f"ts_rank(tsv, to_tsquery('english', ${n}), 1) * "
                f"CASE WHEN (facets ? 'url' OR facets ? 'episode_url') THEN 1.0 ELSE 0.7 END")
        order_sql = f"{rank} DESC, facets->>'published_at' DESC NULLS LAST"
        # The outer query of the per-piece path can only name columns the inner one returned, and
        # `tsv` is a generated column that is never selected. Order by the SELECTED alias instead of
        # recomputing the rank — recomputing it is also wasted work.
        outer_order = "score DESC, facets->>'published_at' DESC NULLS LAST"
        # An essay block can be thousands of characters, so the head of it is rarely the part that
        # answered the question. ts_headline returns the passage that actually matched.
        snippet = (f"ts_headline('english', text, to_tsquery('english', ${n}), "
                   f"'MaxWords=48, MinWords=20, ShortWord=3, MaxFragments=1, StartSel=\u00ab, StopSel=\u00bb')")
    else:
        rank = "0.0"
        # Newest by the PIECE's date; ingest time only breaks ties for rows with no usable date.
        order_sql = ("(facets->>'views')::bigint DESC, facets->>'published_at' DESC NULLS LAST"
                     if order == "watched"
                     else "facets->>'published_at' DESC NULLS LAST, created_at DESC NULLS LAST")
        snippet = "left(text, 320)"
        outer_order = order_sql

    n += 1
    params.append(int(max(1, min(limit, 100))))
    # created_at is SELECTED, not merely ordered by: the per-piece path wraps this in an outer
    # query, and an outer ORDER BY can only name columns the inner query returned.
    cols = (f"document_id, block_id, text, document_title, source_key, facets, created_at, "
            f"{rank} AS score, {snippet} AS snippet")
    if per_document:
        # One row per EPISODE. Without this a company's strip fills with the first eight chapters of
        # one episode ("00:00 Intro", "02:00 Early days") and every other episode is pushed out.
        # The outer sort must repeat the real ordering. Sorting the deduplicated set by score put
        # every row at 0.0 in a browse, so it fell through to document_id — an alphabetical feed in
        # which "founder_essay:…" always beat "show_notes:…" and video never appeared at all.
        sql = (f"SELECT * FROM (SELECT DISTINCT ON (document_id) {cols} "
               f"FROM {table} WHERE {' AND '.join(where)} ORDER BY document_id, {order_sql}) s "
               f"ORDER BY {outer_order} LIMIT ${n}")
    else:
        sql = f"SELECT {cols} FROM {table} WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ${n}"
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
