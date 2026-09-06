"""SEC Form D bulk data sets → structured private-offering records (no model call).

Form D is the notice a US issuer files within 15 days of first selling securities in an exempt (private)
offering. The SEC publishes every filing as quarterly zips of TSV tables (index page:
https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets). This module downloads a quarter, joins
the tables by accession number, and yields ONE record per filing with the fields Startup Search uses:
issuer identity (CIK — permanent, legal name, previous names, city / state, entity type, incorporation year),
the offering (industry group, revenue range, amounts, first-sale date, amendment chain, pooled-fund flag) and
the related persons with their stated roles (executive officer / director / promoter — never founders).

Filters here are STRUCTURAL: pooled investment funds are excluded by the offering's own industry group and
fund flag, and by the issuer's entity type; a name-form check drops obvious fund / SPV vehicles. Whether a
residual issuer is an operating company is a judgment left to the resolver."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date

from . import http

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets"
_ZIP_HREF = re.compile(r'href="(/files/[^"]*form-d-data-sets/(\d{4})q([1-4])_d\.zip)"', re.I)
_FUND_FORM = re.compile(r"\b(fund|spv|l\.?p\.?|lp|holdings?|partners|capital|ventures|investments?|trust|reit|acquisition|opportunit|"
                        r"portfolio|series [a-z0-9]+ of|a series of|feeder|master|secondar|co-invest|coinvest)\b", re.I)
OPERATING_ENTITY_TYPES = {"corporation", "limited liability company", "business trust", "general partnership", "other"}
_OPERATING_INDUSTRIES = {"technology", "other technology", "biotechnology", "health care", "other health care", "pharmaceuticals",
                         "medical device", "energy", "other energy", "manufacturing", "retailing", "restaurants", "telecommunications",
                         "business services", "agriculture", "commercial", "construction", "coal mining", "electric utilities",
                         "energy conservation", "environmental services", "oil and gas", "other", "computers", "travel", "lodging",
                         "residential", "other real estate", "insurance", "investing", "other banking and financial services",
                         "commercial banking", "aerospace", "airlines and airports", "tourism"}


def list_quarters(since: tuple[int, int] = (2019, 1)) -> list[tuple[str, str]]:
    """[(label 'YYYYqN', absolute zip url)] from the SEC index page, newest first, filtered to >= `since`."""
    f = http.get(INDEX_URL, min_gap=0.5, respect_robots=False)
    if not f.ok:
        return []
    out = []
    for m in _ZIP_HREF.finditer(f.text):
        y, q = int(m.group(2)), int(m.group(3))
        if (y, q) >= since:
            out.append((f"{y}q{q}", "https://www.sec.gov" + m.group(1)))
    seen, uniq = set(), []
    for lab, url in out:
        if lab not in seen:
            seen.add(lab); uniq.append((lab, url))
    return uniq


def download_quarter(url: str) -> bytes | None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": http.UA, "Accept": "application/zip,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except Exception:   # noqa: BLE001
        return None


def _tables(zip_bytes: bytes) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1].upper()
            if not base.endswith(".TSV"):
                continue
            with z.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="ignore", newline="")
                rows = list(csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE))
            out[base[:-4]] = rows
    return out


def _money(v: str) -> float | None:
    v = (v or "").strip().replace(",", "")
    if not v or v.lower() in ("indefinite", "n/a"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _iso(v: str) -> str:
    """Form D dates come as DD-MON-YYYY or YYYY-MM-DD; normalise to ISO or ''."""
    v = (v or "").strip()
    if not v:
        return ""
    m = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})", v.upper())
    if m:
        mon = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}.get(m.group(2))
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    return m.group(0) if m else ""


def name_norm(s: str) -> str:
    """Legal-name normalisation for matching: lowercase, punctuation → space, legal-form suffixes stripped."""
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    toks = s.split()
    suffixes = {"inc", "incorporated", "llc", "l", "c", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "pbc",
                "lp", "llp", "the", "holdings", "technologies", "technology", "labs", "lab", "ai", "io", "com"}
    while toks and toks[-1] in suffixes:
        toks.pop()
    while toks and toks[0] == "the":
        toks.pop(0)
    return " ".join(toks)


def parse_quarter(zip_bytes: bytes) -> list[dict]:
    """One dict per filing (primary issuer), with `is_operating` = the structural pre-filter's verdict."""
    t = _tables(zip_bytes)
    subs = {r["ACCESSIONNUMBER"]: r for r in t.get("FORMDSUBMISSION", [])}
    offers = {r["ACCESSIONNUMBER"]: r for r in t.get("OFFERING", [])}
    persons: dict[str, list[dict]] = {}
    for r in t.get("RELATEDPERSONS", []):
        nm = " ".join(x for x in (r.get("FIRSTNAME", ""), r.get("MIDDLENAME", ""), r.get("LASTNAME", "")) if x and x != "N/A").strip()
        roles = [r.get(k, "") for k in ("RELATIONSHIP_1", "RELATIONSHIP_2", "RELATIONSHIP_3")]
        persons.setdefault(r["ACCESSIONNUMBER"], []).append({"name": nm, "roles": [x for x in roles if x],
                                                            "clarification": (r.get("RELATIONSHIPCLARIFICATION") or "")[:120]})
    out = []
    for iss in t.get("ISSUERS", []):
        if (iss.get("IS_PRIMARYISSUER_FLAG") or "").upper() != "YES":
            continue
        acc = iss["ACCESSIONNUMBER"]
        sub, off = subs.get(acc, {}), offers.get(acc, {})
        industry = (off.get("INDUSTRYGROUPTYPE") or "").strip()
        etype = (iss.get("ENTITYTYPE") or "").strip()
        pooled = (off.get("ISPOOLEDINVESTMENTFUNDTYPE") or "").lower() == "true" or industry.lower() == "pooled investment fund" \
            or bool((off.get("INVESTMENTFUNDTYPE") or "").strip())
        name = (iss.get("ENTITYNAME") or "").strip()
        fund_form = bool(_FUND_FORM.search(name))
        is_operating = (not pooled) and etype.lower() in OPERATING_ENTITY_TYPES and not fund_form \
            and (industry.lower() in _OPERATING_INDUSTRIES or not industry)
        prev = [iss.get(k, "") for k in ("ISSUER_PREVIOUSNAME_1", "ISSUER_PREVIOUSNAME_2", "ISSUER_PREVIOUSNAME_3",
                                          "EDGAR_PREVIOUSNAME_1", "EDGAR_PREVIOUSNAME_2", "EDGAR_PREVIOUSNAME_3")]
        year = (iss.get("YEAROFINC_VALUE_ENTERED") or "").strip()
        out.append({
            "accession": acc, "file_num": (sub.get("FILE_NUM") or "").strip(), "filing_date": _iso(sub.get("FILING_DATE", "")),
            "cik": (iss.get("CIK") or "").strip().lstrip("0"), "entity_name": name, "name_norm": name_norm(name),
            "previous_names": [p for p in prev if p and p != "N/A"],
            "city": (iss.get("CITY") or "").strip().title(), "state": (iss.get("STATEORCOUNTRY") or "").strip().upper(),
            "entity_type": etype, "year_inc": int(year) if year.isdigit() else None,
            "industry": industry, "revenue_range": (off.get("REVENUERANGE") or "").strip(),
            "is_amendment": (off.get("ISAMENDMENT") or "").lower() == "true",
            "previous_accession": (off.get("PREVIOUSACCESSIONNUMBER") or "").strip(),
            "sale_date": _iso(off.get("SALE_DATE", "")), "is_equity": (off.get("ISEQUITYTYPE") or "").lower() == "true",
            "offering_usd": _money(off.get("TOTALOFFERINGAMOUNT", "")), "sold_usd": _money(off.get("TOTALAMOUNTSOLD", "")),
            "investors_count": min(int(off["TOTALNUMBERALREADYINVESTED"]), 10**12) if (off.get("TOTALNUMBERALREADYINVESTED") or "").isdigit() else None,
            "is_pooled": pooled, "is_operating": is_operating, "officers": persons.get(acc, []),
        })
    return out


