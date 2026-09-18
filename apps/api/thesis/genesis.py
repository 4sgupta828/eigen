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
6. EXECUTE what the author asks: if they ask you to improve/narrow/broaden/reframe the thesis a certain
   way, or ask a question, DO it this turn — rewrite the thesis to match (or answer the question) rather
   than just discussing it. When you change the thesis, say briefly WHY in `change_rationale`.
7. LEARN HOW THEY WANT IT SHAPED: keep `shaping_prefs` updated with this author's priorities, constraints,
   and style (e.g. "prefers a narrow beachhead", "wants defensibility foregrounded", "keeps it one crisp
   sentence") — so every later turn reflects how THEY want to shape it.

`reply` should be substantive — a few sentences when the subarea deserves it (the specifics + your
follow-up). No filler, flattery, or headings.

Set ready=true when the thesis meets the goal, OR the author signals to proceed, OR an open detail is
explicitly deferred ("TBD").

Return ONE JSON object exactly:
{"thought": "<brief reasoning>",
 "thesis": "<the full current falsifiable thesis sentence, unchanged if this turn didn't warrant a change>",
 "reply": "<your substantive engagement + follow-up>",
 "change_rationale": "<one line: what you changed in the thesis and why, or '' if unchanged>",
 "assumptions": ["<load-bearing assumptions the thesis rests on>"],
 "open_threads": ["<subareas/questions still to resolve to reach the goal>"],
 "resolved": ["<threads/points now settled>"],
 "shaping_prefs": ["<how THIS author wants the thesis shaped — priorities, constraints, style>"],
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
            "resolved": _lst("resolved", 14), "shaping_prefs": _lst("shaping_prefs", 12)}


def _mem_block(m: dict) -> str:
    def _fmt(xs):
        return "\n".join(f"  - {x}" for x in xs) or "  (none yet)"
    return ("WORKING MEMORY (carry forward and update):\n"
            f"assumptions the thesis rests on:\n{_fmt(m['assumptions'])}\n"
            f"open threads still to resolve (your goal is to close these):\n{_fmt(m['open_threads'])}\n"
            f"resolved (do not re-raise):\n{_fmt(m['resolved'])}\n"
            "HOW THIS AUTHOR WANTS THE THESIS SHAPED (their priorities, constraints, style — respect "
            f"and keep learning these):\n{_fmt(m['shaping_prefs'])}")


async def turn(llm_json, *, said: str, history: list[dict], budget_left: int,
               memory: dict | None = None, context: str = "") -> dict:
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
    prompt = ((f"REFERENCE MATERIAL THE AUTHOR ATTACHED (ground the thesis in it; it is context, not the "
               f"thesis to restate verbatim):\n{context.strip()[:8000]}\n\n" if (context or '').strip() else "")
              + f"CONVERSATION SO FAR:\n{_convo(history)}\n\n{_mem_block(mem)}\n\n"
              f"THE AUTHOR JUST SAID:\n{said}\n\nReason then act. Return your next turn as JSON now.")
    try:
        raw = await llm_json(_INTAKE_SYSTEM, prompt)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a genesis turn never blocks the author
        return {"reply": "", "proposed_thesis": "", "ready": True, "memory": mem, "thought": ""}
    thesis = str(d.get("thesis") or "").strip()[:THESIS_CAP]   # same bound as the seed + commit path
    reply = str(d.get("reply") or "").strip()[:1600]   # room for a substantive analyst reply
    ready = bool(d.get("ready")) or done
    # Updated memory carried forward; fall back to prior memory for any field the model dropped. Shaping
    # prefs ACCUMULATE (union with prior) rather than reset — the agent keeps learning how they want it.
    new_mem = _mem(d)
    for k in ("assumptions", "open_threads", "resolved"):
        if not new_mem[k]:
            new_mem[k] = mem[k]
    merged_prefs = list(mem["shaping_prefs"])
    for p in new_mem["shaping_prefs"]:
        if p not in merged_prefs:
            merged_prefs.append(p)
    new_mem["shaping_prefs"] = merged_prefs[:12]
    if not reply:
        reply = "Here's the updated thesis — refine it, or use it to draft the questions."
    return {"reply": reply, "proposed_thesis": thesis, "ready": ready, "memory": new_mem,
            "change_rationale": str(d.get("change_rationale") or "").strip()[:300],
            "thought": str(d.get("thought") or "").strip()[:600]}


_IMPROVE_SYSTEM = """\
You are a venture partner IMPROVING a startup thesis on the author's behalf — not interrogating them. You
PROPOSE the few highest-leverage questions whose answers would most sharpen THIS thesis, ANSWER each one
yourself from your own domain knowledge (name the real segments, mechanisms, numbers, incumbents,
regulations — be concrete, never "it depends"), and then REWRITE the thesis to fold those answers in.

Rules:
- 2 to 4 questions. Each `q` is the improvement question; each `a` is your own substantive answer to it.
- The rewrite must be MORE falsifiable, MORE specific (named buyer, substitute, mechanism, why-now), and
  MORE defensible — not merely longer. Keep the author's own product and intent; sharpen, don't hijack.
- RESPECT the author's SHAPING PREFERENCES (given below) and any INSTRUCTION they gave for this pass.
- If the thesis is already strong on a dimension, don't manufacture a change there.

Return ONE JSON object exactly:
{"questions": [{"q": "<improvement question>", "a": "<your own concrete answer>"}],
 "improved_thesis": "<the rewritten, sharper thesis — flowing prose, one to a few sentences>",
 "rationale": "<<=2 sentences: what you changed and why>",
 "shaping_prefs": ["<updated read of how this author wants the thesis shaped>"]}
Output ONLY the JSON object."""


async def improve(llm_json, *, thesis: str, memory: dict | None = None, instruction: str = "",
                  history: list[dict] | None = None) -> dict:
    """The self-improvement loop: propose a few improvement questions, ANSWER them, and rewrite the thesis.
    -> {questions:[{q,a}], improved_thesis, rationale, shaping_prefs}. Never raises; returns the thesis
    unchanged (empty questions) when there is no model or the output is unusable — the caller then makes
    no new version. `instruction` steers a directed 'improve it this way' pass."""
    mem = _mem(memory)
    thesis = (thesis or "").strip()
    if llm_json is None or not thesis:
        return {"questions": [], "improved_thesis": "", "rationale": "", "shaping_prefs": mem["shaping_prefs"]}
    convo = _convo(history or [])
    prompt = (f"CURRENT THESIS:\n{thesis}\n\n{_mem_block(mem)}\n\n"
              + (f"RECENT CONVERSATION:\n{convo}\n\n" if history else "")
              + (f"THE AUTHOR'S INSTRUCTION FOR THIS IMPROVEMENT PASS:\n{instruction}\n\n" if instruction.strip()
                 else "No specific instruction — make the highest-leverage improvements.\n\n")
              + "Propose, self-answer, and rewrite now. Return the JSON.")
    try:
        raw = await llm_json(_IMPROVE_SYSTEM, prompt)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — improvement never blocks; caller keeps the current thesis
        return {"questions": [], "improved_thesis": "", "rationale": "", "shaping_prefs": mem["shaping_prefs"]}
    qs = []
    for it in (d.get("questions") or [])[:4]:
        q = str((it or {}).get("q") or "").strip()[:300]
        a = str((it or {}).get("a") or "").strip()[:1200]
        if q and a:
            qs.append({"q": q, "a": a})
    improved = str(d.get("improved_thesis") or "").strip()[:THESIS_CAP]
    prefs = list(mem["shaping_prefs"])
    for p in [str(x).strip()[:200] for x in (d.get("shaping_prefs") or []) if str(x).strip()]:
        if p not in prefs:
            prefs.append(p)
    return {"questions": qs, "improved_thesis": improved,
            "rationale": str(d.get("rationale") or "").strip()[:400], "shaping_prefs": prefs[:12]}


# ── deficiency-driven sharpening: one identified gap + one proposal at a time ──────────────────────
# The five pillars of a solid startup INVESTMENT thesis. The agent grades the current thesis against
# these and closes the weakest gap one proposal at a time, so the author accepts/rejects deliberately
# rather than watching an opaque auto-rewrite.
PILLARS: list[dict] = [
    {"key": "macro_shift", "label": "Macro shift & why-now",
     "what": "the specific technological, regulatory, or behavioural change opening this window NOW — a "
             "tight wedge (e.g. 'embedded payroll for cross-border contractors'), never a broad bucket "
             "like 'fintech' or 'AI'"},
    {"key": "insight", "label": "Proprietary insight / edge",
     "what": "why this investor/fund is uniquely positioned to SEE, WIN, and SUPPORT it — deep domain "
             "expertise, a proprietary sourcing network, or a contrarian belief the consensus gets wrong"},
    {"key": "scope", "label": "Operational parameters & scope",
     "what": "the boundaries of the OPPORTUNITY the thesis covers: target geography, company stage "
             "(pre-seed vs seed product-market fit), and preferred business models (usage-based, "
             "marketplace…)"},
    {"key": "returns", "label": "Venture-scale return logic (100x)",
     "what": "how a winner compounds into a category-defining company — the TAM-expansion trajectory and "
             "the exit path (IPO or strategic acquisition); the 100x math"},
    {"key": "risks", "label": "Key risks & deal-breakers",
     "what": "the 3–5 load-bearing assumptions that MUST hold, and the critical risks / unit-economic or "
             "regulatory hurdles that would invalidate the thesis"},
]
_PILLAR_KEYS = {p["key"] for p in PILLARS}
_PILLAR_LABEL = {p["key"]: p["label"] for p in PILLARS}

_DEFICIENCY_SYSTEM = (
    "You are a sharp venture partner helping an investor turn a rough thesis into a SOLID investment "
    "thesis — ONE improvement at a time.\n\n"
    "WHAT A THESIS IS: a concise, first-principles HYPOTHESIS about a market opportunity and how a fund is "
    "positioned to win it — a bet on the world (X is true / X is about to happen) drawn from observed "
    "facts, logic, and the state of the world, that also names the fund's edge and acts as a filter for "
    "deal flow. It describes the OPPORTUNITY and the STRATEGY; it is INDEPENDENT of capital deployment. "
    "How much to invest — check size, fund size, ownership target, reserves — is a separate decision that "
    "is not part of the thesis (market-size and traction numbers ABOUT the opportunity do belong; the "
    "amount the investor would deploy does not). A solid thesis rests on FIVE pillars:\n"
    + "\n".join(f"{i+1}. {p['label'].upper()} — {p['what']}" for i, p in enumerate(PILLARS)) + "\n\n"
    "You are given the CURRENT thesis and the pillars ALREADY addressed or explicitly skipped. Find the "
    "SINGLE most important REMAINING weakness — the pillar most missing or weakest that is NOT in the skip "
    "list. Name it, say in one line why closing it matters for THIS thesis, and propose ONE concrete "
    "improvement: rewrite the WHOLE thesis to strengthen exactly that one pillar. Keep the author's own "
    "product and intent — sharpen, don't hijack. Stay grounded: real segments, mechanisms, numbers, "
    "incumbents; the proposal must make the thesis MORE falsifiable and specific, not merely longer. If "
    "every pillar is already adequately covered, set done=true.\n\n"
    "Return ONE JSON object exactly:\n"
    '{"done": <true only if the thesis already covers all five pillars solidly>,\n'
    ' "pillar": "<one of ' + "|".join(p["key"] for p in PILLARS) + '>",\n'
    ' "deficiency": "<what is missing or weak on this pillar, specific to THIS thesis — one or two lines>",\n'
    ' "why": "<one line: why closing this gap matters>",\n'
    ' "proposed_thesis": "<the full rewritten thesis with this ONE pillar strengthened — flowing prose>",\n'
    ' "rationale": "<=2 sentences: exactly what you added or changed>"}\n'
    "Output ONLY the JSON object.")


async def next_improvement(llm_json, *, thesis: str, skip: list[str] | None = None,
                           memory: dict | None = None, context: str = "") -> dict:
    """Identify the single most important remaining deficiency (against the five-pillar ideal) that is not
    in `skip`, and propose one improvement to close it. -> {done, pillar, pillar_label, deficiency, why,
    proposed_thesis, rationale}. Never raises; `done` (nothing to propose) on any failure."""
    mem = _mem(memory)
    thesis = (thesis or "").strip()
    empty = {"done": True, "pillar": "", "pillar_label": "", "deficiency": "", "why": "",
             "proposed_thesis": "", "rationale": ""}
    if llm_json is None or not thesis:
        return empty
    skip_set = [s for s in (skip or []) if s in _PILLAR_KEYS]
    prompt = (f"CURRENT THESIS:\n{thesis}\n\n"
              + (f"REFERENCE MATERIAL THE AUTHOR ATTACHED (use it to ground the improvement):\n"
                 f"{context.strip()[:8000]}\n\n" if (context or '').strip() else "")
              + (f"PILLARS ALREADY ADDRESSED OR SKIPPED (do NOT propose these): "
                 f"{', '.join(skip_set)}\n\n" if skip_set else "")
              + f"{_mem_block(mem)}\n\nIdentify the next deficiency and propose one improvement. Return the JSON.")
    try:
        raw = await llm_json(_DEFICIENCY_SYSTEM, prompt)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — sharpening never blocks the author
        return empty
    if not isinstance(d, dict):
        return empty
    pillar = str(d.get("pillar") or "").strip()
    if pillar not in _PILLAR_KEYS:
        pillar = ""
    proposed = str(d.get("proposed_thesis") or "").strip()[:THESIS_CAP]
    done = bool(d.get("done")) or not pillar or not proposed
    return {"done": done, "pillar": pillar, "pillar_label": _PILLAR_LABEL.get(pillar, ""),
            "deficiency": str(d.get("deficiency") or "").strip()[:400],
            "why": str(d.get("why") or "").strip()[:300],
            "proposed_thesis": proposed,
            "rationale": str(d.get("rationale") or "").strip()[:400]}


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


# ---------------------------------------------------------------- GenSimpleThesis (ISEF / CSEF level)
# A SEPARATE generator so a high-school student can enter a genuine SCIENCE-FAIR research project — the
# calibre that stands out and wins at ISEF (International Science & Engineering Fair) / CSEF (state fair):
# novel, differentiated, rigorous, and falsifiable, yet buildable by a motivated teenager with accessible
# tools (a school/home lab, low-cost sensors and microcontrollers, public datasets, open-source software,
# a local university lab). NOT a startup pitch and NOT a trivial "build an app" idea. Kept apart from
# sample_thesis so the investor flow is untouched. Runs on the OpenAI seam (the endpoint wires it) — the
# strong model is needed to reach into a real research frontier and avoid the overdone fair clichés.
# The category seed spans ALL ISEF categories, not just software, so ideas range across the sciences.
_SIMPLE_SECTORS = ("biochemistry", "cellular and molecular biology", "microbiology", "biomedical and health sciences",
                   "biomedical engineering", "translational medicine", "chemistry", "materials science",
                   "environmental engineering", "earth and environmental science", "plant sciences",
                   "computational biology and bioinformatics", "physics and astronomy", "mathematics",
                   "robotics and intelligent machines", "embedded systems", "energy and sustainable materials",
                   "engineering mechanics", "systems software / machine learning", "behavioral and social sciences",
                   "animal sciences", "neuroscience")

_SAMPLE_SIMPLE_SYSTEM = """You are a veteran ISEF (International Science & Engineering Fair) grand-award judge
and research mentor. Invent ONE genuinely competition-caliber science-fair PROJECT in the named ISEF
category — the kind that wins at CSEF/ISEF because it is NOVEL, DIFFERENTIATED, and rigorous, yet a
motivated high-school student could actually execute. Do the work in order:

1. RECALL what floods this category every year — the overdone, done-to-death projects a judge sees a
   hundred times (e.g. "does music/caffeine affect plant growth", baking-soda volcanoes, a basic solar
   oven, "which paper towel is most absorbent", a generic CNN on a Kaggle dataset). List them so you can
   deliberately AVOID them; the obvious project is disqualifying here.
2. Reach for the RESEARCH FRONTIER a student can still touch: a specific recent shift, an underused
   low-cost technique, a public dataset or open tool, an accessible assay or sensor, a cheap material —
   the angle that makes real researchers say "that's clever, and no one his age is doing it."
3. Write the PROJECT as a dense, flowing paragraph (about 6-9 sentences) that a bright 16-year-old and a
   judge both understand — accessible but rigorous, never dumbed down and never jargon for its own sake.
   Cover, in order: the specific RESEARCH QUESTION and a falsifiable HYPOTHESIS; the NOVEL, DIFFERENTIATED
   angle and exactly why it beats the standard projects; a concrete, FEASIBLE method a student could run
   with realistic resources (name the technique / dataset / material / instrument / measurement, and how
   the result would confirm or refute the hypothesis); and why it MATTERS (the real scientific or
   real-world significance a judge rewards). Specific nouns only — real assays, organisms, materials,
   datasets, algorithms, measurements — no vague wishes, no hype, no "revolutionary". State it flatly
   enough that the experiment could come out NEGATIVE.

Return ONE JSON object exactly:
{"category": "<the ISEF category>",
 "overdone": ["<clichéd projects in this category you are deliberately NOT proposing>"],
 "novelty": "<the specific differentiated angle that makes this stand out to judges>",
 "thesis": "<the ~6-9 sentence project: research question, falsifiable hypothesis, novel angle, feasible method, and why it matters>"}
Output ONLY the JSON object."""

_SIMPLE_THESIS_CAP = 1600


async def sample_thesis_simple(llm_json, *, area: str = "") -> str:
    """An ISEF/CSEF-caliber high-school research PROJECT — the GenSimpleThesis button. Novel, differentiated,
    falsifiable, and feasible for a motivated student; spans all ISEF categories, not just software. The
    model discovers first (recall the overdone projects → reach the frontier) then writes the project; we
    return the project statement, bounded to survive the downstream cap. -> the project, or '' on failure
    (endpoint answers 502). Separate from sample_thesis; the endpoint wires it to the OpenAI seam."""
    if llm_json is None:
        return ""
    area = area or random.choice(_SIMPLE_SECTORS)
    try:
        raw = await llm_json(_SAMPLE_SIMPLE_SYSTEM,
                             f"ISEF CATEGORY: {area}\nRecall the overdone projects in this category, then invent one "
                             "novel, differentiated, competition-winning project a high-school student could actually "
                             "run. Return the JSON.")
        d = raw if isinstance(raw, dict) else json.loads(raw)
        d = d or {}
        return _clip_sentence(str(d.get("thesis") or d.get("text") or "").strip(), _SIMPLE_THESIS_CAP)
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
