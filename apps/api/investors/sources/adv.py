"""SEC Form ADV bulk data → investor firms (no model call).

Every US investment adviser files Form ADV, and the SEC republishes the whole register monthly as two zipped
CSVs: *registered* advisers (~17k firms, 448 columns) and *exempt reporting advisers* (~6.7k, 171 columns).
The second file is the one that matters most here: the venture-capital adviser exemption is why most VC firms
are ERAs rather than RIAs. Measured 2026-09-09 on the September files: 7,424 firms flag at least one venture or
private-equity fund, 6,444 of them publish a website.

What this module reads per firm: identity (CRD — permanent, legal + business name, CIK), website, head office
city / state / country, entity form, employee count, **regulatory AUM**, the private-fund type flags and counts,
total gross private-fund assets, and the Item 11 disclosure counts. It makes no judgment: `investor_type` is
derived later, where fund sizes are also known.

Index page verified 200 on 2026-09-09:
https://www.sec.gov/data-research/sec-markets-data/information-about-registered-investment-advisers-exempt-reporting-advisers
"""
from __future__ import annotations

import csv
import io
import re
import zipfile

from api.startups.sources import http

INDEX_URL = ("https://www.sec.gov/data-research/sec-markets-data/"
             "information-about-registered-investment-advisers-exempt-reporting-advisers")
# ia09012026-exempt.zip / ia09012026-registered.zip / ia060126_0.zip — the SEC's naming has drifted over the
# years, so the shape is matched loosely and the *kind* is read off the filename, not assumed from position.
_ZIP_HREF = re.compile(r'href="(/files/[^"]*information-about-registered[^"]*/(ia[^"/]*\.zip))"', re.I)

# Item 11 disclosure questions. Their per-question counts are the filed compliance record; we sum them and link
# to the official IAPD report rather than characterising anything.
_DISCLOSURE_COLS = tuple(f"Count of {q} disclosures" for q in
                         ("11A(1)", "11A(2)", "11B(1)", "11B(2)", "11C(1)", "11C(2)", "11C(3)", "11C(4)",
                          "11C(5)", "11D(1)", "11D(2)", "11D(3)", "11D(4)", "11E(1)", "11E(2)", "11E(3)",
                          "11E(4)", "11F", "11G", "11H(1)(a)", "11H(1)(b)", "11H(1)(c)", "11H(2)"))

FUND_FLAGS = {"vc": "Any VC Funds", "pe": "Any PE Funds", "hedge": "Any Hedge Funds",
              "real_estate": "Any Real Estate Funds", "liquidity": "Any Liquidity Funds",
              "securitized": "Any Securitized Funds", "other": "Any Other Funds"}


def list_zips() -> list[tuple[str, str, str]]:
    """[(label, kind, absolute url)] newest first, where kind is 'registered' or 'exempt'."""
    f = http.get(INDEX_URL, min_gap=0.5, respect_robots=False)
    if not f.ok:
        return []
    out, seen = [], set()
    for m in _ZIP_HREF.finditer(f.text):
        href, base = m.group(1), m.group(2).lower()
        if base in seen:
            continue
        seen.add(base)
        kind = "exempt" if "exempt" in base else "registered"
        out.append((base[:-4], kind, "https://www.sec.gov" + href))
    return out


def latest_pair() -> list[tuple[str, str, str]]:
    """The newest registered zip and the newest exempt zip — the two files a full refresh needs."""
    zips = list_zips()
    out = []
    for kind in ("registered", "exempt"):
        got = next((z for z in zips if z[1] == kind), None)
        if got:
            out.append(got)
    return out


def download(url: str) -> bytes | None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": http.UA, "Accept": "application/zip,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    except Exception:      # noqa: BLE001 — a failed download is "no rows this run", never a crash
        return None


def _money(v: str) -> float | None:
    v = (v or "").strip().replace(",", "").replace("$", "")
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f if f >= 0 else None


def _int(v: str) -> int | None:
    v = (v or "").strip().replace(",", "")
    return int(v) if v.isdigit() else None


def rows(zip_bytes: bytes) -> list[dict]:
    """Raw CSV rows from the single CSV inside an ADV zip (latin-1: the SEC file is not UTF-8)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = [n for n in z.namelist() if n.upper().endswith(".CSV")]
        if not names:
            return []
        with z.open(names[0]) as fh:
            return list(csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1", newline="")))


def parse_firm(r: dict) -> dict | None:
    """One ADV row → a normalized firm record, or None when it carries no usable identity.

    `aum` prefers 5F(2)(c) — regulatory assets under management, the number the form defines — and falls back
    to total gross private-fund assets, which most ERAs report instead. The two are NOT the same measure, so
    the basis travels with the number and the card says which one it is showing.
    """
    from api.investors.store import domain_of
    crd = (r.get("Organization CRD#") or "").strip()
    name = (r.get("Primary Business Name") or r.get("Legal Name") or "").strip()
    if not crd or not name:
        return None
    raum, basis = _money(r.get("5F(2)(c)", "")), "adv_raum"
    if raum is None:
        raum, basis = _money(r.get("Total Gross Assets of Private Funds", "")), "adv_private_fund_assets"
    site = (r.get("Website Address") or "").strip()
    funds = {k: (r.get(col) or "").strip().upper() == "Y" for k, col in FUND_FLAGS.items()}
    return {
        "crd": crd,
        "cik": (r.get("CIK#") or "").strip().lstrip("0"),
        "name": name,
        "legal_name": (r.get("Legal Name") or "").strip(),
        "site": site if site.lower().startswith("http") else (f"https://{site}" if site else ""),
        "domain": domain_of(site),
        "firm_type": (r.get("Firm Type") or "").strip().upper(),          # ERA | RIA-ish
        "status": (r.get("SEC Current Status") or "").strip(),
        "hq_city": (r.get("Main Office City") or "").strip().title(),
        "hq_state": (r.get("Main Office State") or "").strip().upper(),
        "hq_country": (r.get("Main Office Country") or "").strip(),
        "entity_form": (r.get("3A") or "").strip(),
        "employees": _int(r.get("5A", "")),
        "aum": raum,
        "aum_basis": basis,
        "funds": funds,
        "fund_counts": {"vc": _int(r.get("Total number of VC funds", "")),
                        "pe": _int(r.get("Total number of PE funds", "")),
                        "all": _int(r.get("Count of Private Funds - 7B(1)", ""))},
        "disclosures": sum(_int(r.get(c, "")) or 0 for c in _DISCLOSURE_COLS),
        "latest_filing": (r.get("Latest ADV Filing Date") or "").strip(),
    }


def is_investor(f: dict) -> bool:
    """Does this adviser run the kind of fund this mode is about?

    Venture and private equity, yes. A pure hedge-fund or real-estate manager is a different asset class and is
    left out of the v1 population rather than padding the counts with firms a founder can never raise from.
    """
    return bool(f["funds"]["vc"] or f["funds"]["pe"])


def registers_of(f: dict) -> list[str]:
    return ["sec_era" if f.get("firm_type") == "ERA" else "sec_ria"]