def render_summary(rec: dict) -> str:
    """The filing as a short text — the quote source for filing-backed facts."""
    parts = [f"SEC Form D{' (amendment)' if rec.get('is_amendment') else ''} filed {rec.get('filing_date') or 'n/a'} by {rec.get('entity_name')} "
             f"(CIK {rec.get('cik')}), {rec.get('entity_type') or 'entity'} in {rec.get('city')}, {rec.get('state')}."]
    if rec.get("industry"):
        parts.append(f"Industry group: {rec['industry']}.")
    if rec.get("revenue_range"):
        parts.append(f"Revenue range: {rec['revenue_range']}.")
    if rec.get("sold_usd") is not None:
        parts.append(f"Total amount sold: ${rec['sold_usd']:,.0f}" + (f" of ${rec['offering_usd']:,.0f} offered" if rec.get("offering_usd") else "") + ".")
    if rec.get("sale_date"):
        parts.append(f"Date of first sale: {rec['sale_date']}.")
    if rec.get("investors_count") is not None:
        parts.append(f"Investors so far: {rec['investors_count']}.")
    if rec.get("officers"):
        parts.append("Related persons: " + "; ".join(f"{p['name']} ({', '.join(p['roles'])})" for p in rec["officers"][:12]) + ".")
    return " ".join(parts)


def edgar_url(rec: dict) -> str:
    cik, acc = rec.get("cik", ""), rec.get("accession", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/" if cik and acc else "https://www.sec.gov/"


def today() -> date:
    return date.today()
