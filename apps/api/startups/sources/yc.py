"""Y Combinator directory → companies + founders (public, search-only Algolia index; no model call).

The directory (ycombinator.com/companies) is a React app over a public Algolia index whose read-only key is
embedded client-side. We page the index per batch (Algolia caps a query at 1,000 hits) and read each company's
public detail page for its founders (Inertia JSON in `data-page`). Fields are read verbatim; the closed YC
industry labels map to our `tech_area` by lookup."""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse

from . import http
from ..schema import area_from_yc_industries

_APP_ID = "45BWZJ1SGC"
_API_KEY = ("NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFu"
            "YWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlf"
            "QnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE")
_SEARCH = f"https://{_APP_ID}-dsn.algolia.net/1/indexes/YCCompany_production"
_DETAIL = "https://www.ycombinator.com/companies/{slug}"
_HDR = {"X-Algolia-Application-Id": _APP_ID, "X-Algolia-API-Key": _API_KEY}
_STATUS = {"active": "active", "public": "public", "acquired": "acquired", "inactive": "shut_down"}


def _get(url: str):
    import urllib.request
    req = urllib.request.Request(url, headers={**_HDR, "User-Agent": http.UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def batches() -> list[str]:
    d = _get(f"{_SEARCH}?query=&hitsPerPage=1&facets=%5B%22batch%22%5D")
    return sorted((d.get("facets") or {}).get("batch", {}).keys())


def companies_in_batch(batch: str) -> list[dict]:
    out, page = [], 0
    while True:
        params = {"query": "", "hitsPerPage": "1000", "page": str(page), "facetFilters": json.dumps([f"batch:{batch}"])}
        d = _get(f"{_SEARCH}?{urllib.parse.urlencode(params)}")
        hits = [h for h in (d.get("hits") or []) if isinstance(h, dict)]
        out += hits
        if not hits or page + 1 >= int(d.get("nbPages") or 1):
            break
        page += 1
    return out


def detail(slug: str) -> dict:
    f = http.get(_DETAIL.format(slug=urllib.parse.quote(slug)), min_gap=1.0, respect_robots=False)
    if not f.ok:
        return {}
    m = re.search(r'data-page="(.*?)"\s*>', f.text, re.S)
    if not m:
        return {}
    try:
        page = json.loads(_html.unescape(m.group(1)))
    except Exception:   # noqa: BLE001
        return {}
    comp = ((page.get("props") or {}).get("company")) or {}
    return comp if isinstance(comp, dict) else {}


def to_company(rec: dict) -> dict | None:
    """Algolia / detail record → su_company row + structured facts (provenance 'yc')."""
    website = str(rec.get("website") or "").strip()
    slug = str(rec.get("slug") or "").strip()
    if not website or not slug:
        return None
    cid = http.registrable_domain(website)
    if not cid or "." not in cid or cid.endswith(("ycombinator.com", "linkedin.com", "twitter.com", "github.com")):
        return None
    src_url = _DETAIL.format(slug=slug)
    inds = [str(x) for x in (rec.get("industries") or []) if x] or [str(rec.get("industry") or "")]
    status = _STATUS.get(str(rec.get("status") or "").lower(), "active")
    facts: list[dict] = [{"key": "program", "value": "yc", "quote": f"{rec.get('name')} — Y Combinator {rec.get('batch')}", "source_url": src_url, "display": str(rec.get("batch") or "")},
                         {"key": "status", "value": status, "quote": f"Status: {rec.get('status')}", "source_url": src_url}]
    for a in area_from_yc_industries(inds):
        facts.append({"key": "tech_area", "value": a, "quote": "Industries: " + ", ".join(inds), "source_url": src_url, "confidence": 0.6})
    ts = rec.get("team_size")
    if isinstance(ts, (int, float)) and ts > 0:
        facts.append({"key": "headcount", "number": float(ts), "display": str(int(ts)), "quote": f"Team size: {int(ts)}", "source_url": src_url})
    yr = rec.get("year_founded")
    if isinstance(yr, (int, float)) and 1990 < yr < 2100:
        facts.append({"key": "founded", "number": float(yr), "display": str(int(yr)), "quote": f"Founded: {int(yr)}", "source_url": src_url})
    loc = str(rec.get("all_locations") or rec.get("location") or "").strip()
    for key, val in _geo(loc):
        facts.append({"key": key, "value": val, "quote": f"Location: {loc}", "source_url": src_url})
    founders = []
    for f in (rec.get("founders") or []):
        if not isinstance(f, dict):
            continue
        name = str(f.get("full_name") or f.get("name") or "").strip()
        if name:
            founders.append({"name": name, "title": str(f.get("title") or "")[:120], "prior_companies": [], "source_url": src_url,
                             "quote": f"{name}, {f.get('title') or 'founder'} — Y Combinator company profile"})
    company = {"id": cid, "name": str(rec.get("name") or "").strip(), "website": website, "one_liner": str(rec.get("one_liner") or "").strip(),
               "description": str(rec.get("long_description") or "").strip()[:4000], "hq": loc, "yc_slug": slug, "yc_batch": str(rec.get("batch") or ""),
               "aliases": [str(x) for x in (rec.get("former_names") or []) if x], "sources": ["yc"]}
    return {"company": company, "facts": facts, "founders": founders, "is_hiring": bool(rec.get("isHiring"))}


_METROS = (("san francisco", "bay_area"), ("palo alto", "bay_area"), ("mountain view", "bay_area"), ("menlo park", "bay_area"), ("redwood city", "bay_area"),
           ("san mateo", "bay_area"), ("sunnyvale", "bay_area"), ("san jose", "bay_area"), ("berkeley", "bay_area"), ("oakland", "bay_area"),
           ("new york", "new_york"), ("brooklyn", "new_york"), ("los angeles", "los_angeles"), ("santa monica", "los_angeles"), ("boston", "boston"),
           ("cambridge, ma", "boston"), ("seattle", "seattle"), ("austin", "austin"), ("london", "london"), ("chicago", "chicago"), ("denver", "denver"),
           ("boulder", "denver"), ("miami", "miami"), ("toronto", "toronto"), ("bangalore", "bangalore"), ("bengaluru", "bangalore"), ("paris", "paris"),
           ("berlin", "berlin"), ("tel aviv", "tel_aviv"), ("singapore", "singapore"), ("washington", "dc"), ("atlanta", "atlanta"), ("san diego", "san_diego"))
_COUNTRIES = (("usa", "us"), ("united states", "us"), ("united kingdom", "uk"), ("england", "uk"), ("canada", "ca"), ("india", "in"), ("germany", "de"),
              ("france", "fr"), ("israel", "il"), ("singapore", "sg"), ("australia", "au"), ("brazil", "br"), ("mexico", "mx"), ("netherlands", "nl"),
              ("spain", "es"), ("sweden", "se"), ("switzerland", "ch"), ("ireland", "ie"), ("japan", "jp"), ("south korea", "kr"), ("nigeria", "ng"))


def _geo(loc: str) -> list[tuple[str, str]]:
    """Location string → (country, metro) tokens by lookup (structural; a US state code alone implies us)."""
    l = loc.lower()
    out: list[tuple[str, str]] = []
    for needle, code in _COUNTRIES:
        if needle in l:
            out.append(("country", code)); break
    else:
        if re.search(r",\s*[A-Z]{2}(\s|,|$)", loc):
            out.append(("country", "us"))
    for needle, metro in _METROS:
        if needle in l:
            out.append(("metro", metro)); break
    return out
