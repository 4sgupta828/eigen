"""Competitive LANDSCAPE research — the state of the market around a thesis, actively gathered.

The old competitive matrix was passive: it re-read whatever the per-question findings happened to name,
so it was usually empty. This module RESEARCHES the landscape on purpose:
  1. identify the players — the incumbents and startups in this space (from the thesis + the findings +
     an open-web pull for "<space> companies / <product> alternatives / market map");
  2. profile each player across the dimensions that matter — central idea, differentiation, moats, tech
     edge, customers, traction, funding, investors — every cell tied to a web source;
  3. return a landscape the app renders as per-player cards + a compact comparison table.

Register discipline: this is MARKET INTELLIGENCE from the open web (stated/reported), never filed fact —
each cell carries its source; an unfound cell is left blank, never invented. Web/LLM seams are injected,
so this stays testable and never raises; on any failure it returns an empty landscape.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

MAX_PLAYERS = 6
_PER_QUERY = 6


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").replace("www.", "")
    except Exception:      # noqa: BLE001
        return ""


async def _search(web_client, query: str) -> list[dict]:
    """Open-web results as {title, url, text} — highlights + a slice of body, like attack._web."""
    if web_client is None or not query.strip():
        return []
    try:
        res = await web_client.search(query, max_results=_PER_QUERY, open_web=True)
    except Exception:      # noqa: BLE001 — a leg we cannot reach thins the landscape, never fails it
        return []
    out = []
    for r in res or []:
        text = " ".join(filter(None, [*(getattr(r, "highlights", ()) or ()),
                                      getattr(r, "snippet", "") or "",
                                      (getattr(r, "body", "") or "")[:2500]])).strip()
        if text:
            out.append({"title": (getattr(r, "title", "") or _host(r.url) or "web")[:200],
                        "url": r.url or "", "text": text[:2800]})
    return out


async def _identify_players(llm_json, web_client, *, thesis: str, subject: str, findings: list[dict],
                            max_players: int) -> tuple[str, list[str]]:
    """(space label, [player names]) — the real incumbents + startups in this market. Seeded by an
    open-web pull and the findings; the model names the players (never invents a market that isn't there)."""
    seed = await _search(web_client, f"{subject or thesis[:80]} competitors alternatives recently funded emerging startups market map")
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:400]}" for s in seed[:6])
    found = "\n".join(f"- {f.get('answer','')[:300]}" for f in (findings or [])[:12]
                      if "competit" in (f.get("aspect", "") + f.get("question", "")).lower()
                      or f.get("aspect", "").lower().startswith("who else"))
    if llm_json is None:
        return subject or "", []
    system = ("You are a venture analyst mapping a market for a FUNDING decision. Given a startup thesis "
              "and open-web context, name the SPACE and the real players competing in it — the ones that "
              "most put THIS thesis in perspective for an investor. Prioritize NEW and RELEVANT players: "
              "recently founded / recently funded startups and fast-growing entrants alongside the "
              "incumbents that actually matter — not a list of household names for their own sake. Actual "
              "company names only, no categories, no inventions. Return ONLY "
              '{"space": "<short label>", "players": ["<company>", ...]} (most decision-relevant first).')
    user = (f"THESIS:\n{thesis}\n\nSUBJECT: {subject}\n\n"
            + (f"WHAT DILIGENCE FOUND ABOUT THE FIELD:\n{found}\n\n" if found else "")
            + (f"OPEN-WEB CONTEXT:\n{seed_txt}\n\n" if seed_txt else "")
            + f"Name up to {max_players} players. Return the JSON.")
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        space = str(d.get("space") or subject or "").strip()[:120]
        players = [str(p).strip()[:80] for p in (d.get("players") or []) if str(p).strip()]
        # de-dupe case-insensitively, cap
        seen, out = set(), []
        for p in players:
            if p.lower() not in seen:
                seen.add(p.lower()); out.append(p)
        return space, out[:max_players]
    except Exception:      # noqa: BLE001
        return subject or "", []


async def _profile_player(llm_json, web_client, *, name: str, space: str, columns: list[dict]) -> dict:
    """{key: {text, source_url, source_title}} for one player — each cell grounded in a web source, blank
    where the record is silent. Never raises."""
    hits = await _search(web_client, f"{name} {space} product funding customers investors")
    if not hits or llm_json is None:
        return {}
    listing = "\n".join(f"[{i+1}] {h['title']} ({h['url']}): {h['text']}" for i, h in enumerate(hits))
    keys = ", ".join(c["key"] for c in columns)
    system = ("You are a venture analyst profiling ONE company from open-web sources. For EACH dimension, "
              "write a concise, specific cell grounded ONLY in the sources, and give the source index [n] "
              "it rests on. Leave a dimension EMPTY (\"\") if the sources do not cover it — never invent a "
              "number, a customer, or a funding round. Funding/investors: only from a credible report.\n"
              "Return ONLY {\"cells\": {\"<dim>\": {\"text\": \"...\", \"src\": <n>}, ...}} using these "
              f"dimension keys: {keys}.")
    dims = "\n".join(f"- {c['key']}: {c.get('label') or c['key']}" for c in columns)
    user = f"COMPANY: {name}\nSPACE: {space}\n\nDIMENSIONS:\n{dims}\n\nSOURCES:\n{listing}\n\nReturn the JSON."
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        cells_in = d.get("cells") or {}
    except Exception:      # noqa: BLE001
        return {}
    out = {}
    valid = {c["key"] for c in columns}
    for k, v in cells_in.items():
        if k not in valid or not isinstance(v, dict):
            continue
        text = str(v.get("text") or "").strip()[:400]
        if not text:
            continue
        try:
            idx = int(v.get("src")) - 1
        except (TypeError, ValueError):
            idx = -1
        src = hits[idx] if 0 <= idx < len(hits) else {}
        out[k] = {"text": text, "source_url": src.get("url", ""), "source_title": src.get("title", "")}
    return out


