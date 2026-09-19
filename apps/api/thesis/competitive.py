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
import logging
from urllib.parse import urlparse

log = logging.getLogger("eigen.thesis.competitive")

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
    except Exception as exc:      # noqa: BLE001 — a leg we cannot reach thins the landscape, never fails it
        log.warning("competitive web search failed (query=%r): %s: %s", query[:60], type(exc).__name__, exc)
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


async def _focus_queries(llm_json, *, thesis: str, subject: str) -> tuple[str, list[str]]:
    """(focus, [queries]) — the ONE focused market (the exact JOB + BUYER this thesis competes on) and
    targeted search queries to find its DIRECT competitors, mixing keyword and natural-language angles so
    we search by meaning AND by term. Falls back to simple queries with no model."""
    base = (subject or thesis[:80]).strip()
    fallback = (base, [f"{base} competitors", f"{base} startups", f"{base} alternatives",
                       f"companies like {base}", f"{base} market leaders incumbents"])
    if llm_json is None:
        return fallback
    system = (
        "You are a venture analyst finding the PRECISE competitive set for a thesis. First pin the ONE "
        "focused market: the exact JOB the product does, for the exact BUYER — a tight wedge, never the "
        "broad category ('embedded payroll for cross-border contractors', not 'fintech'). Then write "
        "SEARCH QUERIES that will surface the REAL players — spanning FOUR angles so nothing is missed:\n"
        "  1) direct-competitor keyword searches (the specific product + buyer terms),\n"
        "  2) STARTUP / recently-funded-entrant searches (e.g. '<job> startup seed Series A 2024 2025'),\n"
        "  3) INCUMBENT / market-leader searches (who owns this today, the substitute being displaced),\n"
        "  4) one natural-language 'companies that do <job> for <buyer>' / 'alternatives to <leader>' query.\n"
        'Return ONLY {"focus": "<exact job + buyer, one line>", "queries": ["...", ...]} — 5-7 queries, '
        "the most precise first, using the real nouns of the market (segments, standards, incumbents).")
    try:
        raw = await llm_json(system, f"THESIS:\n{thesis}\n\nSUBJECT: {subject}\n\nReturn the JSON.")
        d = raw if isinstance(raw, dict) else json.loads(raw)
        focus = str(d.get("focus") or base).strip()[:200]
        qs = [str(q).strip()[:160] for q in (d.get("queries") or []) if str(q).strip()][:7]
        return focus, (qs or fallback[1])
    except Exception:      # noqa: BLE001
        return fallback


async def _gather_seed(web_client, queries: list[str], *, cap: int = 16) -> list[dict]:
    """Search several targeted queries (direct / startup / incumbent / meaning angles) and merge, deduped
    by url — higher recall of the real players than one generic query."""
    out, seen = [], set()
    for q in (queries or [])[:7]:
        for s in await _search(web_client, q):
            u = s.get("url") or s.get("title")
            if u and u not in seen:
                seen.add(u); out.append(s)
        if len(out) >= cap:
            break
    return out[:cap]


