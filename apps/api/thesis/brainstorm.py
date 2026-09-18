"""Brainstorm orchestration — assemble a thesis's WHOLE context and run continuous, memory-bearing
brainstorm turns over it, plus the on-demand enrichment legs (experts / references / media / deepdive)
that fetch REAL sources when the user pulls on a suggested direction.

The conversational mechanics live in the kernel (`decision.compose_brainstorm`); the partner voice +
grounding discipline is the vertical's (`profile.brainstorm_directive`). This module is the
vertical-bound app layer: it assembles the domain context pack and fires the retrieval legs
(people / web / corpus). Never raises into the request path; every leg is best-effort + time-bounded
and returns a card the client renders inline. Real people, prior work, and media come from these legs —
never from the model — so the conversation can suggest WHERE to look without fabricating sources.
"""
from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlparse

from eigen_kernel.decision import compose_brainstorm, empty_memory

from . import attack as atk

_WS = re.compile(r"\s+")


def _clip(s, n: int) -> str:
    return _WS.sub(" ", str(s or "")).strip()[:n]


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").replace("www.", "")
    except Exception:      # noqa: BLE001
        return ""


# ── context assembly ────────────────────────────────────────────────────────────────────────────

def assemble_context(doc: dict, questions: list[dict], *, cap: int = 9000) -> str:
    """The lean-but-complete context pack a brainstorm turn reasons over: the thesis, how it currently
    leans, the collective read (bottom line + tensions/gaps/assumptions), the answered findings, and the
    competitive shape. Deliberately NOT everything — the take + findings already carry the grounded
    substance; packing every raw evidence row would only add noise and cost."""
    doc = doc or {}
    parts: list[str] = []
    thesis = _clip(doc.get("thesis"), 600)
    if thesis:
        parts.append("THESIS UNDER TEST: " + thesis)
    subject = " ".join(str(v) for v in (doc.get("subject") or {}).values()).strip()
    if subject:
        parts.append("SUBJECT: " + _clip(subject, 300))

    # How it leans (claim verdicts, non-open only).
    verdicts = [f"- {_clip(c.get('rung'), 60)}: {c.get('verdict')}"
                for c in (doc.get("claims") or [])
                if c.get("verdict") and c.get("verdict") != "open"]
    if verdicts:
        parts.append("WHERE THE CLAIMS LAND:\n" + "\n".join(verdicts[:10]))

    take = doc.get("collective_take") or {}
    if not take.get("empty"):
        bl = _clip((take.get("bottom_line") or {}).get("text"), 500)
        if bl:
            parts.append("THE COLLECTIVE READ (bottom line): " + bl)
        blocks: list[str] = []
        for s in (take.get("sections") or []):
            for a in (s.get("analysis") or []):
                t = _clip(a.get("text"), 240)
                if t:
                    blocks.append(f"- [{a.get('kind')}] {t}")
        if blocks:
            parts.append("REASONING THE READ SURFACED (tensions / gaps / assumptions):\n"
                         + "\n".join(blocks[:14]))

    # Answered findings (line — question — answer excerpt).
    findings = []
    for q in (questions or []):
        if not q.get("target_status") or not (q.get("answer") or "").strip():
            continue
        line = _clip(q.get("inquiry_name") or "Findings", 60)
        ques = _clip(q.get("text"), 160)
        ans = _clip(q.get("answer"), 300)
        findings.append(f"- ({line}) {ques} → {ans}")
    if findings:
        parts.append("WHAT THE RESEARCH FOUND (answered questions):\n" + "\n".join(findings[:16]))

    comp = doc.get("competitive") or {}
    if not comp.get("empty"):
        names = [p.get("name") for p in (comp.get("players") or []) if p.get("name")]
        if names:
            parts.append("COMPETITIVE LANDSCAPE (" + _clip(comp.get("space"), 80) + "): "
                         + ", ".join(_clip(n, 40) for n in names[:12]))

    if len(findings) == 0 and take.get("empty", True):
        parts.append("NOTE: research has not been run yet — reason from the thesis itself and open up "
                     "what to investigate.")
    return "\n\n".join(parts)[:cap].strip()


async def run_turn(llm_json, profile, *, doc: dict, questions: list[dict], said: str,
                   memory: dict | None = None, history: list[dict] | None = None) -> dict:
    """One brainstorm turn over the assembled context. Returns the kernel turn dict
    {reply, sections, directions, memory}. Never raises."""
    directive = ""
    if profile is not None and hasattr(profile, "brainstorm_directive"):
        try:
            directive = profile.brainstorm_directive(doc.get("thesis") or "")
        except Exception:      # noqa: BLE001
            directive = ""
    context = assemble_context(doc, questions)
    return await compose_brainstorm(llm_json, directive=directive, context=context, said=said,
                                    memory=memory or empty_memory(), history=history or [])


# ── enrichment legs (on-demand; real sources) ─────────────────────────────────────────────────────

def _card(title: str, url: str, snippet: str, *, tag: str = "") -> dict:
    return {"title": _clip(title, 160) or _host(url) or "source", "url": url,
            "source": _host(url), "snippet": _clip(snippet, 360), "tag": tag}


