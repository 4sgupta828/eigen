"""PdlPeopleSearch — a PeopleSearchClient over People Data Labs' Person Search API.

The structured-precision leg (title / seniority / skills / current & past company) that complements Exa's
semantic reach. PDL is a LICENSED B2B dataset, so this is the compliant precision layer: results are the
person's public professional record, returned as ranking signal to reach out to — never evidence.

PDL Person Search is not natural-language; it takes an Elasticsearch query. We translate the freeform
expertise query into a `query_string` over the fields that carry expertise (title, company, skills,
summary), which lets the same PeopleSearchClient port drive it. No key ⇒ empty (reported as such).
"""
from __future__ import annotations

import os
import re

from .people_search import PersonResult

PDL_URL = "https://api.peopledatalabs.com/v5/person/search"

# Filler that carries no role — dropped before building the title query, so "heads of warehouse ops"
# searches on "warehouse operations", not the seniority filler "heads".
_STOP = frozenset("""of at a an the who whose which has have had in on for to and or with as is are be by
their our my your that this these those someone somebody people person could can will would should may
might not no mid market midmarket third party who've heads head lead leads leading senior junior vp svp
evp chief officer director manager head-of about looking find someone who""".split())


def _title_terms(query: str, k: int = 2) -> list[str]:
    seen: list[str] = []
    for t in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", (query or "").lower()):
        if t not in _STOP and t not in seen:
            seen.append(t)
    return seen[:k]


def _s(v) -> str:
    """PDL fields are usually strings but occasionally a bool/number/null — coerce safely so one odd
    record never breaks the whole parse."""
    return v.strip() if isinstance(v, str) else ""


def _parse(data: dict) -> list[PersonResult]:
    """PDL person records -> PersonResult. Pure, so the parsing is unit-tested without a live call.
    Defensive: any field may be a non-string, so coerce before use."""
    out: list[PersonResult] = []
    for r in ((data or {}).get("data") or []):
        if not isinstance(r, dict):
            continue
        name = _s(r.get("full_name")).title()
        li = _s(r.get("linkedin_url"))
        url = ("https://" + li) if (li and not li.startswith("http")) else li
        title, org = _s(r.get("job_title")), _s(r.get("job_company_name"))
        headline = " · ".join(x for x in (title, org) if x)[:200]
        skills = tuple(_s(s) for s in (r.get("skills") or [])[:8] if _s(s))
        if not name and not url:
            continue
        out.append(PersonResult(
            name=name or (url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()),
            profile_url=url, headline=headline, org=org, expertise=skills,
            location=_s(r.get("location_name"))[:120], provider="pdl"))
    return out


class PdlPeopleSearch:
    def __init__(self, *, api_key: str | None = None, timeout: float = 12.0):
        self._api_key = api_key or os.environ.get("PDL_API_KEY", "")
        self._timeout = timeout

    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]:
        if not self._api_key or not (query or "").strip():
            return []
        import httpx
        # PDL's ES subset is restricted (no query_string / minimum_should_match, and `match` is
        # AND-token) — a full sentence over-constrains it. PDL is the structured/breadth leg on a ROLE,
        # so search its title with the salient role terms via SQL LIKE (Exa beside it carries the
        # semantic precision of the whole ask). No usable terms → no query.
        terms = _title_terms(query)
        if not terms:
            return []
        where = " AND ".join("job_title LIKE '%%%s%%'" % t.replace("'", "") for t in terms)
        payload = {"sql": "SELECT * FROM person WHERE %s" % where,
                   "size": max(1, min(25, int(max_results))), "dataset": "all", "pretty": False}
        headers = {"X-Api-Key": self._api_key, "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(PDL_URL, json=payload, headers=headers)
                if resp.status_code == 404:      # PDL returns 404 when a search matches zero records
                    return []
                resp.raise_for_status()
                data = resp.json()
        except Exception:      # noqa: BLE001 — a provider error thins the composite, never 500s the leg
            return []
        try:
            return _parse(data)
        except Exception:      # noqa: BLE001 — one malformed record never takes down the whole leg
            return []