async def suggest_candidates(llm_json, web_client, *, thesis: str, subject: str, space: str = "",
                             existing: tuple = (), max_candidates: int = 12) -> list[dict]:
    """Propose MORE competitors to analyze — direct and adjacent — that are NOT already in the landscape.
    Cheap: one open-web pull + one LLM call, and it only NAMES candidates (no profiling yet), so the user
    can pick which to spend on. -> [{name, kind: 'direct'|'adjacent', note}]. Never raises."""
    space = space or subject or thesis[:80]
    have = {str(n).strip().lower() for n in (existing or ()) if str(n).strip()}
    seed = await _search(web_client, f"{space} recently funded emerging startups new entrants competitors alternatives")
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:300]}" for s in seed[:6])
    if llm_json is None:
        return []
    system = ("You are a venture analyst expanding a competitive map for a FUNDING decision. Propose "
              "companies to ADD that would most change how an investor sees this deal — both DIRECT "
              "competitors (same job, same buyer) and ADJACENT ones (substitute, or a larger platform "
              "that could enter). Prioritize NEW and RELEVANT players: recently founded or recently "
              "funded startups and fast-growing entrants — not just legacy incumbents everyone knows. "
              "Favor the ones whose funding, traction, or momentum would put THIS thesis in perspective "
              "(a well-funded direct rival, a hot recent entrant, an incumbent about to enter). Real "
              "company names only, never categories or inventions. Return ONLY {\"candidates\": [{\"name\": "
              "\"...\", \"kind\": \"direct|adjacent\", \"note\": \"who they are + why they matter for the "
              "funding call (recency/funding/traction)\"}]} (most decision-relevant first).")
    exist_txt = ", ".join(sorted(have)) or "(none yet)"
    user = (f"THESIS:\n{thesis}\n\nMARKET: {space}\n\nALREADY IN THE MAP (do NOT repeat): {exist_txt}\n\n"
            + (f"OPEN-WEB CONTEXT:\n{seed_txt}\n\n" if seed_txt else "")
            + f"Propose up to {max_candidates} NEW candidates. Return the JSON.")
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        items = d.get("candidates") or []
    except Exception:      # noqa: BLE001
        return []
    out, seen = [], set(have)
    for it in items:
        name = str((it or {}).get("name") or "").strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        kind = "adjacent" if str((it or {}).get("kind") or "").strip().lower() == "adjacent" else "direct"
        out.append({"name": name, "kind": kind, "note": str((it or {}).get("note") or "").strip()[:200]})
        if len(out) >= max_candidates:
            break
    return out


async def profile_players(llm_json, web_client, *, names, space: str, columns: list[dict]) -> list[dict]:
    """Profile SPECIFIC named players (the ones the user chose to add) → landscape player rows. Same
    grounding as the initial research; drops any name it cannot ground on a single dimension. Never raises."""
    cols = [{"key": str(c["key"]), "label": str(c.get("label") or c["key"])} for c in (columns or [])]
    out = []
    for nm in names or []:
        nm = str(nm).strip()[:80]
        if not nm:
            continue
        cells = await _profile_player(llm_json, web_client, name=nm, space=space, columns=cols)
        if cells:
            out.append({"name": nm, "is_subject": False, "cells": cells})
    return out


async def research_landscape(llm_json, web_client, *, thesis: str, subject: str, findings: list[dict],
                             columns: list[dict], max_players: int = MAX_PLAYERS) -> dict:
    """-> {space, columns, players:[{name, is_subject, cells:{key:{text,source_url,source_title}}}],
    empty}. Row 0 is the thesis company itself (profiled from what the FINDINGS establish, cited to
    findings); the rest are competitors profiled from the open web. Never raises."""
    cols = [{"key": str(c["key"]), "label": str(c.get("label") or c["key"])} for c in (columns or [])]
    space, names = await _identify_players(llm_json, web_client, thesis=thesis, subject=subject,
                                           findings=findings, max_players=max_players)
    players = []
    for nm in names:
        cells = await _profile_player(llm_json, web_client, name=nm, space=space, columns=cols)
        if cells:                                   # drop a peer we could not ground on any dimension
            players.append({"name": nm, "is_subject": False, "cells": cells})
    return {"space": space, "columns": cols, "players": players, "empty": not players}
