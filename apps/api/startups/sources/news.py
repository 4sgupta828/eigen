"""Funding NEWS — the web leg for what sites rarely state: round name, amount, lead and participating investors.

Press is frequently changing and not downloadable, so this is the one source Startup Search reads at query
time through a search API (Brave, key in the environment): one query per company, the top results' titles
and snippets ("Acme raises $12M Series A led by …") go to the model in batches, and every financing event it
returns must quote a title or snippet VERBATIM (checked in code) with the figure and the round word inside
the quote. Provenance 'press'; the article URL is the source. A company with no funding headline yields
nothing — never a guess."""
from __future__ import annotations

import json
import os
import re

from ..extract import _ROUND, _slug, figure_in_quote, norm, parse_money

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_STOP = ("raises", "raised", "funding", "series", "seed", "round", "led by", "investment", "valuation")


def _clean(t) -> str:
    """Brave marks matches with <strong> and elides with …; the quote gate compares plain text."""
    import html as _html
    t = re.sub(r"<[^>]+>", "", str(t or ""))
    t = _html.unescape(t).replace("\u2026", " ").replace("...", " ")
    return re.sub(r"\s+", " ", t).strip()


def brave_funding_news(name: str, website: str = "", *, api_key: str | None = None, max_results: int = 10, timeout: float = 12.0) -> list[dict]:
    """[{title, snippet, url, published}] for a funding query about the company (sync; the job runs it in a thread)."""
    key = api_key or os.environ.get("BRAVE_API_KEY", "")
    if not key or not name:
        return []
    import httpx
    q = f'"{name}" (raises OR raised OR funding OR "Series A" OR "Series B" OR seed OR "led by")'
    params = {"q": q, "count": max(1, min(int(max_results), 20)), "result_filter": "web,news", "freshness": "py"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(BRAVE_URL, params=params, headers={"X-Subscription-Token": key, "Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:   # noqa: BLE001 — a failed query contributes nothing
        return []
    out = []
    for section in ("news", "web"):
        for r in ((data.get(section) or {}).get("results") or []):
            title = _clean(r.get("title"))
            desc = _clean(r.get("description"))
            text = f"{title} {desc}".lower()
            if not any(w in text for w in _STOP) or name.lower().split()[0] not in text:
                continue
            out.append({"title": title[:300], "snippet": desc[:500], "url": r.get("url", ""), "published": (r.get("age") or r.get("page_age") or "")[:40]})
    seen, uniq = set(), []
    for r in out:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"]); uniq.append(r)
    return uniq[:max_results]


NEWS_SYSTEM = """You read funding-news headlines and snippets about startups and return the FINANCING EVENTS they state, as strict
JSON: {"items": [{"i": <index>, "events": [{"round_name": "pre-seed|seed|series a|series b|series c|series d|growth|", "amount": "<as written, e.g. $12M>",
"currency": "USD|EUR|GBP|other", "date": "YYYY-MM|", "lead": "<lead investor slug or empty>", "investors": ["<slugs>"], "quote": "<VERBATIM title or snippet that states it>", "modality": "realized|intent"}]}]}
Rules: `quote` is copied exactly from ONE title or snippet given for that company (code discards anything else). Only events about
THAT company (a headline about a different company with a similar name is not an event; if the snippet names another company as
the one raising, skip it). "in talks", "plans to raise", "seeking" → modality intent. Investors only when named as investors.
Return every index with an events list (empty when nothing is stated)."""


def news_payload(batch: list[dict]) -> str:
    return json.dumps({"items": [{"i": i, "company": b["name"], "website": b.get("website") or "", "hq": b.get("hq") or "",
                                  "articles": [{"title": a["title"], "snippet": a["snippet"], "published": a.get("published") or ""} for a in b["articles"][:10]]}
                                 for i, b in enumerate(batch)]}, ensure_ascii=False)


def validate_news(out: dict, batch: list[dict]) -> dict[int, list[dict]]:
    """index → financing events, each gated: verbatim quote from that company's articles; figure and round word in the quote."""
    res: dict[int, list[dict]] = {}
    got = {int(o.get("i")): o for o in (out.get("items") or []) if isinstance(o, dict) and str(o.get("i", "")).isdigit()}
    for i, b in enumerate(batch):
        texts = {}
        for a in b["articles"]:
            for t in (a.get("title"), a.get("snippet")):
                if t:
                    texts[norm(t)] = a
        evs = []
        for ev in ((got.get(i) or {}).get("events") or []):
            if not isinstance(ev, dict) or ev.get("modality") == "intent":
                continue
            qn = norm(str(ev.get("quote") or ""))
            art = texts.get(qn) or next((a for k, a in texts.items() if qn and len(qn) >= 20 and qn in k), None)
            if not art:
                continue
            rn_raw = norm(str(ev.get("round_name") or ""))
            rn = _ROUND.get(rn_raw, "")
            if rn and not re.search(r"\b" + re.escape(rn_raw.replace("-", " ")) + r"\b", qn.replace("-", " ")):
                rn = ""
            amt = parse_money(ev.get("amount")) if str(ev.get("currency") or "USD").upper() == "USD" else None
            if amt is not None and not figure_in_quote(amt, qn):
                amt = None
            if not rn and amt is None:
                continue
            from ..extract import _month
            evs.append({"kind": "press", "round_name": rn, "amount_usd": amt, "event_date": _month(ev.get("date")) or None,
                        "investors": [_slug(x) for x in (ev.get("investors") or []) if _slug(x)][:12], "lead": _slug(ev.get("lead") or ""),
                        "quote": str(ev.get("quote"))[:800], "source_url": art.get("url") or ""})
        if evs:
            res[i] = dedup_events(evs)
    return res


def dedup_events(evs: list[dict]) -> list[dict]:
    """Several articles report the SAME round: one event per (round name, amount) — the earliest dated one, its
    investor list merged (the lead kept from any article that names one)."""
    by: dict[tuple, dict] = {}
    for ev in sorted(evs, key=lambda e: (e.get("event_date") is None, e.get("event_date") or "")):
        k = (ev.get("round_name") or "", round(float(ev["amount_usd"] or 0) / 1e5) if ev.get("amount_usd") else None)
        cur = by.get(k)
        if cur is None:
            by[k] = dict(ev); continue
        cur["investors"] = list(dict.fromkeys((cur.get("investors") or []) + (ev.get("investors") or [])))[:12]
        if not cur.get("lead") and ev.get("lead"):
            cur["lead"] = ev["lead"]
    return list(by.values())
