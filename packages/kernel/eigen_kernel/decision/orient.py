"""Orient-before-you-ask — a landscape scan that keeps the QUESTIONS current, not just the answers.

Question generation is otherwise purely parametric: the model names incumbents / "why now" / entrants
from its training memory, so the research PLAN is bounded by the cutoff (stale incumbents, missed recent
entrants, a new regulation it never heard of). Because the plan gates every downstream evidence run,
that is the highest-leverage staleness bug — no amount of grounded answering recovers a question never
asked.

This module fixes *what gets asked*. Two moves, in order (the insight is the FIRST one):
  A. ORIENT (meta-cognition): the model decides *what it must learn to ask well* — it emits typed
     orientation queries, it does NOT answer from memory here.
  B. SCAN (retrieve current): run those queries against the injected legs — corpus, live web, a peer
     index — keeping each hit's source + register + `as_of` date.
  C. DIGEST: a compact, dated, typed `LandscapeBrief` the generators draw every named specific from.

The mechanism is DOMAIN-FREE: the legs (`retrieve` / `web` / `peers`) and the "what a thesis of this
kind must know" `directive` are injected. Same fail-safe as the rest of the grounding path — every phase
degrades to a smaller-but-valid brief and NEVER raises; a leg we cannot reach widens `unknowns`, it does
not fail the scan.
"""
from __future__ import annotations

import json
import re
from datetime import date

# A capitalized MULTI-word phrase — an entity name like "Oracle Health", "Epic Systems". Multi-word only,
# so a sentence-initial single capital ("Which incumbents…") never false-positives as a named specific.
_ENTITY = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]+(?:\s+(?:of|the|for|&|[A-Z][A-Za-z0-9&.\-]+))*\s+[A-Z][A-Za-z0-9&.\-]+")
# Sentence-initial words the regex can absorb into a phrase — stripped so "Does Cerner Millennium…"
# reads as the entity "Cerner Millennium", not a false phrase starting with the interrogative.
_LEAD_WORDS = {"does", "do", "did", "what", "which", "is", "are", "was", "were", "how", "why", "when",
               "where", "can", "could", "will", "would", "should", "the", "a", "an", "who", "whom", "if"}

# The typed needs an orientation query can serve. Domain-free buckets; the vertical directive supplies
# what each means for its domain. `benchmark`/`regulation` etc. are generic diligence axes, not nouns.
NEEDS = ("incumbents", "entrants", "funding", "regulation", "benchmark", "why_now", "market_event", "substitute")
_SECTIONS = ("incumbents", "entrants", "funding", "regulation", "benchmarks", "why_now")


def _today() -> str:
    return date.today().isoformat()


def empty_brief(as_of: str = "", note: str = "") -> dict:
    """A valid, empty brief — returned on any failure so callers never branch on None."""
    b: dict = {"as_of": as_of or _today()}
    for s in _SECTIONS:
        b[s] = []
    b["unknowns"] = [note] if note else []
    return b


def _clip(s, n: int) -> str:
    return str(s or "").strip()[:n]


