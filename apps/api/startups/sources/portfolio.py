"""Portfolio pages — accelerators and VC funds asserting their own portfolio (the non-YC population).

One curated list of public portfolio URLs (`data/portfolios.json`, dated). A page is read STRUCTURALLY only: every
external link with its anchor text, and every `{name, website}`-shaped object in embedded JSON (Next.js data,
JSON-LD, inline state) — no model, no judgment. What comes out is a candidate company `{name, website, fund}`;
its identity is the website's registrable domain, the same key the YC writer uses, so a company backed by three
funds is one node with three `investor{role=portfolio_affiliation}` (or `program`) facts. The fund's own domain,
social networks, app stores, CDNs and news sites are never companies."""
from __future__ import annotations

import html as _html
import json
import re

from . import http

_DENY = ("linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com", "youtu.be", "medium.com", "github.com",
         "apple.com", "google.com", "play.google.com", "apps.apple.com", "crunchbase.com", "angel.co", "wellfound.com", "techcrunch.com",
         "forbes.com", "bloomberg.com", "wsj.com", "nytimes.com", "reuters.com", "wikipedia.org", "sec.gov", "substack.com", "notion.site",
         "notion.so", "vimeo.com", "spotify.com", "tiktok.com", "threads.net", "producthunt.com", "ycombinator.com", "wordpress.com",
         "cloudfront.net", "amazonaws.com", "googleapis.com", "gstatic.com", "cloudflare.com", "webflow.com", "webflow.io", "squarespace.com",
         "wixstatic.com", "hubspot.com", "hsforms.com", "typeform.com", "calendly.com", "mailchimp.com", "eventbrite.com", "zoom.us", "slack.com",
         "docsend.com", "dropbox.com", "figma.com", "airtable.com", "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "bamboohr.com",
         "sentry.io", "intercom.io", "segment.com", "vercel.app", "netlify.app", "github.io", "pages.dev", "schema.org", "w3.org", "gravatar.com")
_URL_IN_TEXT = re.compile(r"https?://[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?:/[^\s\"'<>)\\]*)?")
_BAD_NAME = re.compile(r"^(read more|learn more|visit|website|view|more|link|home|open|→|›|»|company|portfolio|\s*)$", re.I)


