"""Derived facets — the computed keys, each with a `basis` the card shows (docs/specs/startup-search.md §3).

Pure functions over a company's financing events, filings, founders and roles → fact rows with provenance
'derived'. Rules: a stage is only a STATED round (basis stated_round); a Form D amount feeds `financing_scale`
(basis inferred_from_filing) and never stage; total disclosed funding sums one event per Form D file number
(amendments supersede) plus stated rounds not within 120 days of a filing; ARR is never derived here."""
from __future__ import annotations

from datetime import date

from .schema import FORMD_REVENUE, STAGES

_WINDOW_DAYS = 120


def _latest(evs: list[dict], key: str = "event_date"):
    dated = [e for e in evs if e.get(key)]
    return max(dated, key=lambda e: e[key]) if dated else (evs[-1] if evs else None)


def _d(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


# Two-letter subdivisions we can read with confidence. A code we do not know is left alone rather
# than invented: "Washington, DC" is a place, "Cambridge, UK" is not a state, and guessing either
# would put a company in a jurisdiction it is not in.
US_STATES = {"al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky",
             "la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd",
             "oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc"}
CA_PROVINCES = {"ab","bc","mb","nb","nl","ns","nt","nu","on","pe","qc","sk","yt"}


# Countries whose presence in an HQ string means a US or Canadian filing address is not where the
# company is. Cheap and deliberately partial: it only has to catch the common non-US HQs we hold.
_ELSEWHERE = ("uk", "united kingdom", "india", "germany", "france", "singapore", "israel", "spain",
              "netherlands", "australia", "brazil", "mexico", "japan", "china", "sweden", "ireland",
              "switzerland", "poland", "nigeria", "kenya", "indonesia", "argentina", "chile", "colombia")


def _hq_is_elsewhere(hq: str) -> bool:
    last = [p.strip().lower() for p in str(hq or "").split(",")][-1:] or [""]
    return any(last[0] == c or last[0].endswith(" " + c) for c in _ELSEWHERE)


def state_of(hq: str) -> str:
    """The state or province an HQ string states, or "".

    HQ strings arrive as "San Francisco, CA, USA" or "Toronto, ON, Canada" — the subdivision is the
    middle field. Only codes we recognise are accepted, so a European city with a two-letter region
    abbreviation does not become a US state.
    """
    parts = [p.strip().lower() for p in str(hq or "").split(",")]
    for p in parts[1:]:
        code = p.replace(".", "")
        if len(code) == 2 and (code in US_STATES or code in CA_PROVINCES):
            return code
    return ""


def derive_facts(company: dict, financing: list[dict], filings: list[dict], founders: list[dict], roles: list[dict],
                 role_functions: dict[str, str], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    facts: list[dict] = []
    # WHERE they are, at the level people actually say. The HQ string states it ("San Francisco, CA,
    # USA"), and for a filing-backed company so does the filing itself — two independent sources for
    # the same jurisdiction, and neither is guessed when the text does not carry one.
    hq = str(company.get("hq") or "")
    st = state_of(hq)
    if not st and not _hq_is_elsewhere(hq):
        # A Form D states the issuer's business address, and the distribution says it is a real one
        # (California 2,483, New York 1,099, Delaware only 258 — incorporation states would invert
        # that). It is used only when the HQ does not already place the company in another country,
        # so a London company does not acquire a US state from a filing.
        for f in (filings or []):
            code = str(f.get("state") or "").strip().lower()
            if code in US_STATES or code in CA_PROVINCES:
                st = code
                break
    if st:
        facts.append({"key": "state", "value": st, "basis": "hq_or_filing",
                      "quote": (company.get("hq") or "").strip()[:120] or f"state on the SEC filing: {st.upper()}",
                      "confidence": 0.9})

    fin = [dict(e, event_date=_d(e.get("event_date"))) for e in financing]
    formd = [dict(f, sale_date=_d(f.get("sale_date")), filing_date=_d(f.get("filing_date"))) for f in filings]

    # --- financing events: one per Form D file number (latest amendment wins), plus stated rounds not covered by a filing
    by_file: dict[str, dict] = {}
    for f in formd:
        fn = f.get("file_num") or f.get("accession")
        cur = by_file.get(fn)
        if cur is None or (f.get("filing_date") or date.min) >= (cur.get("filing_date") or date.min):
            by_file[fn] = f
    filing_events = [{"kind": "formd", "amount": f.get("sold_usd"), "date": f.get("sale_date") or f.get("filing_date"), "src": f} for f in by_file.values()]
    # one stated event per (round, amount) across press + site (several sources report the same round)
    stated, seen = [], set()
    for e in sorted((e for e in fin if e.get("kind") in ("press", "site")), key=lambda e: (e.get("event_date") is None, e.get("event_date") or date.max)):
        k = (e.get("round_name") or "", round(float(e["amount_usd"]) / 1e5) if e.get("amount_usd") else None)
        if k in seen and (k[0] or k[1] is not None):
            continue
        seen.add(k); stated.append(e)
    stated_events = []
    for e in stated:
        d = e.get("event_date")
        covered = any(d and fe["date"] and abs((d - fe["date"]).days) <= _WINDOW_DAYS for fe in filing_events)
        if not covered:
            stated_events.append({"kind": e["kind"], "amount": e.get("amount_usd"), "date": d, "src": e})
    events = filing_events + stated_events
    amounts = [e["amount"] for e in events if e.get("amount")]
    if amounts:
        total = float(sum(amounts))
        n_f, n_s = len([e for e in filing_events if e.get("amount")]), len([e for e in stated_events if e.get("amount")])
        facts.append({"key": "total_disclosed_funding", "number": total, "display": _usd(total),
                      "basis": "filings_and_stated_rounds" if (n_f and n_s) else ("filings" if n_f else "stated_rounds"),
                      "quote": f"{n_f} filing event(s) + {n_s} stated round(s) not matched to a filing", "as_of": today})
    latest = _latest([e for e in events if e.get("date")], "date")
    if latest and latest.get("amount"):
        facts.append({"key": "last_round_amount", "number": float(latest["amount"]), "display": _usd(latest["amount"]),
                      "basis": "filing" if latest["kind"] == "formd" else "stated_round", "quote": _quote_of(latest), "as_of": latest["date"],
                      "source_url": _url_of(latest)})
    if latest and latest.get("date"):
        months = (today - latest["date"]).days / 30.44
        facts.append({"key": "last_round_months", "number": round(months, 1), "display": f"{months:.0f} months ago",
                      "basis": "filing" if latest["kind"] == "formd" else "stated_round", "quote": _quote_of(latest), "as_of": latest["date"], "source_url": _url_of(latest)})

    # --- stage: stated round only
    rounds = [e for e in fin if e.get("round_name") in STAGES]
    if rounds:
        r = _latest(rounds)
        facts.append({"key": "stage", "value": r["round_name"], "basis": "stated_round", "quote": r.get("quote") or "", "source_url": r.get("source_url") or "",
                      "as_of": r.get("event_date"), "display": r["round_name"].replace("_", " ")})

    # --- latest filing: financing scale + revenue range
    lf = _latest([f for f in formd if f.get("sale_date") or f.get("filing_date")], "filing_date") if formd else None
    if lf:
        if lf.get("sold_usd"):
            facts.append({"key": "financing_scale", "number": float(lf["sold_usd"]), "display": _usd(lf["sold_usd"]), "basis": "inferred_from_filing",
                          "quote": f"Total amount sold: {_usd(lf['sold_usd'])} (Form D {lf.get('accession')})", "as_of": lf.get("sale_date") or lf.get("filing_date"),
                          "source_url": lf.get("source_url") or ""})
        rr = FORMD_REVENUE.get((lf.get("revenue_range") or "").strip().lower())
        if rr:
            facts.append({"key": "revenue_range", "value": rr, "basis": "filing_range", "quote": f"Revenue range: {lf.get('revenue_range')} (Form D {lf.get('accession')})",
                          "as_of": lf.get("filing_date"), "source_url": lf.get("source_url") or "", "display": lf.get("revenue_range") or ""})

    # --- investors from stated rounds (lead / participant)
    for e in stated:
        for inv in (e.get("investors") or []):
            facts.append({"key": "investor", "value": inv, "basis": "stated_round", "quote": e.get("quote") or "", "source_url": e.get("source_url") or "", "as_of": e.get("event_date")})
        if e.get("lead"):
            facts.append({"key": "lead_investor", "value": e["lead"], "basis": "stated_round", "quote": e.get("quote") or "", "source_url": e.get("source_url") or "", "as_of": e.get("event_date")})

    # --- founders
    if founders:
        facts.append({"key": "founder_count", "number": float(len(founders)), "display": str(len(founders)), "basis": "named_founders",
                      "quote": "; ".join(f"{f.get('name')} ({f.get('title') or 'founder'})" for f in founders[:6]), "source_url": (founders[0].get("source_url") or ""), "as_of": today})
        for f in founders:
            for pc in (f.get("prior_companies") or []):
                facts.append({"key": "founder_prior_company", "value": pc, "basis": "stated", "quote": f.get("quote") or "", "source_url": f.get("source_url") or "", "as_of": today})

    # --- hiring from the ATS board
    if roles:
        facts.append({"key": "hiring", "number": float(len(roles)), "display": f"{len(roles)} open role" + ("" if len(roles) == 1 else "s"), "basis": "ats_board",
                      "quote": "; ".join((r.get("title") or "")[:60] for r in roles[:8]), "source_url": (roles[0].get("url") or ""), "as_of": today})
        fns = sorted({fn for fn in role_functions.values()})
        for fn in fns:
            ex = [r for r in roles if role_functions.get(_n(r.get("title") or "")) == fn]
            facts.append({"key": "hiring_function", "value": fn, "basis": "ats_board", "quote": "; ".join((r.get("title") or "")[:60] for r in ex[:5]),
                          "source_url": (ex[0].get("url") if ex else "") or "", "as_of": today})

    # --- evidence strength for the funding facts
    kinds = {e["kind"] for e in events if e.get("amount")}
    if kinds:
        strength = "filing_backed" if "formd" in kinds else ("two_sources" if len(kinds) >= 2 else "single_source")
        facts.append({"key": "evidence_strength", "value": strength, "basis": "derived", "quote": "funding facts backed by: " + ", ".join(sorted(kinds)), "as_of": today})
    return facts


def _n(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s.strip().lower())


def _usd(x) -> str:
    x = float(x or 0)
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:.0f}"


def _quote_of(e: dict) -> str:
    s = e.get("src") or {}
    if e.get("kind") == "formd":
        return f"Total amount sold: {_usd(s.get('sold_usd'))}; date of first sale {s.get('sale_date')} (Form D {s.get('accession')})"
    return s.get("quote") or ""


def _url_of(e: dict) -> str:
    s = e.get("src") or {}
    return s.get("source_url") or ""