async def _orientation_queries(llm_json, *, directive: str, decision: str, subject: str,
                               history: str, cap: int) -> list[dict]:
    """Phase A — the model names what it must LEARN (never answers). Returns [{q, need, why}], capped."""
    if llm_json is None:
        return []
    system = (directive or "").strip() or (
        "You are orienting before you ask. Given a thesis, name what you must LEARN from the CURRENT "
        "record to ask the right questions — do NOT answer from memory here.")
    system += (
        "\n\nEmit ONLY JSON: {\"queries\": [{\"q\": \"<present-tense search query in the thesis's own "
        "nouns + its segment, dated ('current', 'latest', '" + str(date.today().year) + "')>\", "
        "\"need\": \"<one of " + "|".join(NEEDS) + ">\", \"why\": \"<what learning this lets you ask "
        "well>\"}]}.\nRules: at most " + str(cap) + " queries; each SPECIFIC to THIS thesis's mechanism "
        "and segment (a generic 'who are the competitors' is a failure); you may only NAME what to search "
        "for, never state an answer.")
    user = f"THESIS:\n{decision}\n\n" + (f"SUBJECT: {subject}\n\n" if subject else "") + \
           (f"CONVERSATION SO FAR (mine for specifics):\n{history}\n\n" if history else "") + \
           "Return the orientation queries JSON."
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        if not isinstance(d, dict):      # a string that decodes to a list/scalar → nothing to read
            return []
    except Exception:      # noqa: BLE001 — orientation never blocks; no queries → empty brief
        return []
    out, seen = [], set()
    for it in (d.get("queries") or []):
        if not isinstance(it, dict):
            continue
        q = _clip(it.get("q"), 200)
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        need = str(it.get("need") or "").strip().lower()
        out.append({"q": q, "need": need if need in NEEDS else "", "why": _clip(it.get("why"), 200)})
        if len(out) >= cap:
            break
    return out


async def _scan(queries: list[dict], *, retrieve, web, peers, per_query: int, web_cap: int) -> list[dict]:
    """Phase B — run every orientation query through the injected legs CONCURRENTLY; keep each hit's
    source + register + as_of. Every leg is best-effort; a leg that raises or returns nothing simply
    contributes nothing."""
    import asyncio

    async def _try(coro):
        try:
            return await coro
        except Exception:      # noqa: BLE001 — a leg we cannot reach thins the scan, never fails it
            return []

    # Fan the (leg, need, query) calls out at once; a burst of ~N×legs I/O should not be N×legs serial.
    plan, web_used = [], 0
    for oq in queries:
        q, need = oq["q"], oq.get("need") or ""
        if retrieve is not None:
            plan.append(("corpus", need, _try(retrieve(q))))
        if web is not None and web_used < web_cap:
            web_used += 1
            plan.append(("web", need, _try(web(q))))
        if peers is not None and need in ("entrants", "incumbents", "substitute", ""):
            plan.append(("peers", need, _try(peers(q))))
    results = await asyncio.gather(*(p[2] for p in plan)) if plan else []

    hits: list[dict] = []
    for (leg, need, _), res in zip(plan, results):
        for r in (res or [])[:per_query]:
            if leg == "corpus":
                hits.append({"need": need, "leg": "corpus", "title": _clip(r.get("title"), 200),
                             "text": _clip(r.get("text"), 700), "source": _clip(r.get("source"), 200),
                             "url": _clip(r.get("url"), 400), "as_of": _clip(r.get("as_of"), 20),
                             "register": _clip(r.get("register"), 20) or "filed"})
            elif leg == "web":
                hits.append({"need": need, "leg": "web", "title": _clip(r.get("title"), 200),
                             "text": _clip(r.get("text"), 700), "source": _clip(r.get("source") or r.get("url"), 200),
                             "url": _clip(r.get("url"), 400), "as_of": _clip(r.get("as_of"), 20),
                             "register": "coverage"})
            else:  # peers
                nm = _clip(r.get("name"), 120)
                if nm:
                    hits.append({"need": need or "entrants", "leg": "peers", "title": nm,
                                 "text": _clip(r.get("note"), 300), "source": "peer-index",
                                 "url": "", "as_of": "", "register": "stated"})
    return hits


