"""Genesis — a CONVERSATIONAL intake agent that refines a messy idea, turn by turn, into ONE clear,
falsifiable thesis. Modelled on factra's project-intake wizard (`genesis_intake`): a natural chat that
draws the decision out of the author ONE focused question at a time, sets `ready` when it has a workable
thesis, then SYNTHESISES the whole conversation into a single clean statement the author confirms.

The old flow was a form — it proposed a sentence on turn one and self-declared "ready" from a
product/buyer/substitute checkbox, so it read as a childish reformulation. This is a real conversation:
the agent asks about the single biggest gap, the author answers in their own words, and only the FINAL
synthesis (over the whole transcript) becomes the thesis — not a running restatement.

Rule 18: the MODEL owns the wording AND, here (as in factra), whether the conversation is `ready`; CODE
owns only the fail-safes (no model / bad JSON / spent budget → proceed with the author's own words, never
trap them) and the fact that nothing commits until the HUMAN confirms the synthesised sentence.
"""
from __future__ import annotations

import json
import random

# Sectors to seed a varied sample thesis, so "generate a plausible thesis" isn't the same idea twice.
_SECTORS = ("AI infrastructure", "developer tools", "climate / energy", "biotech / drug discovery",
            "fintech / payments", "robotics / automation", "logistics / supply chain",
            "healthcare delivery", "cybersecurity", "advanced materials / manufacturing",
            "space / geospatial", "agriculture / food", "legal / compliance tech", "construction tech",
            "semiconductors", "vertical SaaS", "data infrastructure")

# Turns of natural conversation before code stops and lets the author proceed with what they have.
# It's a real dialogue now, so the ceiling is generous but bounded.
GENESIS_BUDGET = 6

_INTAKE_SYSTEM = """\
You are a sharp, domain-fluent venture partner running a REASON-then-ACT loop to help an investor land ONE
robust, FALSIFIABLE thesis to test. You have a GOAL and a MEMORY, and you think before you act.

YOUR GOAL: converge on a thesis that is (a) falsifiable, (b) names a specific buyer, a real substitute,
and a mechanism, and (c) whose load-bearing ASSUMPTIONS are surfaced and whose major OPEN THREADS are
each either resolved or explicitly deferred as things the diligence will test. Drive the conversation
toward closing the open threads.

YOUR MEMORY is given to you each turn (current thesis; assumptions surfaced; open threads still to
resolve; points resolved). CARRY IT FORWARD and UPDATE it. Never lose it, never re-raise a resolved
point, never re-ask something already answered.

EACH TURN, reason then act:
1. THINK (in `thought`): what did the author just say, where does it leave the thesis versus the goal,
   and what is the single most useful move now? Keep it short.
2. ENGAGE the author's actual input — a comment, question, objection, correction, or refinement — as a
   thread to PULL. Go DEEP on the subarea with concrete, real-world specifics from your knowledge (name
   the actual regulations, standards, segments, incumbents, cost structures, adoption barriers,
   mechanisms). Answer questions directly. Add SPECIFICITY, never shallow rewording.
3. ASK a sharp clarifying follow-up when it helps close an open thread, paired with YOUR best answer.
4. HOLD THE GROUND on the thesis: change it ONLY when the discussion warrants (new constraint, accepted
   refinement, resolved ambiguity, valid objection); otherwise return it UNCHANGED, word for word, and
   say why. Push back when the author is wrong.
5. UPDATE MEMORY: add any new assumptions and open threads; move a thread to resolved once settled.

`reply` should be substantive — a few sentences when the subarea deserves it (the specifics + your
follow-up). No filler, flattery, or headings.

Set ready=true when the thesis meets the goal, OR the author signals to proceed, OR an open detail is
explicitly deferred ("TBD").

Return ONE JSON object exactly:
{"thought": "<brief reasoning>",
 "thesis": "<the full current falsifiable thesis sentence, unchanged if this turn didn't warrant a change>",
 "reply": "<your substantive engagement + follow-up>",
 "assumptions": ["<load-bearing assumptions the thesis rests on>"],
 "open_threads": ["<subareas/questions still to resolve to reach the goal>"],
 "resolved": ["<threads/points now settled>"],
 "ready": true|false}
Output ONLY the JSON object."""


