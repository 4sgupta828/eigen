"""Brainstorm — a continuous, memory-bearing exploration turn over a decision's whole context.

This is the conversational altitude above the memo/deck synthesis. Where `compose_memo` writes a graded
read over the answered findings, a brainstorm turn is EXPLORATORY: given everything known about a
decision (the proposition, the reasoning already produced, what remains open) plus a running memory of
the conversation and the user's latest message, it thinks WITH the user — surfacing related questions,
adjacent areas worth pulling on, sub-areas to go deep on, and the gaps/weaknesses to press. It never
grades a verdict and never invents sourced facts: real experts, references, and media come from the
app's retrieval LEGS, fired on demand; the turn only REASONS and SUGGESTS where to look.

Domain-free by construction. The whole context arrives as an opaque `context` string the caller
assembles; the `directive` (the vertical's voice + grounding discipline) is injected; the section and
direction KINDS are generic exploration lenses a legal or biotech decision would reuse unchanged. The
turn also returns an updated STRUCTURED memory so the next turn stays continuous. Never raises.
"""
from __future__ import annotations

import json
import re

# Generic exploration lenses for the reasoning layer of a brainstorm turn. No domain noun — an adjacent
# area or an open thread means the same in any vertical.
SECTION_KINDS = ("related_questions", "adjacent_areas", "deep_dive", "gaps")

# The kinds of SUGGESTED next move a turn can offer. `question` seeds another brainstorm turn; the rest
# name a retrieval capability the app can fire on click (people, prior-work, first-person media, a focused
# dossier). These are capability names, not domain vocabulary — every vertical has experts and references.
DIRECTION_KINDS = ("question", "experts", "references", "media", "deepdive")

_WS = re.compile(r"\s+")


def _clip(s, n: int) -> str:
    return _WS.sub(" ", str(s or "")).strip()[:n]


def _str_list(v, *, cap: int, item: int) -> list[str]:
    out, seen = [], set()
    for x in (v or []):
        t = _clip(x if isinstance(x, str) else (x or {}).get("text", ""), item)
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
        if len(out) >= cap:
            break
    return out


def empty_memory() -> dict:
    return {"summary": "", "assumptions": [], "explored": [], "open_threads": []}


def merge_memory(prior: dict, update: dict) -> dict:
    """Fold a turn's memory update into the prior memory: summary replaced (it is a fresh rolling read),
    the list fields UNIONED and capped so the thread stays continuous without growing without bound."""
    prior = prior or {}
    update = update or {}
    out = {"summary": _clip(update.get("summary") or prior.get("summary"), 700)}
    for key, cap in (("assumptions", 12), ("explored", 20), ("open_threads", 12)):
        merged = list(prior.get(key) or []) + list(update.get(key) or [])
        out[key] = _str_list(merged, cap=cap, item=200)
    return out


def memory_context(memory: dict) -> str:
    """Render the thread memory as compact context for the next turn's prompt."""
    memory = memory or {}
    parts = []
    if memory.get("summary"):
        parts.append("WHERE THIS BRAINSTORM STANDS: " + _clip(memory["summary"], 700))
    for key, label in (("open_threads", "STILL OPEN"), ("explored", "ALREADY EXPLORED"),
                       ("assumptions", "WORKING ASSUMPTIONS")):
        items = memory.get(key) or []
        if items:
            parts.append(label + ": " + "; ".join(_clip(x, 160) for x in items[:10]))
    return "\n".join(parts).strip()


def _history_block(history: list[dict], *, turns: int = 8, chars: int = 320) -> str:
    rows = []
    for h in (history or [])[-turns:]:
        role = "You" if (h or {}).get("role") == "user" else "Eigen"
        text = _clip((h or {}).get("text"), chars)
        if text:
            rows.append(f"{role}: {text}")
    return "\n".join(rows).strip()