async def _digest(llm_json, *, decision: str, hits: list[dict], as_of: str) -> dict:
    """Phase C — a dated, typed LandscapeBrief composed ONLY from the scanned hits. One grounded call;
    on failure, degrade to a deterministic assembly so a brief still comes back."""
    if not hits:
        return empty_brief(as_of, "the landscape scan returned nothing to ground the plan")
    listing = "\n".join(
        f"[{i+1}] ({h['leg']}/{h['register']}{(' · as of ' + h['as_of']) if h['as_of'] else ''}) "
        f"{h['title']}: {h['text']}" for i, h in enumerate(hits[:40]))
    if llm_json is not None:
        system = (
            "You are digesting a landscape SCAN into a dated brief a diligence lead will ask questions "
            "from. Use ONLY the numbered scan hits — never add a name, number, rule or date not in them. "
            "Every entry cites its hit [n] and carries an as_of date when the hit has one. Put anything the "
            "scan could not establish into `unknowns` (these seed 'what would change this' questions).\n"
            "Emit ONLY JSON: {\"incumbents\":[{\"name\":\"\",\"what_they_do\":\"\",\"src\":<n>}],"
            "\"entrants\":[{\"name\":\"\",\"note\":\"\",\"src\":<n>}],\"funding\":[{\"who\":\"\",\"round\":\"\",\"src\":<n>}],"
            "\"regulation\":[{\"rule\":\"\",\"status\":\"\",\"src\":<n>}],\"benchmarks\":[{\"name\":\"\",\"result\":\"\",\"src\":<n>}],"
            "\"why_now\":[{\"catalyst\":\"\",\"src\":<n>}],\"unknowns\":[\"\"]}")
        user = f"THESIS:\n{decision}\n\nSCAN HITS:\n{listing}\n\nReturn the brief JSON."
        try:
            raw = await llm_json(system, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            return _shape(d, hits, as_of)
        except Exception:      # noqa: BLE001 — fall through to deterministic assembly
            pass
    # Deterministic fallback: bucket the hits by their orientation `need`, keep them dated + sourced.
    b = empty_brief(as_of)
    bucket = {"incumbents": "incumbents", "entrants": "entrants", "funding": "funding",
              "regulation": "regulation", "benchmark": "benchmarks", "why_now": "why_now"}
    for h in hits:
        sec = bucket.get(h.get("need") or "", "entrants" if h["leg"] == "peers" else "")
        if not sec:
            continue
        b[sec].append({"name": h["title"], "note": h["text"], "source": h["source"] or h["url"],
                       "as_of": h["as_of"], "register": h["register"]})
    if not any(b[s] for s in _SECTIONS):
        b["unknowns"].append("the scan found context but nothing cleanly typed — treat specifics as to-verify")
    return b


def _shape(d: dict, hits: list[dict], as_of: str) -> dict:
    """Validate the model's brief: keep only entries whose src points at a real hit; carry its as_of."""
    b = empty_brief(as_of)
    def src_of(v):
        try:
            i = int(v) - 1
            return hits[i] if 0 <= i < len(hits) else None
        except (TypeError, ValueError):
            return None
    keymap = {"incumbents": ("name", "what_they_do"), "entrants": ("name", "note"),
              "funding": ("who", "round"), "regulation": ("rule", "status"),
              "benchmarks": ("name", "result"), "why_now": ("catalyst", None)}
    for sec, (k1, k2) in keymap.items():
        for it in (d.get(sec) or []):
            if not isinstance(it, dict):
                continue
            a = _clip(it.get(k1), 160)
            if not a:
                continue
            h = src_of(it.get("src"))
            b[sec].append({k1: a, **({k2: _clip(it.get(k2), 300)} if k2 else {}),
                           "source": (h or {}).get("source") or (h or {}).get("url") or "",
                           "as_of": (h or {}).get("as_of") or "",
                           "register": (h or {}).get("register") or "coverage"})
    b["unknowns"] = [_clip(u, 200) for u in (d.get("unknowns") or []) if _clip(u, 200)][:8]
    return b


def brief_is_empty(brief: dict | None) -> bool:
    return not brief or not any((brief.get(s) or []) for s in _SECTIONS)


def _brief_entities(brief: dict | None) -> str:
    """All named specifics in the brief, lowercased into one haystack for membership checks."""
    if not brief:
        return ""
    parts = []
    for sec in _SECTIONS:
        for it in (brief.get(sec) or []):
            parts += [str(it.get(k) or "") for k in ("name", "who", "rule", "catalyst")]
    return " ".join(parts).lower()


def unsourced_specifics(text: str, brief: dict | None) -> list[str]:
    """The anti-staleness lint (spec §5.1): named multi-word entities in generated text that are NOT in
    the dated brief — i.e. specifics the model likely recalled from stale memory, not the current scan.
    Empty when the brief is empty (nothing to check against) — the discipline only binds once we scanned.
    Conservative by design (multi-word entities only) to avoid flagging generic phrasings."""
    if brief_is_empty(brief):
        return []
    hay = _brief_entities(brief)
    out = []
    for m in _ENTITY.finditer(text or ""):
        toks = m.group(0).strip().split()
        while toks and toks[0].lower() in _LEAD_WORDS:      # drop a sentence-initial "Does/Which/Is…"
            toks = toks[1:]
        if len(toks) < 2:                                    # need a real 2+-word entity, not one capital
            continue
        ph = " ".join(toks)
        if ph.lower() in hay or any(len(t) > 3 and t.lower() in hay for t in toks):
            continue
        out.append(ph)
    return sorted(set(out))


def brief_context(brief: dict | None, *, cap: int = 2200) -> str:
    """Render the brief as the 'CURRENT LANDSCAPE (as of …)' block appended to a generator's context.
    Empty brief → '' (the generators fall back to generic/present-tense phrasings)."""
    if brief_is_empty(brief):
        return ""
    assert brief is not None
    lines = [f"CURRENT LANDSCAPE (as of {brief.get('as_of') or _today()}, dated + typed — name specifics "
             "ONLY from here; anything absent, phrase generically or tag to-verify):"]
    label = {"incumbents": "Incumbents now", "entrants": "Recent entrants", "funding": "Recent funding",
             "regulation": "Regulation/policy", "benchmarks": "Benchmarks/SOTA", "why_now": "Why now"}
    for sec in _SECTIONS:
        rows = brief.get(sec) or []
        if not rows:
            continue
        parts = []
        for it in rows[:6]:
            head = it.get("name") or it.get("who") or it.get("rule") or it.get("catalyst") or ""
            tail = it.get("what_they_do") or it.get("note") or it.get("round") or it.get("status") or it.get("result") or ""
            dt = f" (as of {it.get('as_of')})" if it.get("as_of") else ""
            parts.append(f"{head}{(' — ' + tail) if tail else ''}{dt}".strip())
        if parts:
            lines.append(f"- {label[sec]}: " + "; ".join(parts))
    if brief.get("unknowns"):
        lines.append("- Could NOT establish (ask generically / to-verify): " + "; ".join(brief["unknowns"][:5]))
    return "\n".join(lines)[:cap]


async def orient_and_scan(llm_json, *, retrieve=None, web=None, peers=None, decision: str,
                          subject: str = "", history: str = "", directive: str = "",
                          n_queries: int = 8, per_query: int = 3, web_cap: int = 8) -> dict:
    """Orient → scan → digest → a dated, typed `LandscapeBrief`. Injected legs keep the kernel
    domain-free. Never raises; degrades to a smaller-but-valid brief on any failure."""
    as_of = _today()
    decision = (decision or "").strip()
    if not decision:
        return empty_brief(as_of, "no thesis to orient on")
    queries = await _orientation_queries(llm_json, directive=directive, decision=decision,
                                         subject=subject, history=history, cap=max(1, n_queries))
    if not queries:
        return empty_brief(as_of, "could not form orientation queries")
    hits = await _scan(queries, retrieve=retrieve, web=web, peers=peers,
                       per_query=max(1, per_query), web_cap=max(0, web_cap))
    brief = await _digest(llm_json, decision=decision, hits=hits, as_of=as_of)
    brief["queries"] = [q["q"] for q in queries]      # what we chose to learn (for the UI / audit)
    return brief
