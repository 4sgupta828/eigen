"""What OUR OWN corpus already holds about this company.

DeepDive read the company's site, the keyless public sources and the open web — and never once looked
in the corpus this product is built on. 650,525 blocks sat there: 464k SEC filings, 92k preprints,
33k code documents, 19k papers, plus patents, funding and news. For a company we have ingested
anything about, the deepest source available was the one we never queried.

This is FREE — our own Postgres, keyword search over the tsvector that already exists. It runs at
every depth, including `held`, which is what turns `held` from two reference rows into a real reading.

THE HARD PART IS NOT FINDING BLOCKS, IT IS SAYING WHOSE THEY ARE.
A keyword search returns every block that names the company, and most of them are somebody ELSE'S
document. Amazon's 10-K discusses its stake in Anthropic; a hundred GitHub READMEs list Anthropic
among their providers; a paper's bibliography cites them. Filing those under "What they have filed"
and "Their public code" is wrong-company attribution — the exact failure class the standing directive
names, and the reason "the quote exists" is never the same as "the quote is about them".

So every hit is classified on ONE question: is the company the document's SUBJECT, or is it named
inside somebody else's? Both are kept — Amazon disclosing a stake in Anthropic is a strong signal —
but they never share a heading, and a mention is never dressed up as the company's own filing.

Ownership is decided from the document id and the document's host — facts about where a document came
from — never from how the text reads:
  - `edgar`    — the accession's leading digits ARE the filer's CIK. Theirs iff it is the company's.
  - `github` / `huggingface` — the native id is `owner/name`. Theirs iff the owner is the company.
  - feeds, web, news, blogs — the document URL's host. Theirs iff it is the company's own domain.
  - `wikipedia` / `wikidata` / `yc` — a reference page ABOUT one subject; theirs iff the title names
    them.
  - research and patents — authored or assigned, and we hold no reliable affiliation or assignee, so
    it is always "research that names them". Saying less than we know beats saying more than we can
    show.

Links come from the vertical's own canonical link builder (`ui.source_url`), not from guessing which
facet key a connector used. A row the reader cannot open is a row they have to take on faith.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse

from .gates import subject_bound

# source_key -> (title when the document is THEIRS, title when they are merely NAMED, register).
# The register describes what the SOURCE IS — a filing is `filed` whoever filed it — never how
# confident the text sounds.
_REGISTER = {
    "edgar":            ("What they have filed", "Named in others' filings", "filed"),
    "filing":           ("What they have filed", "Named in others' filings", "filed"),
    "companies_house":  ("What they have filed", "Named in others' filings", "filed"),
    "uspto":            ("Their patents", "Named in others' patents", "filed"),
    "patentsview":      ("Their patents", "Named in others' patents", "filed"),
    "nsf":              ("Public funding they were awarded", "Named in public funding records", "filed"),
    "nih_reporter":     ("Public funding they were awarded", "Named in public funding records", "filed"),
    "arxiv":            ("Research", "Research that names them", "stated"),
    "openalex":         ("Research", "Research that names them", "stated"),
    "semantic_scholar": ("Research", "Research that names them", "stated"),
    "crossref":         ("Research", "Research that names them", "stated"),
    "openreview":       ("Research", "Research that names them", "stated"),
    "github":           ("Their public code", "Named in public code", "observed"),
    "huggingface":      ("Their public models", "Named in public models", "observed"),
    "news":             ("Press", "Press", "stated"),
    "startup_news":     ("Press", "Press", "stated"),
    "gdelt":            ("Press", "Press", "stated"),
    "hackernews":       ("Discussion", "Discussion", "stated"),
    "lobsters":         ("Discussion", "Discussion", "stated"),
    "reddit":           ("Discussion", "Discussion", "stated"),
    "stackoverflow":    ("Discussion", "Discussion", "stated"),
    "eng_blog":         ("Their engineering writing", "Engineering writing that names them", "stated"),
    "founder_essay":    ("Their founders' writing", "Founder and investor writing about them", "stated"),
    "expert_feed":      ("Their writing", "Analysis that names them", "stated"),
    "podcast":          ("Them, in their own words", "Conversations that name them", "stated"),
    "show_notes":       ("Them, in their own words", "Conversations that name them", "stated"),
    "youtube_chapters": ("Them, in their own words", "Conversations that name them", "stated"),
    "yc":               ("Their YC profile", "Named in YC records", "stated"),
    "wikipedia":        ("Reference profile", "Named in reference pages", "stated"),
    "wikidata":         ("Reference profile", "Named in reference pages", "stated"),
    "web":              ("Their own pages, as we hold them", "Web pages that name them", "stated"),
}
_DEFAULT = ("Also in our corpus", "Elsewhere in our corpus", "stated")

# Their own documents first, a filing before a blog post, and everybody else's documents after all of
# them. This is the order a reader should meet the evidence in: an authority statement, not layout.
_OWN_ORDER = [
    "What they have filed", "Their patents", "Public funding they were awarded",
    "Their public code", "Their public models", "Their YC profile", "Reference profile",
    "Their engineering writing", "Their founders' writing", "Their writing",
    "Them, in their own words", "Their own pages, as we hold them", "Press", "Discussion",
    "Also in our corpus",
]
_MENTION_ORDER = [
    "Named in others' filings", "Named in others' patents", "Named in public funding records",
    "Named in public code", "Named in public models", "Named in YC records",
    "Named in reference pages", "Research", "Research that names them",
    "Engineering writing that names them", "Founder and investor writing about them",
    "Analysis that names them", "Conversations that name them", "Web pages that name them",
    "Elsewhere in our corpus",
]
_ORDER = _OWN_ORDER + _MENTION_ORDER
# "Research" is reachable both ways in the table above, but nothing we can bind ever lands there, so
# it is grouped with the documents that merely name them. "Press" is genuinely about them whoever
# wrote it, which is why press is not demoted.
_MENTION_TITLES = frozenset(_MENTION_ORDER)

MAX_PER_SOURCE = 4
MAX_TOTAL = 40
MIN_CHARS = 40
MAX_QUOTE = 360


def _domain(d: str) -> str:
    """A bare host, whatever we were handed.

    A company row carries its site as `website` ("https://www.anthropic.com/") and its id as a bare
    host, and the two were used interchangeably. With a scheme still attached, the host comparison in
    `is_theirs` could never match — so every page ON anthropic.com was filed as a page that merely
    NAMED Anthropic, which is the same attribution error in the other direction.
    """
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split("?")[0].split("#")[0]
    d = d.split("@")[-1].split(":")[0]
    return d[4:] if d.startswith("www.") else d


def _terms(name: str, domain: str) -> list[str]:
    """What counts as naming this company. Deliberately narrow: a short or generic name matched
    loosely turns every block mentioning 'Scale' or 'Anthropic-like' into a claim about them."""
    out = []
    n = (name or "").strip()
    if len(n) >= 3:
        out.append(n)
    d = _domain(domain)
    if d and "." in d:
        out.append(d)
        stem = d.split(".")[0]
        if len(stem) >= 4 and stem.lower() != n.lower():
            out.append(stem)
    return out[:3]


def names_subject(text: str, title: str, terms: list[str]) -> bool:
    """Does this passage NAME the company? Case-insensitive, and a bare name must stand as its own
    word — "Scale" must not be matched inside "scaled", which is how a generic name turns half the
    corpus into claims about one startup."""
    hay = f"{text}\n{title}".lower()
    for t in terms:
        t = t.lower().strip()
        if not t:
            continue
        if "." in t:                       # a domain: a substring match is already specific
            if t in hay:
                return True
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            return True
    return False


_CITE = re.compile(r"\((?:19|20)\d\d[a-z]?\)")


def looks_like_bibliography(text: str) -> bool:
    """A reference list is not a finding.

    Papers store their bibliography in the same blocks as their argument, and a bibliography ranks
    for any term it cites — which is how "Aboulkhair et al. (2016), On the formation of…" arrived as
    a claim about an AI lab. Three or more year-citations in one passage, or a heading that says so.
    """
    if text.lstrip()[:40].lower().startswith(("references", "bibliography", "works cited")):
        return True
    return len(_CITE.findall(text)) >= 3


# An ingested web page arrives with a header the ingest wrote and a navigation bar the site wrote.
# Quoting either at a reader is quoting furniture: "# Claude Sonnet \\ Anthropic / Published: … /
# Source: anthropic.com (anthropic.com) / Language: en / ## Story / Skip to main contentSkip to
# footer / [Home](…)". The page's actual first sentence is three hundred characters further down.
_PREAMBLE = re.compile(r"^\s*(?:published|source|language|author|date|updated)\s*:.*$",
                       re.IGNORECASE | re.MULTILINE)
_NAV = re.compile(r"skip to (?:main content|footer|content)", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]]{0,80})\]\(https?://[^)]+\)")
_H1 = re.compile(r"^\s*#\s+(.{3,140}?)\s*$", re.MULTILINE)
_SECTION_HEAD = re.compile(r"^\s*#{1,6}\s*(?:story|article|content)\s*$", re.IGNORECASE | re.MULTILINE)


def headline(text: str, document_title: str) -> str:
    """The best name we have for this document.

    An ingested page's stored title is often just the site's ("Anthropic" for every page on
    anthropic.com), while the page's own H1 says which page it is. Prefer the H1 when the stored
    title is a prefix of it or the site's bare name — otherwise keep what was stored.
    """
    t = (document_title or "").strip()
    m = _H1.search(text or "")
    h = (m.group(1).strip() if m else "").replace(" \\ ", " — ")
    if h and (not t or t.lower() in h.lower()):
        return h[:160]
    return t[:160]


def clean_passage(text: str, title: str = "") -> str:
    """The passage with the ingest header, the navigation chrome and the repeated title taken out.

    A page's name appears three times before its first real sentence — once as the ingest's H1, once
    under the "## Story" divider, once as the page's own H1 — so a quote that began at character
    zero was the title, the title, and the title again.
    """
    # ENTITIES FIRST. Feed ingests store the escaped source, so a Hacker News comment reached the
    # reader as `&quot;using Claude from Anthropic&quot; here: https:&#x2F;&#x2F;www.mozilla.org` —
    # the same missing unescape that made engineering-blog rows unreadable.
    t = html.unescape(text or "")
    t = _PREAMBLE.sub("", t)
    t = _SECTION_HEAD.sub("", t)
    t = _NAV.sub("", t)
    t = _MD_LINK.sub(r"\1", t)                 # a link's text, not its markdown
    t = re.sub(r"^\s*#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    ts = _slug(title)
    dropped = 0
    while lines and dropped < 12:
        ls = _slug(lines[0])
        # the title again…
        if ts and len(ts) >= 4 and ls and (ls in ts or ts in ls):
            lines.pop(0); dropped += 1; continue
        # …or a navigation item: a short fragment with no sentence in it. The moment a line reads
        # like prose we stop, so a genuinely terse first sentence is never eaten.
        bare = lines[0].lstrip("-*• ").strip()
        if len(bare) < 30 and not re.search(r"[.!?:]$", bare) and len(bare.split()) <= 4:
            lines.pop(0); dropped += 1; continue
        break
    return " ".join(lines).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# An org handle is rarely the company name character for character: Anthropic publishes as
# `anthropics`, and labs routinely append `ai`, `hq`, `labs` or `inc`. Stripping those before
# comparing is the difference between finding their SDK and filing it as somebody else's repo.
_ORG_SUFFIX = ("labs", "inc", "hq", "ai", "io", "s")


def _org_core(s: str) -> str:
    s = _slug(s)
    for suf in _ORG_SUFFIX:
        if len(s) > len(suf) + 3 and s.endswith(suf):
            return s[: -len(suf)]
    return s


def same_org(a: str, b: str) -> bool:
    """Do these two handles name the same organisation? Requires a core of at least four characters,
    so `ai` and `x` never match everything."""
    ca, cb = _org_core(a), _org_core(b)
    return bool(ca) and len(ca) >= 4 and ca == cb


# ── is this name an IDENTIFIER, or just a word? ───────────────────────────────────────────────────
#
# "Anthropic" identifies one company. "Clay" does not: it is an ordinary noun and a personal name,
# and a whole-word search for it returns William Clay Ford in Ford's proxy statement, Ms. Clay in
# Jones Lang LaSalle's, a clay cap in a geothermal paper, and Clay Regazzoni winning the 1979 British
# Grand Prix. Every one of those passed the whole-word check and arrived as a claim about a sales
# automation startup.
#
# Rather than ship a dictionary, ASK THE CORPUS. The rows we just retrieved are the sample: if the
# token turns up in lowercase running prose, or sitting inside somebody's name, it is a word people
# use and not a mark that picks out a company.

_HONORIFIC = re.compile(r"\b(mr|mrs|ms|miss|dr|prof|sir|lord|rev)\.?\s*$", re.IGNORECASE)


def _uses_as_word(text: str, name: str) -> bool:
    """Is `name` used here as an ordinary lowercase word, mid-sentence?"""
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])", text):
        before = text[:m.start()].rstrip()
        if before and before[-1] not in ".!?:;\n" and text[m.start():m.end()] == name.lower():
            return True
    return False


def _uses_as_person(text: str, name: str) -> bool:
    """Is `name` sitting inside somebody's name here? "Ms. Clay", "William Clay Ford".

    Only two patterns count, both of which put the name in the MIDDLE or END of a person's name: an
    honorific in front of it, or another capitalised word directly in front of it. A capitalised word
    AFTER it is not evidence — that rule read "Anthropic CEO Dario Amodei" and "Anthropic Claude
    Sonnet" as people, which is how a perfectly distinctive name was called ambiguous.
    """
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text):
        if _HONORIFIC.search(text[max(0, m.start() - 8):m.start()]):
            return True
        if re.search(r"(?:^|[\s(])([A-Z][a-z]{1,20})\s+$", text[max(0, m.start() - 26):m.start()]):
            return True
    return False
# How much of the sample has to use the name as a word or a person before we stop trusting it alone.
AMBIGUOUS_AT = 0.12
MIN_SAMPLE = 12


def name_is_ambiguous(name: str, texts: list[str]) -> tuple[bool, int]:
    """(ambiguous, how many of the sample used it as a word or a person)."""
    n = (name or "").strip()
    if len(n) < 3 or " " in n:          # a multi-word mark is already specific
        return False, 0
    hits = sum(1 for t in texts if _uses_as_word(t, n) or _uses_as_person(t, n))
    if len(texts) < MIN_SAMPLE:
        return False, hits
    return (hits / len(texts)) >= AMBIGUOUS_AT, hits


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().replace("www.", "")
    except Exception:      # noqa: BLE001
        return ""


def is_theirs(document_id: str, source_key: str, document_title: str, url: str, *,
              name: str, domain: str, cik: str = "") -> bool:
    """Is the company the document's SUBJECT, or is it named inside somebody else's document?

    Unsure is `False`. A mention filed as a mention is honest; somebody else's 10-K filed as this
    company's own filing is the wrong-company attribution the gates exist to make impossible.
    """
    src, _, native = (document_id or "").partition(":")
    src = (src or source_key or "").lower()
    dom = _domain(domain)
    nslug = _slug(name)
    dslug = _slug(dom.split(".")[0]) if dom else ""

    if src in ("edgar", "sec", "filing"):
        # An accession is {10-digit filer CIK}-{YY}-{sequence}: its leading digits ARE the filer.
        head = native.split("-", 1)[0] if native else ""
        filer = head.lstrip("0") if head.isdigit() else ""
        return bool(cik) and bool(filer) and filer == str(cik).lstrip("0")

    if src in ("github", "huggingface"):
        owner = (native or "").split("/")[0]
        return any(same_org(owner, cand) for cand in (nslug, dslug) if cand)

    if src in ("wikipedia", "wikidata", "yc", "companies_house"):
        return bool(nslug) and nslug in _slug(document_title)

    if src in ("arxiv", "openalex", "semantic_scholar", "crossref", "openreview",
               "uspto", "patentsview", "nsf", "nih_reporter"):
        return False

    # Everything that came off a URL — feeds, blogs, news, web pages: the host says whose it is.
    h = _host(url) or _host(native)
    return bool(dom) and bool(h) and (h == dom or h.endswith("." + dom))


def _facets(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw) or {}
        except Exception:      # noqa: BLE001
            return {}
    return raw or {}


async def corpus_hits(dsn: str, *, name: str, domain: str, cik: str = "", tenant: str = "demo",
                      ui=None, corroborators: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    """([hit], attempt). Keyword search over the corpus we already hold. Never raises: a corpus we
    cannot reach makes the dossier thinner and is reported as an attempt, like any failed fetch."""
    terms = _terms(name, domain)
    if not dsn or not terms:
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages",
                    "result": "no corpus configured" if not dsn else "no usable name to search for"}
    try:
        import asyncpg
    except Exception:      # noqa: BLE001
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages", "result": "unavailable"}

    # EVERY term, not just the first. The search used to pass `terms[0]` and drop the rest, so a
    # company whose corpus presence is under its DOMAIN (repos, pages citing a URL) went unfound while
    # a perfectly good second term sat unused. `websearch_to_tsquery` is the one query parser that
    # takes an OR.
    q = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    try:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                """SELECT document_id, block_id, text, document_title, source_key, facets,
                          facets->>'published_at' AS published_at
                     FROM rs_block
                    WHERE tenant_id = $1 AND tsv @@ websearch_to_tsquery('english', $2)
                 ORDER BY ts_rank(tsv, websearch_to_tsquery('english', $2)) DESC
                    LIMIT $3""", tenant, q, MAX_TOTAL * 8)
        finally:
            await conn.close()
    except Exception as e:      # noqa: BLE001
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages",
                    "result": f"unavailable ({str(e)[:60]})"}

    # IS THE NAME AN IDENTIFIER? Measured on the rows we just retrieved, which cost nothing extra.
    dom = _domain(domain)
    ambiguous, word_uses = name_is_ambiguous(name, [(r["text"] or "") for r in rows])
    # When it is not, the name binds on its own. When it is, a passage has to carry something that
    # picks out THIS company: the domain, or somebody we already hold as connected to them.
    corro = tuple(c for c in ((dom,) + tuple(corroborators)) if c and len(c) >= 4)

    per: dict[str, int] = {}
    out: list[dict] = []
    dropped = {"unbound": 0, "not-this-company": 0}
    for r in rows:
        if len(out) >= MAX_TOTAL:
            break
        sk = (r["source_key"] or "").lower()
        if per.get(sk, 0) >= MAX_PER_SOURCE:
            continue
        text = (r["text"] or "").strip()
        if len(text) < MIN_CHARS or looks_like_bibliography(text):
            continue
        # SUBJECT BINDING. `tsv` matches stemmed lexemes anywhere in the block, which makes a row a
        # candidate, not a claim. The company has to be NAMED in the passage itself — binding on the
        # document title alone let every block of a paper through, bibliography included.
        if not names_subject(text, "", terms):
            continue

        title = r["document_title"] or ""
        facets = _facets(r["facets"])
        url = ""
        if ui is not None:
            try:
                url = ui.source_url(r["document_id"], text[:120], facets) or ""
            except Exception:      # noqa: BLE001 — a link we cannot build is a row without one
                url = ""
        url = url or facets.get("url") or facets.get("source_url") or facets.get("link") or ""

        owned_t, mention_t, register = _REGISTER.get(sk, _DEFAULT)
        theirs = is_theirs(r["document_id"], sk, title, url, name=name, domain=domain, cik=cik)

        # A document that IS theirs needs no further binding — it is their page, their repo, their
        # filing. Anything else has to earn its place.
        if not theirs:
            if ambiguous and not _corroborated(text, title, url, corro):
                dropped["unbound"] += 1
                continue
            ok, _why = subject_bound(text, list(terms), url=url, own_domain=dom)
            if not ok:
                # Another company is the subject of this sentence. "William Clay Ford, Jr." in Ford's
                # proxy statement is not a claim about a sales automation startup.
                dropped["not-this-company"] += 1
                continue

        per[sk] = per.get(sk, 0) + 1
        shown = headline(text, title)
        passage = clean_passage(text, shown)
        if len(passage) < MIN_CHARS:           # nothing left but furniture
            per[sk] = per.get(sk, 0) - 1
            continue
        out.append({"section": owned_t if theirs else mention_t, "theirs": theirs,
                    "register": register, "source_key": sk,
                    "claim": shown or text[:160], "document_title": shown or title,
                    "quote": passage[:MAX_QUOTE], "source_url": url,
                    "as_of": (r["published_at"] or "")[:10], "document_id": r["document_id"]})

    theirs_n = sum(1 for h in out if h["theirs"])
    bits = [f"{theirs_n} theirs, {len(out) - theirs_n} naming them"] if out else []
    # SAY WHY WE KEPT SO LITTLE. A name we cannot trust on its own is a finding about the search, and
    # a reader who sees three passages where they expected thirty deserves to know it was deliberate.
    if ambiguous:
        bits.append(f'“{name}” is also an ordinary word or a person’s name '
                    f"({word_uses} of the passages we found use it that way), so a passage had to "
                    f"name {dom or 'their site'} or someone we already know is connected to them")
    if dropped["unbound"]:
        bits.append(f"{dropped['unbound']} dropped as unattributable")
    if dropped["not-this-company"]:
        bits.append(f"{dropped['not-this-company']} were about another company")
    return out, {"source": "Eigen corpus", "found": len(out), "unit": "passages",
                 "result": "" if out else ("nothing we could bind to this company"
                                           if rows else "nothing about this company in the corpus yet"),
                 "ambiguous_name": ambiguous, "detail": " · ".join(bits)}


def _corroborated(text: str, title: str, url: str, corro: tuple[str, ...]) -> bool:
    """Does this passage carry something that picks out THIS company, beyond a word anyone might use?"""
    hay = f"{text}\n{title}\n{url}".lower()
    return any(c.lower() in hay for c in corro)


def as_sections(hits: list[dict]) -> list[dict]:
    """Group corpus hits into dossier sections, in the shape assemble.py already emits."""
    by: dict[str, list[dict]] = {}
    for h in hits:
        by.setdefault(h["section"], []).append(h)
    out = [_sec(t, by.pop(t)) for t in _ORDER if t in by]
    out += [_sec(t, cl) for t, cl in by.items()]   # an unmapped source still gets its rows shown
    return out


def _sec(title: str, claims: list[dict]) -> dict:
    sec = {"title": title, "kind": "corpus", "claims": claims}
    if title in _MENTION_TITLES:
        # Say it on the SECTION, not once per row. A reader who skims headings must not come away
        # thinking somebody else's filing was this company's.
        sec["note"] = "Somebody else's document, naming them — not theirs."
    return sec
