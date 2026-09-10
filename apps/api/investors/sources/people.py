"""Team pages -> named people with the profile links the page itself printed (no model call).

A team page is the only public source that says who actually works at a fund, and reading one without a model
is a precision problem: a page is full of capitalised word pairs that are not people ("Portfolio Companies",
"New York", "Series A"). Guessing produces a card full of invented partners, which is worse than an empty one.

So the parser is **link-anchored**: it starts from a URL that already contains a name and works outward to the
name printed beside it. That inverts the usual failure — instead of finding names and hoping a link belongs to
them, it finds links and admits only the names it can BIND to one.

The anchor that actually works is **the firm's own profile link**, not LinkedIn. Measured on four real team
pages (2026-09-10): Bessemer prints zero LinkedIn links, USV zero, Initialized one, Craft four — so a
LinkedIn-anchored parser reads almost nobody. What all four DO print is a link to the person's own page on the
firm's site, whose slug is their name: `/team/david-sacks`, `/people/fred-wilson/`, `data-name="byron deeter"`.
That is the primary anchor; LinkedIn and X are read too, and are worth more per person, but they are the rarer
case rather than the common one.

The binding rule is this module's whole point. A candidate name is accepted only when its tokens are present in
the slug — "david-sacks" binds "David Sacks", and does not bind the "Mark Woolway" whose card sits two divs
later in the DOM. That is the same subject-congruence rule the rest of the mode runs on, applied to people.

What this deliberately cannot do: find a partner the page links to by nothing at all. That person is missing
rather than wrong, and the card says how many it found rather than implying it found everyone.
"""
from __future__ import annotations

import html as _html
import re

# The roles a fund's own team page prints. Ordered longest-first so "managing general partner" is not read as
# "partner", and "venture partner" (an affiliate) is not confused with a general partner (a principal).
ROLES = (
    ("founding_partner", ("founding partner", "founding general partner", "co-founder & partner", "founder & partner")),
    ("managing_partner", ("managing partner", "managing general partner", "managing director", "manager partner")),
    ("general_partner", ("general partner", "gp", "partner & co-founder")),
    ("venture_partner", ("venture partner", "operating partner", "advisory partner", "partner emeritus")),
    ("founder", ("founder", "co-founder", "cofounder", "founder & ceo", "founder and ceo")),
    ("chief", ("chief executive", "ceo", "cto", "coo", "cfo", "chief financial officer", "chief operating officer",
               "chief investment officer", "cio", "chief of staff", "general counsel")),
    ("principal", ("principal", "vice president", "senior associate", "investment director", "director")),
    ("partner", ("partner",)),
    ("associate", ("associate", "analyst", "investor", "investment associate", "senior analyst")),
    ("platform", ("head of platform", "head of talent", "head of marketing", "head of communications",
                  "operations", "controller", "head of finance", "recruiting", "community")),
)
_ROLE_LOOKUP = [(name, phrase) for name, phrases in ROLES for phrase in sorted(phrases, key=len, reverse=True)]

# The firm's own profile link: /team/<slug>, /people/<slug>, /partners/<slug> ...
_PROFILE_HREF = re.compile(
    r"(?i)href\s*=\s*[\"']([^\"']*?/(?:team|people|our-team|our-people|partners|staff|members|who-we-are"
    r"|leadership|profile|bio|person)/([a-z0-9][a-z0-9\-_.%]{2,60}?)/?)[\"'#?]")
# Some templates carry the name outright in a data attribute (Bessemer: data-name="byron deeter").
_DATA_NAME = re.compile(r"(?i)data-(?:name|person|member|full-?name)\s*=\s*[\"']([A-Za-z][A-Za-z'’\-. ]{3,50})[\"']")
# Template class names that mark the title element (Webflow / WordPress team components).
_TITLE_CLASS = re.compile(
    r"(?is)class\s*=\s*[\"'][^\"']*(?:member-?title|person-?title|team-?title|role|position|job-?title)"
    r"[^\"']*[\"'][^>]*>(.{0,120}?)<")