async def _identify_players(llm_json, web_client, *, thesis: str, subject: str, findings: list[dict],
                            max_players: int) -> tuple[str, list[str]]:
    """(focus label, [player names]) — the real players competing on THIS thesis's exact job, DIRECT
    competitors first. Seeded by focused, multi-angle web search; the model names the players (never
    invents), stays tightly on the focus, and adjacents are capped so the map isn't drowned in tangents."""
    focus, queries = await _focus_queries(llm_json, thesis=thesis, subject=subject)
    seed = await _gather_seed(web_client, queries, cap=16)
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:400]}" for s in seed[:12])
    found = "\n".join(f"- {f.get('answer','')[:300]}" for f in (findings or [])[:12]
                      if "competit" in (f.get("aspect", "") + f.get("question", "")).lower()
                      or f.get("aspect", "").lower().startswith("who else"))
    if llm_json is None:
        return focus, []
    system = (
        "You are a venture analyst mapping ONE focused market for a FUNDING decision. The FOCUS (the exact "
        "job + buyer this thesis competes on) is given — stay tightly on it. Name the REAL companies that "
        "compete for THAT SAME JOB AND BUYER, most precise first. Reason before you list:\n"
        "- DIRECT: startups/companies doing the same job for the same buyer — these come FIRST and are most "
        "of the list. Prefer the specific, recently-funded ENTRANTS and the clear category leaders.\n"
        "- INCUMBENT: the established player(s) / substitute this thesis displaces — include the ones that "
        "actually matter for this job (mark kind='incumbent').\n"
        "- ADJACENT: a platform or substitute that could credibly ENTER this exact job — at most one or two, "
        "LAST (kind='adjacent').\n"
        "Rules: real, verifiable company names only — NEVER invent one; if you are not confident a company "
        "exists and competes on THIS job, leave it out. Ground each in the open-web context or your own "
        "solid knowledge of the space. EXCLUDE anything that only shares the broad category but not the "
        "job/buyer. A precise short list beats a padded one.\n"
        'Return ONLY {"players": [{"name": "...", "kind": "direct|incumbent|adjacent", "why": "<=8 words, '
        'how it competes on this job>"}, ...]} — direct first, then incumbents, adjacents last.')
    user = (f"FOCUS (stay on this): {focus}\n\nTHESIS:\n{thesis}\n\n"
            + (f"WHAT DILIGENCE FOUND ABOUT THE FIELD:\n{found}\n\n" if found else "")
            + (f"OPEN-WEB CONTEXT (candidate names appear here):\n{seed_txt}\n\n" if seed_txt else "")
            + f"Name up to {max_players} players, DIRECT first, incumbents next, adjacents (≤2) last. Return the JSON.")
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        items = d.get("players") or []
        direct, adj, seen = [], [], set()
        for it in items:
            nm = str((it if not isinstance(it, dict) else it.get("name")) or "").strip()[:80]
            if not nm or nm.lower() in seen:
                continue
            seen.add(nm.lower())
            kind = str((it or {}).get("kind") if isinstance(it, dict) else "").strip().lower()
            (adj if kind == "adjacent" else direct).append(nm)
        return focus, (direct + adj[:2])[:max_players]     # direct first; adjacents capped
    except Exception:      # noqa: BLE001
        return focus, []


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
                             existing: tuple = (), max_candidates: int = 12, startup_search=None,
                             reason_llm=None) -> list[dict]:
    """Propose MORE competitors to analyze — direct, incumbent and adjacent — NOT already in the landscape.
    Cheap: an open-web pull + one LLM call, and it only NAMES candidates (no profiling yet), so the user
    can pick which to spend on. `reason_llm` (when given) powers the precision reasoning.
    -> [{name, kind: 'direct'|'incumbent'|'adjacent', note}]. Never raises."""
    have = {str(n).strip().lower() for n in (existing or ()) if str(n).strip()}
    reason = reason_llm or llm_json
    if reason is None:
        return []
    # Focus tightly on the exact job + buyer, and search multiple targeted angles (direct / startup /
    # incumbent / meaning) — so candidates are the REAL rivals in one focused area, not a scatter.
    focus, queries = await _focus_queries(reason, thesis=thesis, subject=(space or subject))
    seed = await _gather_seed(web_client, queries + [focus + " competitors", focus + " startup funding"], cap=16)
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:300]}" for s in seed[:12])
    system = ("You are a venture analyst expanding a competitive map for a FUNDING decision, staying on ONE "
              "focused market. The FOCUS (the exact job + buyer) is given. Propose companies to ADD that "
              "compete FOR THAT SAME JOB AND BUYER — DIRECT startups/companies FIRST, then the INCUMBENT(s) "
              "or substitute this thesis displaces (kind='incumbent'), then at most one or two ADJACENT "
              "players that could credibly ENTER this exact job (kind='adjacent', last). Prefer the "
              "specific, recently-funded ENTRANTS and the leaders that actually matter. EXCLUDE anything "
              "that only shares the broad category but not the job/buyer, and anything you are unsure "
              "competes — a shorter, precise list beats a long, loose one. Real, verifiable company names "
              "only, NEVER a category or an invention. Ground each in the web context or solid knowledge. "
              "Return ONLY {\"candidates\": [{\"name\": \"...\", \"kind\": \"direct|incumbent|adjacent\", "
              "\"note\": \"who they are + why they compete on THIS job (recency/funding/traction)\"}]} — "
              "direct first, incumbents next, adjacents last.")
    exist_txt = ", ".join(sorted(have)) or "(none yet)"
    user = (f"FOCUS (stay on this): {focus}\n\nTHESIS:\n{thesis}\n\n"
            + f"ALREADY IN THE MAP (do NOT repeat): {exist_txt}\n\n"
            + (f"OPEN-WEB CONTEXT:\n{seed_txt}\n\n" if seed_txt else "")
            + f"Propose up to {max_candidates} NEW candidates, DIRECT first, adjacents last & capped. "
            + "Return the JSON.")
    try:
        raw = await reason(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        items = d.get("candidates") or []
    except Exception:      # noqa: BLE001
        return []
    direct, adj, seen = [], [], set(have)
    for it in items:
        name = str((it or {}).get("name") or "").strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        k = str((it or {}).get("kind") or "").strip().lower()
        kind = "adjacent" if k == "adjacent" else "incumbent" if k == "incumbent" else "direct"
        row = {"name": name, "kind": kind, "note": str((it or {}).get("note") or "").strip()[:200]}
        (adj if kind == "adjacent" else direct).append(row)   # incumbents ride with direct (kept, not capped)
    # OUR internal Startup Search: any indexed company matching the focus is a real, direct candidate —
    # prepend it (deduped) so corpus-grounded competitors lead over web guesses.
    picked = {r["name"].lower() for r in direct + adj} | set(have)
    su_rows = []
    for nm in await _startup_names(startup_search, focus, max_candidates):
        if nm.lower() not in picked:
            picked.add(nm.lower())
            su_rows.append({"name": nm, "kind": "direct", "note": "in our startup index"})
    return (su_rows + direct + adj[:3])[:max_candidates]     # our index first, then direct web, then adjacents


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


async def _startup_names(startup_search, text: str, limit: int) -> list[str]:
    """Company names from OUR internal Startup Search (hybrid semantic+keyword over our company index) —
    a precise, corpus-grounded source of direct competitors. [] when unavailable. Never raises."""
    if startup_search is None or not (text or "").strip():
        return []
    try:
        rows = await startup_search(text, limit) or []
    except Exception:      # noqa: BLE001 — an internal-search hiccup never blocks web discovery
        return []
    out, seen = [], set()
    for r in rows:
        nm = str((r or {}).get("name") or "").strip()[:80]
        if nm and nm.lower() not in seen:
            seen.add(nm.lower()); out.append(nm)
    return out


async def research_landscape(llm_json, web_client, *, thesis: str, subject: str, findings: list[dict],
                             columns: list[dict], max_players: int = MAX_PLAYERS, startup_search=None,
                             reason_llm=None) -> dict:
    """-> {space, columns, players:[{name, is_subject, cells:{key:{text,source_url,source_title}}}],
    empty}. Players are the competitors in the focused market — sourced from OUR internal Startup Search
    (precise, corpus-grounded) FIRST, then the open web — each profiled and cited. `reason_llm` (when
    given) powers the precision-critical focus + player IDENTIFICATION (the strongest reasoner); profiling
    stays on `llm_json` (cheaper/faster). Never raises."""
    cols = [{"key": str(c["key"]), "label": str(c.get("label") or c["key"])} for c in (columns or [])]
    focus, web_names = await _identify_players(reason_llm or llm_json, web_client, thesis=thesis,
                                               subject=subject, findings=findings, max_players=max_players)
    # OUR index first (a company that's in our startup corpus IS a real, indexed player), then web recall.
    su_names = await _startup_names(startup_search, focus, max_players)
    names, seen = [], set()
    for nm in su_names + web_names:
        if nm.lower() not in seen:
            seen.add(nm.lower()); names.append(nm)
    names = names[:max_players]
    players, dropped = [], 0
    for nm in names:
        cells = await _profile_player(llm_json, web_client, name=nm, space=focus, columns=cols)
        if cells:                                   # drop a peer we could not ground on any dimension
            players.append({"name": nm, "is_subject": False, "cells": cells})
        else:
            dropped += 1
    log.info("competitive landscape: web=%s focus=%r identified=%d profiled=%d dropped=%d",
             web_client is not None, (focus or "")[:80], len(names), len(players), dropped)
    # A helpful reason when the map came back empty — so the client can say WHY, not just "nothing yet".
    reason = ""
    if not players:
        if web_client is None:
            reason = "The open-web research leg is not configured, so competitors can't be profiled."
        elif not names:
            reason = "No competitors were identified for this market from the thesis and findings."
        else:
            reason = "Competitors were identified but couldn't be grounded on the open web (the web leg may be rate-limited or returning nothing) — try again in a minute."
    return {"space": focus, "columns": cols, "players": players, "empty": not players, "reason": reason}