def _convo(history: list[dict], said: str = "") -> str:
    lines = [f"{t.get('role', 'user')}: {(t.get('text') or '')[:400]}" for t in (history or [])[-12:]]
    if said:
        lines.append(f"user: {said[:400]}")
    return "\n".join(lines) or "(this is the first message)"


def project_cost() -> dict:
    return {"calls": 1, "projected_usd": 0.002}


import re

# Signals that the author is done refining — either an explicit "proceed" OR an "this detail is open"
# answer (TBD / don't know). Code flips ready on these even if the model keeps proposing refinements, so
# the conversation always terminates and an open detail simply becomes a thing the diligence tests.
_DONE = re.compile(r"\b(proceed|go ahead|let'?s go|that'?s (it|enough|all)|good to go|move on|"
                   r"use (this|it)|i'?m ready|we'?re ready|sounds good|looks good|yes let'?s|ship it|"
                   r"tbd|to be (figured|determined)|figure (it|that|this)? ?out|not sure|"
                   r"don'?t know|unsure|no idea)\b", re.I)


def _mem(m: dict | None) -> dict:
    """Coerce a memory blob to the canonical shape (lists of short strings), capped."""
    m = m or {}
    def _lst(k, cap):
        return [str(x).strip()[:280] for x in (m.get(k) or []) if str(x).strip()][:cap]
    return {"assumptions": _lst("assumptions", 8), "open_threads": _lst("open_threads", 8),
            "resolved": _lst("resolved", 14)}


def _mem_block(m: dict) -> str:
    def _fmt(xs):
        return "\n".join(f"  - {x}" for x in xs) or "  (none yet)"
    return ("WORKING MEMORY (carry forward and update):\n"
            f"assumptions the thesis rests on:\n{_fmt(m['assumptions'])}\n"
            f"open threads still to resolve (your goal is to close these):\n{_fmt(m['open_threads'])}\n"
            f"resolved (do not re-raise):\n{_fmt(m['resolved'])}")


async def turn(llm_json, *, said: str, history: list[dict], budget_left: int,
               memory: dict | None = None) -> dict:
    """One REASON-then-ACT turn. -> {reply, proposed_thesis, ready, memory, thought}. Never raises.

    A ReAct step over eigen's JSON seam: the agent is given its GOAL (a robust falsifiable thesis) and its
    MEMORY (thesis + assumptions + open threads + resolved), reasons (`thought`), acts (engage the input,
    hold or update the thesis), and returns UPDATED memory to carry forward. CODE fail-safes: no model /
    bad JSON / spent budget → ready; an explicit proceed signal also flips ready, so the author is never
    trapped."""
    said = (said or "").strip()
    mem = _mem(memory)
    done = bool(_DONE.search(said))
    if llm_json is None or budget_left <= 0:
        return {"reply": "", "proposed_thesis": "", "ready": True, "memory": mem, "thought": ""}
    if not said and not history:
        return {"reply": "", "proposed_thesis": "", "ready": False, "memory": mem, "thought": ""}
    prompt = (f"CONVERSATION SO FAR:\n{_convo(history)}\n\n{_mem_block(mem)}\n\n"
              f"THE AUTHOR JUST SAID:\n{said}\n\nReason then act. Return your next turn as JSON now.")
    try:
        raw = await llm_json(_INTAKE_SYSTEM, prompt)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a genesis turn never blocks the author
        return {"reply": "", "proposed_thesis": "", "ready": True, "memory": mem, "thought": ""}
    thesis = str(d.get("thesis") or "").strip()[:THESIS_CAP]   # same bound as the seed + commit path
    reply = str(d.get("reply") or "").strip()[:1600]   # room for a substantive analyst reply
    ready = bool(d.get("ready")) or done
    # Updated memory carried forward; fall back to prior memory for any field the model dropped.
    new_mem = _mem(d)
    for k in ("assumptions", "open_threads", "resolved"):
        if not new_mem[k]:
            new_mem[k] = mem[k]
    if not reply:
        reply = "Here's the updated thesis — refine it, or use it to draft the questions."
    return {"reply": reply, "proposed_thesis": thesis, "ready": ready, "memory": new_mem,
            "thought": str(d.get("thought") or "").strip()[:600]}


