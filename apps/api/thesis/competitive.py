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
    fallback = (base, [f"{base} competitors", f"{base} alternatives", f"companies like {base}"])
    if llm_json is None:
        return fallback
    system = ("You are a venture analyst. From this thesis define the ONE focused market it competes in — "
              "the exact JOB the product does, for the exact BUYER (NOT the broad category) — and write "
              "SEARCH QUERIES to find its DIRECT competitors (companies doing that same job for that same "
              "buyer). Mix short keyword queries with one natural-language 'companies that do X for Y' "
              'query. Return ONLY {"focus": "<exact job + buyer, one line>", "queries": ["...", ...]} '
              "(3-5, most precise first).")
    try:
        raw = await llm_json(system, f"THESIS:\n{thesis}\n\nSUBJECT: {subject}\n\nReturn the JSON.")
        d = raw if isinstance(raw, dict) else json.loads(raw)
        focus = str(d.get("focus") or base).strip()[:200]
        qs = [str(q).strip()[:160] for q in (d.get("queries") or []) if str(q).strip()][:5]
        return focus, (qs or fallback[1])
    except Exception:      # noqa: BLE001
        return fallback


async def _gather_seed(web_client, queries: list[str], *, cap: int = 10) -> list[dict]:
    """Search several targeted queries (meaning + keyword angles) and merge, deduped by url — better
    recall of DIRECT players than one generic query."""
    out, seen = [], set()
    for q in (queries or [])[:5]:
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
    seed = await _gather_seed(web_client, queries, cap=10)
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:400]}" for s in seed[:8])
    found = "\n".join(f"- {f.get('answer','')[:300]}" for f in (findings or [])[:12]
                      if "competit" in (f.get("aspect", "") + f.get("question", "")).lower()
                      or f.get("aspect", "").lower().startswith("who else"))
    if llm_json is None:
        return focus, []
    system = ("You are a venture analyst mapping ONE focused market for a FUNDING decision. The FOCUS (the "
              "exact job + buyer this thesis competes on) is given — stay tightly on it. Return the real "
              "companies competing FOR THAT SAME JOB AND BUYER, DIRECT competitors FIRST. Include an "
              "ADJACENT player (a substitute or a platform that could clearly enter) ONLY if it is a "
              "specific, real threat to THIS exact job — at most one or two, and last. EXCLUDE anything "
              "that merely shares the broad category but not the job/buyer, and anything you are unsure "
              "competes. Prefer new/recently-funded entrants and the incumbents that actually matter. "
              'Actual company names only. Return ONLY {"players": [{"name": "...", "kind": '
              '"direct|adjacent"}, ...]} — direct first.')
    user = (f"FOCUS (stay on this): {focus}\n\nTHESIS:\n{thesis}\n\n"
            + (f"WHAT DILIGENCE FOUND ABOUT THE FIELD:\n{found}\n\n" if found else "")
            + (f"OPEN-WEB CONTEXT:\n{seed_txt}\n\n" if seed_txt else "")
            + f"Name up to {max_players} players, DIRECT first, adjacents capped at 2. Return the JSON.")
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
                             existing: tuple = (), max_candidates: int = 12, startup_search=None) -> list[dict]:
    """Propose MORE competitors to analyze — direct and adjacent — that are NOT already in the landscape.
    Cheap: one open-web pull + one LLM call, and it only NAMES candidates (no profiling yet), so the user
    can pick which to spend on. -> [{name, kind: 'direct'|'adjacent', note}]. Never raises."""
    have = {str(n).strip().lower() for n in (existing or ()) if str(n).strip()}
    if llm_json is None:
        return []
    # Focus tightly on the exact job + buyer, and search multiple targeted angles (meaning + keyword) —
    # so candidates are DIRECT rivals in one focused area, not a scatter of adjacents.
    focus, queries = await _focus_queries(llm_json, thesis=thesis, subject=(space or subject))
    seed = await _gather_seed(web_client, queries + [focus + " competitors"], cap=10)
    seed_txt = "\n".join(f"- {s['title']}: {s['text'][:300]}" for s in seed[:8])
    system = ("You are a venture analyst expanding a competitive map for a FUNDING decision, staying on ONE "
              "focused market. The FOCUS (the exact job + buyer) is given. Propose companies to ADD that "
              "compete FOR THAT SAME JOB AND BUYER — DIRECT competitors FIRST. Include an ADJACENT one "
              "(a clear substitute or a platform that could specifically enter) only if it is a real threat "
              "to THIS exact job — at most a couple, and mark them adjacent. EXCLUDE anything that only "
              "shares the broad category but not the job/buyer, and anything you are unsure competes — a "
              "shorter, precise list beats a long, loose one. Prefer new/recently-funded entrants and the "
              "incumbents that actually matter. Real company names only, never categories or inventions. "
              "Return ONLY {\"candidates\": [{\"name\": \"...\", \"kind\": \"direct|adjacent\", \"note\": "
              "\"who they are + why they compete on THIS job (recency/funding/traction)\"}]} — direct first.")
    exist_txt = ", ".join(sorted(have)) or "(none yet)"
    user = (f"FOCUS (stay on this): {focus}\n\nTHESIS:\n{thesis}\n\n"
            + f"ALREADY IN THE MAP (do NOT repeat): {exist_txt}\n\n"
            + (f"OPEN-WEB CONTEXT:\n{seed_txt}\n\n" if seed_txt else "")
            + f"Propose up to {max_candidates} NEW candidates, DIRECT first, adjacents last & capped. "
            + "Return the JSON.")
    try:
        raw = await llm_json(system, user)
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
        kind = "adjacent" if str((it or {}).get("kind") or "").strip().lower() == "adjacent" else "direct"
        row = {"name": name, "kind": kind, "note": str((it or {}).get("note") or "").strip()[:200]}
        (adj if kind == "adjacent" else direct).append(row)
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
                             columns: list[dict], max_players: int = MAX_PLAYERS, startup_search=None) -> dict:
    """-> {space, columns, players:[{name, is_subject, cells:{key:{text,source_url,source_title}}}],
    empty}. Players are the direct competitors in the focused market — sourced from OUR internal Startup
    Search (precise, corpus-grounded) FIRST, then the open web — each profiled and cited. Never raises."""
    cols = [{"key": str(c["key"]), "label": str(c.get("label") or c["key"])} for c in (columns or [])]
    focus, web_names = await _identify_players(llm_json, web_client, thesis=thesis, subject=subject,
                                               findings=findings, max_players=max_players)
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