async def compose_brainstorm(llm_json, *, directive: str, context: str, said: str,
                             memory: dict | None = None, history: list[dict] | None = None,
                             section_kinds: tuple = SECTION_KINDS,
                             direction_kinds: tuple = DIRECTION_KINDS,
                             reply_chars: int = 1600) -> dict:
    """One brainstorm turn. Returns:
        {"reply": <conversational answer>,
         "sections": [{"kind": <section_kind>, "items": [<str>, ...]}],
         "directions": [{"kind": <direction_kind>, "label": <str>, "query": <str>}],
         "memory": {"summary", "assumptions", "explored", "open_threads"}}
    `context` is the caller-assembled, domain-specific context pack (opaque here). Never raises; on any
    failure returns a minimal turn carrying the prior memory unchanged."""
    mem = memory or empty_memory()
    fallback = {"reply": "", "sections": [], "directions": [], "memory": merge_memory(mem, {})}
    if llm_json is None or not (said or "").strip():
        return fallback
    sec_set, dir_set = set(section_kinds), set(direction_kinds)
    mem_ctx = memory_context(mem)
    hist = _history_block(history or [])
    user = (
        "THE FULL CONTEXT you are brainstorming over (the decision and everything known about it):\n"
        + _clip(context, 9000) + "\n\n"
        + (("CONVERSATION MEMORY:\n" + mem_ctx + "\n\n") if mem_ctx else "")
        + (("RECENT MESSAGES:\n" + hist + "\n\n") if hist else "")
        + "THE USER JUST SAID:\n" + _clip(said, 1200) + "\n\n"
        + "Think WITH them. Answer directly and concretely, then open up the most valuable directions.\n\n"
        + "EMIT a JSON object:\n"
          '{"reply": "<a direct, concrete conversational answer — a partner thinking out loud>",\n'
          '  "sections": [{"kind": "<one of ' + "|".join(section_kinds) + '>", '
          '"items": ["<short, specific point>", ...]}],\n'
          '  "directions": [{"kind": "<one of ' + "|".join(direction_kinds) + '>", '
          '"label": "<button text, e.g. \'Find GTM experts in vertical SaaS\'>", '
          '"query": "<the focused query to run for this direction>"}],\n'
          '  "memory": {"summary": "<2-3 sentence rolling state of this brainstorm>", '
          '"assumptions": ["..."], "explored": ["<topics now covered>"], '
          '"open_threads": ["<what is still worth pulling on>"]}}\n\n'
        + "RULES:\n"
        + "- reply: the substance. Reason from the context; be specific to THIS decision, not generic. "
          "Distinguish what the record SHOWS from what is worth EXPLORING — never assert as established a "
          "thing the context leaves open, and treat market sentiment/coverage as a signal, not a fact.\n"
        + "- sections: only the exploration lenses that add value THIS turn (omit the rest). "
          "related_questions = sharp questions to pursue next; adjacent_areas = neighbouring spaces/angles "
          "worth a look; deep_dive = a sub-area to go deep on and what to look for; gaps = the weakest "
          "points / what the record can't settle. Each item is one tight, specific line.\n"
        + "- directions: 2-5 suggested next moves. Use kind='question' for a follow-up worth asking here; "
          "kind='experts' to go find real people, 'references' for prior theses/memos/research, 'media' for "
          "podcasts/talks/blogs, 'deepdive' for a focused dossier on a company or sub-area. The `query` is "
          "what to actually search — DO NOT name specific real people, papers, or shows yourself; the "
          "search returns the real ones. Only suggest a retrieval direction when it would genuinely help.\n"
        + "- memory: update the running state so the next turn stays continuous. Keep lists short and "
          "de-duplicated.\n"
        + "- Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — fail soft; never break the conversation
        return fallback
    if not isinstance(d, dict):
        return fallback

    sections = []
    for s in (d.get("sections") or []):
        if not isinstance(s, dict):
            continue
        kind = _clip(s.get("kind"), 40)
        if kind not in sec_set:
            continue
        items = _str_list(s.get("items"), cap=8, item=260)
        if items:
            sections.append({"kind": kind, "items": items})

    directions, seen = [], set()
    for x in (d.get("directions") or []):
        if not isinstance(x, dict):
            continue
        kind = _clip(x.get("kind"), 40)
        if kind not in dir_set:
            continue
        label = _clip(x.get("label"), 120)
        query = _clip(x.get("query"), 240) or label
        key = (kind, label.lower())
        if label and key not in seen:
            seen.add(key)
            directions.append({"kind": kind, "label": label, "query": query})
        if len(directions) >= 6:
            break

    reply = _clip(d.get("reply"), reply_chars)
    updated = merge_memory(mem, d.get("memory") if isinstance(d.get("memory"), dict) else {})
    return {"reply": reply, "sections": sections, "directions": directions, "memory": updated}