def load_list(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _external(domain: str, own: str) -> bool:
    if not domain or "." not in domain or domain == own or domain.endswith("." + own):
        return False
    return not any(domain == d or domain.endswith("." + d) for d in _DENY)


def _walk_json(x, out: list, depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(x, dict):
        keys = {k.lower(): k for k in x.keys() if isinstance(k, str)}
        site = next((x[keys[k]] for k in ("website", "websiteurl", "website_url", "url", "site", "homepage", "link", "companyurl", "company_url", "external_link", "externalurl") if k in keys and isinstance(x[keys[k]], str) and x[keys[k]].startswith("http")), None)
        name = next((x[keys[k]] for k in ("name", "title", "company", "companyname", "company_name") if k in keys and isinstance(x[keys[k]], str)), None)
        if site and name and 1 < len(name) < 80:
            out.append((name.strip(), site.strip()))
        for v in x.values():
            _walk_json(v, out, depth + 1)
    elif isinstance(x, list):
        for v in x[:5000]:
            _walk_json(v, out, depth + 1)


def parse_page(html: str, page_url: str) -> list[dict]:
    """Candidates from anchors (external href + anchor text) and from embedded JSON objects with a name and a site."""
    own = http.registrable_domain(page_url)
    found: dict[str, dict] = {}
    def add(name: str, url: str, how: str):
        dom = http.registrable_domain(url)
        if not _external(dom, own):
            return
        name = re.sub(r"\s+", " ", _html.unescape(name or "")).strip()[:80]
        if _BAD_NAME.match(name):
            name = ""
        cur = found.get(dom)
        if cur is None:
            found[dom] = {"name": name, "website": f"https://{dom}", "how": how}
        elif not cur["name"] and name:
            cur["name"] = name
    for href, text in http.links(html, page_url):
        add(text, href, "anchor")
    for m in re.finditer(r'(?is)<script[^>]*(?:type="application/(?:ld\+)?json"|id="__NEXT_DATA__")[^>]*>(.*?)</script>', html or ""):
        try:
            data = json.loads(m.group(1))
        except Exception:   # noqa: BLE001
            continue
        pairs: list = []
        _walk_json(data, pairs)
        for name, site in pairs:
            add(name, site, "json")
    # inline state blobs (window.__STATE__ = {...}, Nuxt / Gatsby payloads): every URL with a nearby "name"-ish string is too
    # loose; take bare URLs only when the page had no anchors at all (a JS shell), so a real site is never missed entirely
    if len(found) < 5:
        for m in _URL_IN_TEXT.finditer(html or ""):
            add("", m.group(0), "text")
    return [{"domain": d, **v} for d, v in found.items()]


# ---------------------------------------------------------------- sitemaps → profile pages → the company's own site
_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
PROFILE_RX = re.compile(r"/(portfolio|companies|company|investments|startups|our-companies)/[^/?#]+/?$", re.I)
_VISIT = re.compile(r"\b(website|visit|www\.|\.com|\.ai|\.io|\.co)\b", re.I)


def sitemap_urls(site: str, *, depth: int = 1) -> list[str]:
    """Every <loc> in the site's sitemap.xml, one level of sub-sitemaps followed."""
    base = site if site.startswith("http") else f"https://{site}"
    f = http.get(base.rstrip("/") + "/sitemap.xml", min_gap=0.5, respect_robots=False, accept="application/xml,text/xml,*/*")
    if not f.ok:
        return []
    locs = _SITEMAP_LOC.findall(f.text)
    out: list[str] = []
    for loc in locs:
        if loc.lower().endswith(".xml") and depth > 0:
            g = http.get(loc, min_gap=0.5, respect_robots=False, accept="application/xml,text/xml,*/*")
            if g.ok:
                out += _SITEMAP_LOC.findall(g.text)
        else:
            out.append(loc)
    return out


def profile_urls(site: str, pattern: re.Pattern | None = None) -> list[str]:
    rx = pattern or PROFILE_RX
    seen, out = set(), []
    for u in sitemap_urls(site):
        if rx.search(u) and u not in seen:
            seen.add(u); out.append(u)
    return out


def parse_profile(html: str, page_url: str) -> dict | None:
    """A portfolio PROFILE page → {name, website}: the name from the title / first heading, the website from the
    first external link whose anchor reads like a site link (else the first external link at all)."""
    own = http.registrable_domain(page_url)
    title = http.html_title(html)
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html or "")
    h1t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h1.group(1))).strip()) if h1 else ""
    slug = page_url.rstrip("/").rsplit("/", 1)[-1]
    slug_name = re.sub(r"[-_]+", " ", slug).strip().title()
    tseg = re.split(r"\s[|\-–—:]\s", title)[0].strip()
    tseg = re.sub(r"(?i)^(portfolio|company|companies)\s*[:\-–]\s*", "", tseg)
    # a heading that reads like a tagline (many words) is not the name; the slug or the title's first segment is
    fund_word = own.split(".")[0]
    if tseg and len(tseg.split()) <= 4 and fund_word not in tseg.lower():
        name = tseg
    elif h1t and len(h1t.split()) <= 3 and fund_word not in h1t.lower():
        name = h1t
    else:
        name = slug_name
    name = name[:80]
    ext = [(href, text, http.registrable_domain(href)) for href, text in http.links(html, page_url) if _external(http.registrable_domain(href), own)]
    key = re.sub(r"[^a-z0-9]", "", name.lower())[:6]
    def score(h, t, d):
        sc = 0
        dl = d.replace(".", "").replace("-", "")
        if key and (key in dl or dl[:5] in key):
            sc += 5                                      # the domain echoes the name
        if _VISIT.search(t or ""):
            sc += 3                                      # "Visit website" / "www."
        if re.search(r"(?i)\b(twitter|linkedin|facebook|instagram|press|article|news|podcast|blog|apply|careers)\b", t or ""):
            sc -= 3
        return sc
    ranked = sorted(ext, key=lambda x: -score(*x))
    pick = ranked[0] if ranked else None
    if not pick or not name or score(*pick) < 3:        # nothing on the page says this link is the company's site
        return None
    return {"name": name, "website": f"https://{pick[2]}", "domain": pick[2], "score": score(*pick), "candidates": [d for _, _, d in ranked[:4]]}
