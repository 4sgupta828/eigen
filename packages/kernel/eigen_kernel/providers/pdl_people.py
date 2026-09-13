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

from .people_search import PersonResult

PDL_URL = "https://api.peopledatalabs.com/v5/person/search"


def _parse(data: dict) -> list[PersonResult]:
    """PDL person records -> PersonResult. Pure, so the parsing is unit-tested without a live call."""
    out: list[PersonResult] = []
    for r in ((data or {}).get("data") or []):
        name = (r.get("full_name") or "").strip().title()
        li = (r.get("linkedin_url") or "").strip()
        url = ("https://" + li) if (li and not li.startswith("http")) else li
        title = (r.get("job_title") or "").strip()
        org = (r.get("job_company_name") or "").strip()
        headline = " · ".join(x for x in (title, org) if x)[:200]
        skills = tuple(s for s in (r.get("skills") or [])[:8] if s)
        if not name and not url:
            continue
        out.append(PersonResult(
            name=name or (url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()),
            profile_url=url, headline=headline, org=org, expertise=skills,
            location=(r.get("location_name") or "")[:120], provider="pdl"))
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
        # A query_string over the expertise-bearing fields turns the freeform ask into PDL's ES search.
        es = {"query": {"bool": {"must": [{"query_string": {
            "query": query, "default_operator": "and",
            "fields": ["job_title", "job_title_role", "job_company_name", "skills",
                       "summary", "headline", "industry"]}}]}}}
        payload = {"query": es["query"], "size": max(1, min(25, int(max_results))),
                   "dataset": "all", "pretty": False}
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
        return _parse(data)
