"""Genesis — converse a messy idea into a SHARP, FALSIFIABLE thesis, before any decomposition.

The old flow took whatever the user first typed and decomposed it, and a single model both proposed a
sentence AND graded its own readiness — so it rubber-stamped vague theses ("AI in logistics") as ready
and the whole stress test inherited the vagueness. This is the fix, modelled on factra's decision-intake
agent: a TWO-MODEL conversation.

  1. The PARTNER (converse) reads the conversation and proposes its best single-sentence formalization —
     restating, never echoing — and asks AT MOST ONE clarifying question at the biggest gap.
  2. A separate adversarial VALIDATOR grades that draft against a rubric (is it falsifiable? a concrete
     named buyer, not "companies"? a specific mechanism? a real substitute it must displace?) → one of
     {ready, needs_sharpening, blocked} — plus the load-bearing ASSUMPTIONS the thesis rests on. The
     partner CANNOT declare itself ready; code reads the validator's verdict.

Rule 18: the MODEL owns the wording; CODE owns the gate (`ready` is the validator's verdict, not the
partner's self-flag) and the fail-safe (no model / bad JSON / spent budget → fall open with the user's
own words, never trap them behind an interrogation). The HUMAN owns the thesis: genesis only proposes;
nothing is committed until the user confirms the sentence.
"""
from __future__ import annotations

import json

# The load-bearing elements a startup thesis needs before it can be decomposed into a falsifiable
# ladder: WHAT is sold, WHO buys it, what they do TODAY instead, and WHY it happens (the mechanism).
ELEMENTS = ("product", "buyer", "substitute")

# Analyst turns before code stops asking and lets the user proceed with what they have. Each turn is two
# small JSON calls (partner + validator); genesis is rare, so the ceiling is generous but bounded.
GENESIS_BUDGET = 4

_CONVERSE_SYSTEM = """\
You are an investor's diligence partner. Your ONLY job in this conversation is to help the author land
ONE sharp, FALSIFIABLE startup thesis — a claim the diligence will then test — before we break it into
claims. You are formalizing it, not endorsing it.

A sharp thesis names four things: the PRODUCT (what is sold), the BUYER (the specific segment that pays
— never "companies" or "enterprises"), the SUBSTITUTE (what they do today instead, the thing this must
displace), and the MECHANISM (WHY it will happen — the load-bearing "because", often a threshold or a
shift). It is stated flatly enough to be proven FALSE.
Example: "Mid-market 3PLs (40-200 trucks) will pay for automated route re-planning, displacing the
spreadsheet dispatch they run today, because above ~40 trucks a planner's labour cost exceeds the
software's."

Each turn you get the conversation so far, the author's latest message, and — if the grader has run —
the GAPS it flagged. Do TWO things:
1. Write your best single-sentence formalization of the thesis so far, in the author's own nouns.
   RESTATE it into a tight, falsifiable claim — never copy their words verbatim, and never soften a
   claim into a topic. Fill in only what they clearly implied; do NOT invent a segment, substitute, or
   mechanism they did not gesture at (say what is still missing instead).
2. Write a short reply. If a gap is still open, ask ONE neutral question at the SINGLE biggest gap —
   never a battery of questions, never a leading one that argues for a more fundable framing. If nothing
   load-bearing is missing, say so plainly and invite them to use it.

Rules: one or two plain sentences, no flattery, no "great idea", no headings. Never state the thesis as
settled or promising. The author owns the final sentence; you propose, they confirm.

Return ONE JSON object exactly:
{"reply": "...", "proposed_thesis": "<one falsifiable sentence>"}
Output ONLY the JSON object."""

_VALIDATOR_SYSTEM = """\
You grade a draft startup INVESTMENT THESIS for an investor. You do not converse and you do not soften.
Judge ONLY the thesis sentence given (with the conversation as context). A thesis is a FALSIFIABLE CLAIM
the diligence will test — "SEGMENT will do X, displacing Y, because Z" — not a topic and not a question.

Grade on four axes:
- FALSIFIABLE: is it stated flatly enough that evidence could prove it FALSE? (An aspiration or a trend
  is not.)
- BUYER: is the paying segment SPECIFIC (e.g. "mid-market 3PLs, 40-200 trucks"), not generic
  ("companies", "enterprises", "the market")?
- SUBSTITUTE: does it name what buyers do TODAY that this must displace?
- MECHANISM: does it give the load-bearing reason it will happen (the "because" — a threshold, a cost
  crossover, a regulatory or technology shift)?

Return status:
- "ready": a falsifiable claim with a specific buyer and at least a substitute OR a mechanism — specific
  enough to decompose into testable claims. Perfection is not required; decomposability is.
- "needs_sharpening": thesis intent is there but one or two axes are vague (generic buyer, no substitute,
  no mechanism). Salvageable with one or two questions.
- "blocked": not a thesis at all — a bare topic or research area ("AI in logistics", one word), a
  definitional/informational question ("what is X?"), or empty.

Also return:
- "gaps": up to 2 short, NEUTRAL questions naming exactly what is missing to reach "ready" (empty when
  ready). Each names the specific missing axis, e.g. "Which buyer segment specifically — who signs the
  cheque?".
- "assumptions": up to 4 declarative LOAD-BEARING assumptions the thesis rests on — things that must be
  TRUE for it to hold and whose negation would break it (e.g. "driver labour cost keeps rising"). These
  are bets, NOT unresolved scope questions. Empty if none are clear yet.

Return ONE JSON object exactly:
{"status": "ready|needs_sharpening|blocked", "gaps": ["..."], "assumptions": ["..."]}
Output ONLY the JSON object."""