# A sample thesis is a one-click SEED for the genesis conversation, not a committed thesis. Downstream it
# is dropped in as the first author turn, stored via set_proposed_thesis, and rendered as a chat bubble.
# We want it genuinely DETAILED (~250-300 words), so the whole proposed-thesis path shares one bound —
# THESIS_CAP — aligned to the committed-thesis ceiling (commit_claims / set_proposed_thesis / turn all
# cap here); the `thesis`/`proposed_thesis` DB columns are unbounded `text`, and `decompose` reads the
# full text, so a detailed thesis survives end-to-end without silent truncation. Novelty is forced by
# making the model do the discovery first (scan the consensus, name the wedge) as required JSON fields
# before it may write the thesis; that reasoning shapes the output, then is discarded.
THESIS_CAP = 2000
_SAMPLE_THESIS_CAP = THESIS_CAP

_SAMPLE_SYSTEM = """You are a contrarian venture partner inventing ONE early-stage thesis worth
diligencing in the named sector — SPECIFIC, FALSIFIABLE, and genuinely NON-OBVIOUS. Realistic and
grounded in how the market actually works today, never sci-fi and never a trend-piece platitude. Do the
work in order:

1. SCAN the sector for the CONSENSUS takes — the theses a generalist pitches first. List them so you can
   deliberately AVOID them; the obvious thesis is a failure here.
2. Find the WEDGE the consensus misses: a specific emerging shift, a mispriced constraint, a threshold
   about to be crossed, a regulation taking effect, or a buyer whose behaviour is changing. Name the real
   mechanism, not a vibe.
3. Write the THESIS on that wedge as a DETAILED, dense argument in FLOWING PROSE — never labelled fields
   or headers like "Product:" / "Buyer:". About 6-10 sentences (~250-300 words) that lay out, in order:
   the specific non-obvious WEDGE and why the consensus misses it; the PRODUCT; the SPECIFIC buyer
   segment (never "companies" or "enterprises"); the incumbent or SUBSTITUTE it displaces and why that
   substitute is losing; the MECHANISM (a "because ..." — a threshold, cost crossover, or behaviour
   shift); WHY NOW (the concrete change making it possible/urgent now); and the one or two LOAD-BEARING
   ASSUMPTIONS the whole thesis rests on. Dense with the real nouns of the market — actual segments,
   standards, regulations, incumbents, cost structures, adoption barriers. State it flatly enough that
   evidence could prove it FALSE. No hedging ("may", "could"), no flattery, no filler, no bullet lists.

Return ONE JSON object exactly:
{"consensus": ["<obvious takes you are deliberately NOT proposing>"],
 "wedge": "<the specific non-obvious shift/mechanism you are betting on>",
 "thesis": "<the detailed ~6-10 sentence falsifiable thesis: wedge, product, specific buyer, substitute, mechanism, why now, load-bearing assumptions>"}
Output ONLY the JSON object."""


async def sample_thesis(llm_json, *, sector: str = "") -> str:
    """A fresh, realistic, falsifiable, NON-OBVIOUS startup thesis from the model's parametric knowledge —
    a one-click seed for the intake conversation. Varied by a random sector. The model discovers first
    (consensus → wedge) and then writes a detailed thesis; we return only the thesis statement (the seed),
    bounded so it survives the downstream set_proposed_thesis cap unchanged. -> the thesis, or '' on
    failure (no model, bad JSON) so the endpoint can answer 502 rather than fabricate."""
    if llm_json is None:
        return ""
    sector = sector or random.choice(_SECTORS)
    try:
        raw = await llm_json(_SAMPLE_SYSTEM,
                             f"SECTOR: {sector}\nScan the consensus, find the non-obvious wedge, then "
                             "write the detailed falsifiable thesis on that wedge. Return the JSON.")
        d = raw if isinstance(raw, dict) else json.loads(raw)
        d = d or {}
        return _clip_sentence(str(d.get("thesis") or d.get("text") or "").strip(), _SAMPLE_THESIS_CAP)
    except Exception:      # noqa: BLE001 — a helper; a failure just means no sample this click
        return ""


def _clip_sentence(text: str, cap: int) -> str:
    """Bound `text` to `cap` chars WITHOUT cutting mid-word: trim back to the last sentence end (or, if
    none, the last space) so the seed never ends on a truncated fragment."""
    if len(text) <= cap:
        return text
    head = text[:cap]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut >= cap // 2:
        return head[:cut + 1].strip()
    sp = head.rfind(" ")
    return (head[:sp] if sp >= cap // 2 else head).strip()
