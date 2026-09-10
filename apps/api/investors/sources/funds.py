"""SEC Form D → the fund VEHICLES (no model call).

The same quarterly zips the startup module already downloads carry the other side of the market: when a venture
firm raises a fund, the fund itself files a Form D. That filing states the fund's legal name, **the fund type
the filer chose** (Venture Capital Fund · Private Equity Fund · Hedge Fund · Other Investment Fund), the amount
offered and the amount **sold**, the date of first sale (the vintage), how many investors have come in, the
minimum investment accepted, the manager's city and state, and the related persons — who are the GPs.

The startup module reads these tables already, but it consumes the fund fields only as a boolean, to *exclude*
funds from the company population (`api/startups/sources/formd.py:135`): the type string itself is thrown away
and `MINIMUMINVESTMENTACCEPTED` is never read. So this module re-parses the quarters keeping what that one
discards. Nothing here costs credits — it is bandwidth and CPU.
"""
from __future__ import annotations

import re

from api.startups.sources.formd import _iso, _money, _tables, download_quarter, list_quarters  # noqa: F401

FUND_TYPES = ("Venture Capital Fund", "Private Equity Fund", "Hedge Fund", "Other Investment Fund")

# A per-deal vehicle, not a fund. Measured on 2026Q2: 1,763 of 2,983 filings typed "Venture Capital Fund"
# (59%) match this — "… a Series of X LLC", "OurCrowd (Investment in Morphisec) LP", "Anthropic SPV I".
# Letting them through does not merely add noise: their administrators sign hundreds of filings each and
# become the hubs that collapse GP clustering (see `cluster.py`).
SPV_NAME = re.compile(r"(?i)(\ba series of\b|,\s*a series\b|\bseries\s+[a-z0-9\-]+\s+of\b|\bspv\b|"
                      r"\bco-?invest\w*\b|\(investment in [^)]+\)|\bfeeder\b|\bsidecar\b|"
                      # A TRAILING series designation is the same thing said the other way round:
                      # "Okeanos Venture Partners II, LLC - Series 106" is one numbered cell of one fund, and
                      # counting its 70 siblings as 70 funds put Okeanos above Apollo. 3,603 vehicles in prod.
                      r"[-,]\s*series\s+[a-z0-9]+\s*$)")


def is_spv(name: str) -> bool:
    return bool(SPV_NAME.search(name or ""))


def parse_quarter(zip_bytes: bytes, *, quarter: str = "") -> list[dict]:
    """One dict per POOLED-FUND filing in the quarter. Operating-company filings are the other module's job."""
    t = _tables(zip_bytes)
    subs = {r["ACCESSIONNUMBER"]: r for r in t.get("FORMDSUBMISSION", [])}
    offers = {r["ACCESSIONNUMBER"]: r for r in t.get("OFFERING", [])}
    persons: dict[str, list[dict]] = {}
    for r in t.get("RELATEDPERSONS", []):
        nm = " ".join(x for x in (r.get("FIRSTNAME", ""), r.get("MIDDLENAME", ""), r.get("LASTNAME", ""))
                      if x and x != "N/A").strip()
        if not nm:
            continue
        roles = [r.get(k, "") for k in ("RELATIONSHIP_1", "RELATIONSHIP_2", "RELATIONSHIP_3")]
        # Deliberately NOT kept: the related person's street address, which Form D also carries. A GP's name
        # and stated role are the public fact this mode needs; their address is not, and dropping it at parse
        # time rather than at render time is the difference between a policy and a promise.
        persons.setdefault(r["ACCESSIONNUMBER"], []).append({"name": nm, "roles": [x for x in roles if x]})
    out = []
    for iss in t.get("ISSUERS", []):
        if (iss.get("IS_PRIMARYISSUER_FLAG") or "").upper() != "YES":
            continue
        acc = iss["ACCESSIONNUMBER"]
        sub, off = subs.get(acc, {}), offers.get(acc, {})
        ftype = (off.get("INVESTMENTFUNDTYPE") or "").strip()
        pooled = (off.get("ISPOOLEDINVESTMENTFUNDTYPE") or "").lower() == "true" \
            or (off.get("INDUSTRYGROUPTYPE") or "").strip().lower() == "pooled investment fund" or bool(ftype)
        if not pooled:
            continue
        name = (iss.get("ENTITYNAME") or "").strip()
        file_num = (sub.get("FILE_NUM") or "").strip()
        out.append({
            "id": file_num or acc,
            "file_num": file_num,
            "accession": acc,
            "cik": (iss.get("CIK") or "").strip().lstrip("0"),
            "name": name,
            "fund_type": ftype,
            "offered_usd": _money(off.get("TOTALOFFERINGAMOUNT", "")),
            "sold_usd": _money(off.get("TOTALAMOUNTSOLD", "")),
            "min_investment": _money(off.get("MINIMUMINVESTMENTACCEPTED", "")),
            "first_sale": _iso(off.get("SALE_DATE", "")),
            "filing_date": _iso(sub.get("FILING_DATE", "")),
            "investors_n": int(off["TOTALNUMBERALREADYINVESTED"])
            if (off.get("TOTALNUMBERALREADYINVESTED") or "").isdigit() else None,
            "city": (iss.get("CITY") or "").strip().title(),
            "state": (iss.get("STATEORCOUNTRY") or "").strip().upper(),
            "persons": persons.get(acc, []),
            "is_spv": is_spv(name),
            "is_amendment": (off.get("ISAMENDMENT") or "").lower() == "true",
            "quarter": quarter,
        })
    return out


def venture_or_pe(f: dict) -> bool:
    return f.get("fund_type") in ("Venture Capital Fund", "Private Equity Fund")