async def leg_experts(manifest, profile, *, doc: dict, query: str) -> dict:
    """Find REAL people to engage on a sub-area, via the people leg (public-web profiles). Signal for
    who to reach out to — never evidence. -> {kind, query, people:[{name,url,headline,org}], unavailable}."""
    subject = " ".join(str(v) for v in (doc.get("subject") or {}).values()).strip()
    q = _clip(query, 240) or subject or _clip(doc.get("thesis"), 120)
    try:
        from eigen_kernel.runtime.build import build_people
        client = build_people(mode=os.environ.get("EIGEN_PROVIDER_MODE") or "live",
                              include_domains=tuple(getattr(manifest, "people_domains", ()) or ()))
    except Exception:      # noqa: BLE001
        return {"kind": "experts", "query": q, "people": [], "unavailable": True}
    try:
        rows = await asyncio.wait_for(client.search(q, max_results=6), timeout=18)
    except Exception:      # noqa: BLE001
        rows = []
    seen, people = set(), []
    for p in rows or []:
        url = (getattr(p, "profile_url", "") or "").strip()
        key = url.lower()
        if not url or key in seen:
            continue
        seen.add(key)
        people.append({"name": _clip(getattr(p, "name", ""), 120) or _host(url),
                       "url": url, "headline": _clip(getattr(p, "headline", ""), 200),
                       "org": _clip(getattr(p, "org", ""), 120)})
    return {"kind": "experts", "query": q, "people": people, "unavailable": False}


async def _web_cards(manifest, queries: list[str], *, per: int = 4, tag_of=None, timeout: float = 16) -> list[dict]:
    wc = atk._web_client(manifest)
    if wc is None:
        return []
    async def _one(q):
        try:
            return await wc.search(q, max_results=per, open_web=True)
        except Exception:      # noqa: BLE001
            return []
    try:
        results = await asyncio.wait_for(asyncio.gather(*[_one(q) for q in queries if q]), timeout=timeout)
    except Exception:      # noqa: BLE001
        return []
    seen, cards = set(), []
    for res in results:
        for x in res or []:
            url = (getattr(x, "url", "") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            text = " ".join(filter(None, [*(getattr(x, "highlights", ()) or ()),
                                          getattr(x, "snippet", "") or "",
                                          (getattr(x, "body", "") or "")[:500]])).strip()
            if not text:
                continue
            tag = tag_of(url) if tag_of else ""
            cards.append(_card(getattr(x, "title", ""), url, text, tag=tag))
    return cards


async def leg_references(manifest, *, query: str) -> dict:
    """Prior theses / memos / analyses adjacent to this one — for structure and inspiration, sourced from
    the open web. -> {kind, query, cards:[...]}."""
    q = _clip(query, 200)
    queries = [f"{q} investment thesis", f"{q} VC memo analysis", f"{q} market thesis"]
    cards = await _web_cards(manifest, queries, per=4)
    return {"kind": "references", "query": q, "cards": cards[:8]}


_MEDIA_TAG = (("youtube.com", "video"), ("youtu.be", "video"), ("vimeo.com", "video"),
              ("spotify.com", "podcast"), ("apple.com/podcast", "podcast"), ("podcasts.", "podcast"),
              ("substack.com", "blog"), ("medium.com", "blog"))


def _media_tag(url: str) -> str:
    u = (url or "").lower()
    for frag, tag in _MEDIA_TAG:
        if frag in u:
            return tag
    return "article"


async def leg_media(manifest, *, query: str) -> dict:
    """First-person / operator media on a topic — podcasts, talks, blog posts — from the open web.
    -> {kind, query, cards:[{...,tag}]}."""
    q = _clip(query, 200)
    queries = [f"{q} podcast", f"{q} founder talk youtube", f"{q} essay blog"]
    cards = await _web_cards(manifest, queries, per=4, tag_of=_media_tag)
    return {"kind": "media", "query": q, "cards": cards[:9]}


async def leg_deepdive(manifest, llm_json, *, query: str) -> dict:
    """A focused dossier on a company or sub-area: gather open-web sources, then synthesize a few crisp,
    sourced bullet points. -> {kind, query, summary:[...], cards:[...]}."""
    q = _clip(query, 200)
    queries = [q, f"{q} overview", f"{q} traction funding customers"]
    cards = await _web_cards(manifest, queries, per=4, timeout=18)
    summary: list[str] = []
    if cards and llm_json is not None:
        src = "\n\n".join(f"[{i+1}] {c['title']} ({c['source']}): {c['snippet']}"
                          for i, c in enumerate(cards[:8]))
        directive = ("You are a diligence analyst. From the sources, write 3-6 crisp, specific bullet "
                     "points on the subject. Ground every point in a source; mark market sentiment / news "
                     "tone as a signal, not a fact; never invent a number. Output JSON "
                     '{"points": ["..."]}. Output ONLY the JSON.')
        try:
            raw = await asyncio.wait_for(llm_json(directive, f"SUBJECT: {q}\n\nSOURCES:\n{src}"), timeout=30)
            d = raw if isinstance(raw, dict) else __import__("json").loads(raw)
            for p in (d.get("points") or [])[:6]:
                t = _clip(p if isinstance(p, str) else (p or {}).get("text"), 260)
                if t:
                    summary.append(t)
        except Exception:      # noqa: BLE001 — a summary is a bonus; the sources still stand
            summary = []
    return {"kind": "deepdive", "query": q, "summary": summary, "cards": cards[:8]}


LEG_KINDS = ("experts", "references", "media", "deepdive")


async def run_leg(kind: str, manifest, profile, llm_json, *, doc: dict, query: str) -> dict:
    """Dispatch one enrichment leg by kind. Unknown kind -> empty card. Never raises."""
    try:
        if kind == "experts":
            return await leg_experts(manifest, profile, doc=doc, query=query)
        if kind == "references":
            return await leg_references(manifest, query=query)
        if kind == "media":
            return await leg_media(manifest, query=query)
        if kind == "deepdive":
            return await leg_deepdive(manifest, llm_json, query=query)
    except Exception:      # noqa: BLE001 — the request path never sees a leg failure
        pass
    return {"kind": kind, "query": _clip(query, 200), "cards": []}
