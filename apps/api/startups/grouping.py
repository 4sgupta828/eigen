"""Group a startup result set — the dimensions, and the model's segmentation prompt.

Ported from roster's pattern, which is deliberate: the same two mechanisms, and the same discipline
about which one is allowed to cost anything.

**Facet grouping is free and default.** A dimension's value is the group key, and a dimension only
appears in the menu when it would actually split THIS result set — measured on the rows returned,
never on the index. The kernel's `eligible` holds the rules: too many unknowns, one dominant group,
or too many groups and the dimension is not offered.

**Auto is one model call, only when asked.** It segments by what the companies DO, and it is given
neither the sector, the city, the investors nor the stage — the facets can already group by those,
so a model that segmented by them would just be an expensive duplicate of a free control.
"""
from __future__ import annotations

# (key, label, source, kind) — `source` reads the row, `kind` picks the eligibility rule.
# identity dimensions (metro, investor) want CONCENTRATION: a few values that repeat.
# categorical dimensions want BALANCE: several groups of comparable size.
GROUP_DIMENSIONS: list[tuple[str, str, str, str]] = [
    ("auto",           "Auto",            "",                      "auto"),
    ("tech_area",      "What they build",  "facet:tech_area",      "categorical"),
    ("business_model", "How they charge",  "facet:business_model", "categorical"),
    ("stage",          "Stage",            "facet:stage",          "categorical"),
    ("program",        "Accelerator",      "facet:program",        "categorical"),
    ("metro",          "Where they are",   "facet:metro",          "identity"),
    ("investor",       "Who backed them",  "facet:investor",       "identity"),
    ("funding_band",   "How much raised",  "derived:funding_band", "categorical"),
    ("age_band",       "How old",          "derived:age_band",     "categorical"),
]

# Bands are round numbers a reader already thinks in, not quantiles of our index — a quantile moves
# when the corpus grows, so yesterday's "top band" would quietly mean something else today.
FUNDING_BANDS = ((1_000_000, "under $1M"), (5_000_000, "$1M–5M"), (20_000_000, "$5M–20M"),
                 (100_000_000, "$20M–100M"), (float("inf"), "$100M+"))
AGE_BANDS = ((2, "under 2 years"), (5, "2–5 years"), (10, "5–10 years"), (float("inf"), "10+ years"))


def _num(row: dict, key: str):
    n = (row.get("numeric") or {}).get(key)
    if isinstance(n, (int, float)):
        return float(n)
    for f in ((row.get("company") or {}).get("facts") or []):
        if f.get("key") == key and isinstance(f.get("number"), (int, float)):
            return float(f["number"])
    return None


def values_for(row: dict, source: str, *, this_year: int) -> list[str]:
    """The group keys this row carries for a dimension. Empty means "not stated" — never a guess."""
    if source.startswith("facet:"):
        key = source.split(":", 1)[1]
        vals = (row.get("facets") or {}).get(key) or []
        return [str(v) for v in vals if v]
    if source == "derived:funding_band":
        n = _num(row, "total_disclosed_funding")
        if n is None:
            return []
        return [next(label for cap, label in FUNDING_BANDS if n < cap)]
    if source == "derived:age_band":
        y = _num(row, "founded")
        if y is None or y < 1900:
            return []
        age = max(0, this_year - int(y))
        return [next(label for cap, label in AGE_BANDS if age < cap)]
    return []


def row_line(i: int, row: dict) -> str:
    """One line per company for the model: what it DOES, and nothing it could segment by for free.

    Sector, city, stage and investors are all deliberately absent. The facet controls already group
    by them, so letting the model reach for them would spend a call to reproduce a free control.
    """
    co = row.get("company") or {}
    bits = [str(co.get("name") or row.get("id") or "")]
    if co.get("one_liner"):
        bits.append(str(co["one_liner"])[:150])
    return f"{i}| " + " · ".join(b for b in bits if b)


def segment_prompt(max_groups: int = 7) -> str:
    return (
        "You segment a list of startups the way an INVESTOR reads a market map: by WHAT THE COMPANY "
        "DOES and WHO IT DOES IT FOR — the shape of the business, not its label.\n"
        "Good cuts look like: developer infrastructure · vertical software for clinics · fraud and "
        "risk tooling · robotics for warehouses · consumer health · data platforms for banks.\n"
        "RULES\n"
        f"- Between 3 and {max_groups} groups. Order them largest first.\n"
        "- Never segment by funding stage, city, investor, accelerator or company size. The reader "
        "can already group by those, and a group that repeats one of them is wasted.\n"
        "- Never make a group out of a word nearly every row shares — that word is the search itself.\n"
        "- Every id belongs to at most one group. MOST companies should land in one: leaving a few "
        "out is fine, leaving half the list out is a segmentation that did not do its job. Prefer a "
        "slightly broader group to a large leftover pile, but never force a company somewhere it "
        "plainly does not belong.\n"
        "- name: 2 to 4 words a reader would recognise. why: at most 8 words, what the group has in "
        "common.\n"
        'Return ONLY JSON: {"groups":[{"name":str,"why":str,"ids":[int]}]}'
    )


def resegment_prompt(dominant_name: str, n: int, total: int, max_groups: int = 7) -> str:
    return (segment_prompt(max_groups)
            + f"\nYour previous answer put {n} of {total} companies in \"{dominant_name}\". That is a "
              "list, not a segmentation. No group may hold more than half the rows — find the real "
              "differences inside the big one.")