_LINKEDIN = re.compile(r"https?://(?:[a-z0-9\-]{2,4}\.)?linkedin\.com/in/([A-Za-z0-9\-_%.]{2,80})", re.I)
_X = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{2,30})(?![\w/])", re.I)
_NOISE = re.compile(r"(?is)<(svg|script|style|noscript|path|symbol|defs)\b.*?</\1>|<path\b[^>]*>")
_HEADING = re.compile(r"(?is)<(h[1-6])[^>]*>(?:\s*<[^>]+>)*\s*([^<>{}]{4,60}?)\s*(?:</[^>]+>\s*)*</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"\s+")

# Words that appear inside capitalised phrases which are NOT people. A team page is full of them.
_NOT_A_NAME = {
    "portfolio", "companies", "company", "team", "about", "contact", "careers", "news", "investments",
    "investment", "fund", "funds", "capital", "ventures", "venture", "partners", "partner", "management",
    "linkedin", "twitter", "email", "read", "more", "view", "profile", "learn", "join", "our", "the", "and",
    "series", "seed", "growth", "equity", "san", "new", "york", "francisco", "london", "menlo", "park",
    "privacy", "policy", "terms", "legal", "press", "blog", "home", "back", "next", "previous", "all",
    "follow", "connect", "bio", "full", "close", "menu", "search", "apply", "subscribe", "newsletter",
    "photo", "headshot", "portrait", "image", "logo", "skip", "content", "main", "toggle", "navigation",
    # Role words. Without these the 4-token name pattern swallows the title printed beside the name and
    # yields "Mark Woolway President" as a person, and "Van Linge Principal" as a second, fictional one.
    "president", "principal", "director", "chairman", "chairwoman", "chair", "chief", "officer", "head",
    "vice", "senior", "junior", "managing", "general", "founding", "operating", "emeritus", "analyst",
    "associate", "advisor", "adviser", "counsel", "controller", "ceo", "cto", "coo", "cfo", "cio",
    "manager", "management", "lead", "leader", "executive", "assistant", "coordinator", "specialist",
}
# A handle that is the FIRM's account, not a person's. Never bound to whoever appears near it.
_FIRM_HANDLE_HINTS = ("vc", "capital", "ventures", "partners", "fund", "hq", "team", "official")
_SECTION_SLUGS = {"all", "index", "team", "people", "partners", "staff", "everyone", "list", "page", "us",
                  "our-team", "leadership", "investors", "advisors", "board", "more", "archive", "search"}


def _text(fragment: str) -> str:
    return _WS.sub(" ", _html.unescape(_TAG.sub(" ", fragment or ""))).strip()


def name_tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", (s or "").lower()) if len(t) > 1]


def looks_like_a_person(name: str) -> bool:
    """Two to four capitalised words, none of them page furniture.

    Deliberately strict. A team page prints "Portfolio Companies" and "New York" in the same styles it prints
    "Jane Okafor", and there is no structural difference between them — only this vocabulary check.
    """
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not (2 <= len(parts) <= 4):
        return False
    if any(p.lower().strip(".,") in _NOT_A_NAME for p in parts):
        return False
    particles = {"van", "von", "de", "del", "della", "da", "di", "la", "le", "bin", "al", "el", "st", "mc"}
    for p in parts:
        core = p.strip(".,'’-")
        if not core or any(c.isdigit() for c in core):
            return False
        if core.lower() in particles:
            continue
        if not core[0].isupper():
            return False
        if len(core) > 2 and core.isupper():
            return False
    return True


def bind_score(name: str, slug: str) -> float:
    """How much of this name the slug accounts for — 1.0 when every token is present, 0.0 when it does not bind.

    Several candidates can bind one slug: for `kindle-van-linge`, both "Kindle Van Linge" (3 of 3 tokens) and
    the fragment "Van Linge Principal" (2 of 3) pass the yes/no gate. Picking the FIRST one found invented a
    second person out of one card, so the best-covered candidate wins instead.
    """
    if not binds(name, slug):
        return 0.0
    n = name_tokens(name)
    s = set(name_tokens(slug))
    return len([t for t in n if t in s]) / max(1, len(n))


def _best_binding(names: list[str], slug: str) -> str | None:
    """The candidate that best accounts for the slug: highest coverage, then fewest tokens."""
    scored = [(bind_score(n, slug), -len(name_tokens(n)), n) for n in names]
    scored = [x for x in scored if x[0] > 0]
    return max(scored)[2] if scored else None


def binds(name: str, slug: str) -> bool:
    """Do this name's tokens appear in this slug?

    The gate that makes a link a person's OWN link. `/team/david-sacks` binds "David Sacks"; it does not bind
    "Mark Woolway", whose card may sit closer in the raw HTML but shares no token with it. A single-token match
    is not enough — "chen" alone matches half of `chen-wei-investments` — so a two-part name must match both
    its tokens, and a longer name at least two, one of which is its first or last.
    """
    n = name_tokens(name)
    s = set(name_tokens(slug))
    if not n or not s:
        return False
    hits = [t for t in n if t in s]
    if len(n) <= 2:
        return len(hits) == len(n)
    return len(hits) >= 2 and (n[0] in s or n[-1] in s)


def role_of(text: str) -> tuple[str, str]:
    """(normalised role, the title as the page printed it) from the text beside a name."""
    low = " " + (text or "").lower().replace("&", " & ") + " "
    for name, phrase in _ROLE_LOOKUP:
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", low):
            m = re.search(r"(?i)([A-Za-z&,\-\s]{0,40}" + re.escape(phrase) + r"[A-Za-z&,\-\s]{0,20})", text or "")
            return name, _WS.sub(" ", (m.group(1) if m else phrase)).strip(" ,-&")[:60]
    return "", ""


def _candidate_names(fragment: str) -> list[str]:
    """Every plausible person-name string in a fragment, nearest the END first (closest to the link).

    Names are read PER ELEMENT, never across the flattened text. `<h4>David Sacks</h4><p>Partner</p>
    <h4>Elyse Davis</h4>` flattens to "David Sacks Partner Elyse Davis", and a four-token pattern happily
    reads a person out of the middle of that — inventing "David Sacks Elyse Davis". The tag boundary IS the
    person boundary on a team page, so the split comes first and the pattern runs inside each piece.
    """
    out: list[str] = []
    for piece in _TAG.split(fragment or ""):
        txt = _WS.sub(" ", _html.unescape(piece)).strip()
        if not (4 <= len(txt) <= 80):
            continue
        for m in re.finditer(r"\b([A-Z][\w'’\-.]+(?:\s+[A-Za-z][\w'’\-.]+){1,3})\b", txt):
            cand = m.group(1).strip()
            if looks_like_a_person(cand):
                out.append(cand)
    for m in re.finditer(r"(?i)(?:alt|title|aria-label)\s*=\s*[\"']([^\"']{3,60})[\"']", fragment or ""):
        cand = _WS.sub(" ", _html.unescape(m.group(1))).strip()
        cand = re.sub(r"(?i)^\s*(?:photo|picture|image|headshot|portrait)\s+of\s+", "", cand).strip()
        cand = re.sub(r"(?i)\s*(?:’s|'s)?\s*(?:linkedin|twitter|x|profile|photo|headshot|portrait)\s*$", "", cand).strip()
        if looks_like_a_person(cand):
            out.append(cand)
    return list(reversed(out))


def _slug_could_be_a_name(slug: str) -> bool:
    """A person's slug carries at least two name-ish parts; a section index carries one word."""
    s = slug.lower().rstrip("/")
    if s in _SECTION_SLUGS or s.isdigit():
        return False
    return len(name_tokens(s)) >= 2


def parse_team(html: str, *, window: int = 1200, base_domain: str = "") -> list[dict]:
    """[{name, title, role, links:{profile,linkedin,x}, basis}] from a team page's raw HTML.

    Anchors, in order of how often they actually appear: the firm's own profile link for the person, a
    `data-name` attribute, then a LinkedIn or X URL. Every one is accepted only when a name printed nearby
    BINDS to the slug — a link that binds to nobody is dropped, never attached to whoever is nearest.
    """
    if not html:
        return []
    # SVG path data and inline script/style are noise in every window this parser opens — an icon between a
    # name and its title is hundreds of characters of coordinates that push the role out of range.
    html = _NOISE.sub(" ", html)
    found: dict[str, dict] = {}

    def slot(name: str, basis: str) -> dict:
        return found.setdefault(name, {"name": name, "title": "", "role": "", "links": {}, "basis": basis})

    def fill_role(s: dict, near_html: str, name: str) -> None:
        if s["role"]:
            return
        m = _TITLE_CLASS.search(near_html)
        cand = _text(m.group(1)) if m else ""
        role, title = role_of(cand) if cand else ("", "")
        if not role:
            near = _text(near_html)
            i = near.rfind(name)
            # Read the title from AFTER the name — "Jane Okafor, General Partner" yields the role, not the
            # person repeated back as their own job title.
            role, title = role_of(near[i + len(name):i + len(name) + 160] if i >= 0 else near)
        if role or title:
            s["role"], s["title"] = role, (title or cand)[:60]

    for m in _PROFILE_HREF.finditer(html):
        href, slug = m.group(1), m.group(2)
        if not _slug_could_be_a_name(slug):
            continue
        start = max(0, m.start() - window)
        names = _candidate_names(html[start:m.start()]) + _candidate_names(html[m.end():m.end() + window])
        name = _best_binding(names, slug)
        if not name:
            continue
        s = slot(name, "profile_link")
        url = href if href.startswith("http") else (f"https://{base_domain}{href}"
                                                    if base_domain and href.startswith("/") else href)
        s["links"].setdefault("profile", url)
        fill_role(s, html[start:m.end() + window], name)

    # A page that links nothing at all still marks its people structurally: a heading holding the name, with
    # the role printed just after it (Initialized: <h3>Abdul Ly</h3> ... <div>Partner</div>). There is no slug
    # to bind against here, so the ROLE does the binding instead — "Portfolio Companies" is never followed by
    # "General Partner", and requiring a known role within a short window is what keeps this from guessing.
    for m in _HEADING.finditer(html):
        cand = _text(m.group(2))          # group(1) is the tag name; group(2) is the heading's text
        if not looks_like_a_person(cand):
            continue
        role, title = role_of(_text(html[m.end():m.end() + 400]))
        if not role:
            continue
        s = slot(cand, "heading_role")
        if not s["role"]:
            s["role"], s["title"] = role, title

    for m in _DATA_NAME.finditer(html):
        cand = _WS.sub(" ", m.group(1)).strip()
        cand = cand.title() if cand.islower() or cand.isupper() else cand
        if not looks_like_a_person(cand):
            continue
        s = slot(cand, "data_attribute")
        fill_role(s, html[max(0, m.start() - 200):m.end() + window], cand)

    for rx, key in ((_LINKEDIN, "linkedin"), (_X, "x")):
        for m in rx.finditer(html):
            sl = m.group(1)
            if key == "x" and any(h in sl.lower() for h in _FIRM_HANDLE_HINTS):
                continue
            start = max(0, m.start() - window)
            names = _candidate_names(html[start:m.start()]) + _candidate_names(html[m.end():m.end() + 200])
            # a name already found on this page is the best candidate; otherwise bind a fresh one
            name = _best_binding(list(found) + names, sl)
            if not name:
                continue
            s = slot(name, found.get(name, {}).get("basis") or key)
            s["links"].setdefault(key, m.group(0))
            fill_role(s, html[start:m.end() + 200], name)

    return list(found.values())


def firm_handle(html: str) -> str:
    """The firm's OWN X handle, if the page links one — so it is never attributed to a person."""
    for m in _X.finditer(html or ""):
        if any(h in m.group(1).lower() for h in _FIRM_HANDLE_HINTS):
            return m.group(0)
    return ""


# --------------------------------------------------------------------------------------------------------
# A person's OWN profile page on the firm's site — where the LinkedIn and X links actually live.
#
# Measured 2026-09-10: team pages carry almost no social links, but the per-person pages behind them carry
# both. USV's team page links no LinkedIn at all; fredwilson's page links his X. Bessemer's links
# `byrondeeter`; Craft's links `davidoliversacks`; Lux's links `josh-wolfe-7883`.
#
# The binding rule has to loosen here, and can, because the SUBJECT IS ALREADY KNOWN — we followed a link
# whose slug bound this person on the team page, so the page is about them. What remains is telling their
# handle from the FIRM's, which is on the same page every time (`usv`, `craft_ventures`, `Lux_Capital`,
# `bessemervp`). That is what `loose_binds` decides, and it is why a bare "follow us" link is never
# attributed to whoever the page is about.
# --------------------------------------------------------------------------------------------------------

def _flat(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def loose_binds(name: str, handle: str) -> bool:
    """Does this handle belong to this person, allowing for handles with no separators?

    `binds` splits on separators, so it cannot see the name inside "byrondeeter" or "davidoliversacks". This
    matches on the flattened string instead: the surname must appear, plus the given name or its initial.
    Requiring the surname is what rejects the firm — "craftventures" holds no part of "David Sacks".
    """
    toks = name_tokens(name)
    if len(toks) < 2:
        return False
    h = _flat(handle)
    first, last = toks[0], toks[-1]
    if last not in h:
        return False
    return first in h or h.startswith(first[0]) or h.endswith(first) or first[0] + last in h


def parse_profile_links(html: str, name: str, *, firm_domain: str = "") -> dict:
    """{linkedin, x, role, title} from one person's own page. Only links that bind to THEM.

    The role comes from here too, because a listing page often prints only names — Greylock and Bessemer
    both do — and their per-person pages print the title. It is the same fetch either way.
    """
    if not html or not name:
        return {}
    html = _NOISE.sub(" ", html)
    out: dict = {}
    # The title sits next to the name near the top of the page; read the first role phrase in that region.
    head = _text(html[:12_000])
    i = head.find(name)
    role, title = role_of(head[i + len(name):i + len(name) + 200] if i >= 0 else head[:400])
    if role:
        out["role"], out["title"] = role, title
    firm_flat = _flat(firm_domain.split(".")[0] if firm_domain else "")
    for m in _LINKEDIN.finditer(html):
        if loose_binds(name, m.group(1)):
            out["linkedin"] = m.group(0)
            break
    for m in _X.finditer(html):
        h = m.group(1)
        if firm_flat and _flat(h) == firm_flat:
            continue                                  # the firm's own account, not theirs
        if any(hint in h.lower() for hint in _FIRM_HANDLE_HINTS) and not loose_binds(name, h):
            continue
        if loose_binds(name, h):
            out["x"] = m.group(0)
            break
    return out
