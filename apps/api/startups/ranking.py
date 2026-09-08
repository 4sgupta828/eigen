"""Rank a result set by something an investor, a founder or a job seeker actually asks for.

Relevance answers "who matches my words". It does not answer "who raised the most", "who is hiring
hardest" or "who has been at this longest", and those are the questions that make a list navigable.

Two rules hold for every sort here:

* **A company missing the field is never silently dropped.** It sorts last, and the response says how
  many rows could not be ranked. A "top by funding" list that quietly hides 8,600 companies with no
  funding on record would misrepresent the index as much as a wrong number would.
* **Nothing is invented to fill a sort.** There is no profitability sort, because we hold profit for
  nobody; the closest real signals are the Form D revenue band (511 companies) and self-reported ARR
  (29), and both are offered under their own names rather than dressed up as profitability.
"""
from __future__ import annotations

# key → (label, fact key, direction, what it means)
SORTS: dict[str, dict] = {
    "relevance":     {"label": "Best match", "field": None, "desc": True,
                      "why": "how well the company answers your words and filters"},
    "funding":       {"label": "Most raised", "field": "total_disclosed_funding", "desc": True,
                      "why": "total disclosed funding, from filings and stated rounds"},
    "last_round":    {"label": "Biggest last round", "field": "last_round_amount", "desc": True,
                      "why": "the size of the most recent round on record"},
    "recent_money":  {"label": "Funded most recently", "field": "last_round_months", "desc": False,
                      "why": "months since the last round — fewest first"},
    "hiring":        {"label": "Hiring hardest", "field": "hiring", "desc": True,
                      "why": "open roles on their job board right now"},
    "youngest":      {"label": "Newest", "field": "founded", "desc": True,
                      "why": "year founded — newest first"},
    "oldest":        {"label": "Longest running", "field": "founded", "desc": False,
                      "why": "year founded — oldest first"},
    "team":          {"label": "Largest team", "field": "headcount", "desc": True,
                      "why": "headcount on record"},
    "revenue":       {"label": "Revenue on record", "field": "revenue_range", "desc": True,
                      "why": "the revenue band a Form D filing states — few companies file one"},
}


def numeric_of(row: dict, field: str) -> float | None:
    """The number a row carries for a fact key, or None when it holds none."""
    if not field:
        return None
    n = (row.get("numeric") or {}).get(field)
    if isinstance(n, (int, float)):
        return float(n)
    for f in ((row.get("company") or {}).get("facts") or []):
        if f.get("key") == field and isinstance(f.get("number"), (int, float)):
            return float(f["number"])
    return None


def apply(rows: list[dict], sort: str) -> dict:
    """Reorder in place-ish and report what could not be ranked. Unknown sort → unchanged."""
    spec = SORTS.get(sort or "relevance")
    if not spec or not spec["field"]:
        return {"sort": "relevance", "ranked": len(rows), "unranked": 0}
    field, desc = spec["field"], spec["desc"]
    known, unknown = [], []
    for r in rows:
        (known if numeric_of(r, field) is not None else unknown).append(r)
    known.sort(key=lambda r: (numeric_of(r, field) or 0.0, -float(r.get("score") or 0.0)),
               reverse=desc)
    # A row we cannot rank keeps its relevance order and goes last — present, and visibly unranked.
    rows[:] = known + unknown
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["unranked"] = r in unknown if False else None
    for r in unknown:
        r["unranked"] = True
    return {"sort": sort, "field": field, "ranked": len(known), "unranked": len(unknown)}


def options() -> list[dict]:
    """What the UI offers, with the honest description of each."""
    return [{"key": k, "label": v["label"], "why": v["why"]} for k, v in SORTS.items()]