def _convo(history: list[dict]) -> str:
    return "\n".join(f"{t.get('role', 'user')}: {(t.get('text') or '')[:300]}"
                     for t in (history or [])[-8:]) or "(this is the first message)"


def _converse_prompt(*, said: str, history: list[dict], gaps: list[str]) -> str:
    g = ("\nGAPS THE GRADER FLAGGED LAST TURN:\n" + "\n".join(f"- {x}" for x in gaps)) if gaps else ""
    return (f"CONVERSATION SO FAR:\n{_convo(history)}{g}\n\n"
            f"THE AUTHOR JUST SAID:\n{said}\n\nReturn the JSON now.")


def _validator_prompt(*, thesis: str, history: list[dict]) -> str:
    return (f"CONVERSATION (context):\n{_convo(history)}\n\n"
            f"DRAFT THESIS TO GRADE:\n{thesis}\n\nReturn the JSON now.")


def project_cost() -> dict:
    return {"calls": 2, "projected_usd": 0.004}


async def validate(validator_llm, *, thesis: str, history: list[dict]) -> dict:
    """Grade a draft thesis. -> {status, gaps, assumptions}. Never raises; a missing/failing grader
    falls open to 'ready' with no gaps (code still gates on budget), so the user is never trapped."""
    fallback = {"status": "ready", "gaps": [], "assumptions": []}
    if validator_llm is None or not (thesis or "").strip():
        return fallback
    try:
        raw = await validator_llm(_VALIDATOR_SYSTEM, _validator_prompt(thesis=thesis, history=history))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a grader outage never blocks the user
        return fallback
    status = str(d.get("status") or "").strip().lower()
    if status not in ("ready", "needs_sharpening", "blocked"):
        status = "needs_sharpening"
    gaps = [str(x).strip() for x in (d.get("gaps") or []) if str(x).strip()][:2]
    assumptions = [str(x).strip() for x in (d.get("assumptions") or []) if str(x).strip()][:4]
    return {"status": status, "gaps": gaps, "assumptions": assumptions}


async def turn(llm_json, *, said: str, history: list[dict], budget_left: int, validator_llm=None) -> dict:
    """One genesis turn: partner proposes, validator grades. -> {reply, proposed_thesis, questions,
    ready, status, assumptions, missing}. Never raises.

    `ready` is CODE's call over the VALIDATOR's verdict (status == 'ready'), or when the budget is spent,
    or when there is no model — never the partner's self-assessment. Questions are the validator's gaps,
    capped at two, and only while the thesis is not yet ready.
    """
    said = (said or "").strip()
    fallback = {"reply": "", "proposed_thesis": said, "questions": [], "ready": True,
                "status": "ready", "assumptions": [], "missing": []}
    # No model, or the budget is spent: fall open with the user's own words as the proposed thesis.
    if llm_json is None or budget_left <= 0:
        return fallback
    if not said and not history:
        return fallback

    # Gaps the grader flagged on the PREVIOUS turn steer the partner's next question (carried in the
    # last agent turn's payload); on the first turn there are none.
    prev_gaps = next((t.get("payload", {}).get("questions") or []
                      for t in reversed(history or []) if t.get("role") == "agent"), [])
    try:
        raw = await llm_json(_CONVERSE_SYSTEM, _converse_prompt(said=said, history=history, gaps=prev_gaps))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a genesis turn never blocks the user
        return fallback
    proposed = str(d.get("proposed_thesis") or said).strip()[:600]

    # The adversarial grader — a DIFFERENT seam when available (cross-family), else the same model. The
    # partner cannot declare itself ready; this verdict is what code gates on.
    verdict = await validate(validator_llm or llm_json, thesis=proposed, history=history)
    ready = verdict["status"] == "ready"
    questions = [] if ready else verdict["gaps"]
    reply = str(d.get("reply") or "").strip()[:800]
    if not reply:
        reply = "Looks concrete enough to test." if ready else "Tell me a little more."
    return {"reply": reply, "proposed_thesis": proposed, "questions": questions, "ready": ready,
            "status": verdict["status"], "assumptions": verdict["assumptions"], "missing": verdict["gaps"]}
