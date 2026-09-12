"""The agent's reply — the part that makes this a conversation rather than a report with a chat log.

The first version stored what the user typed and never read it. `next_move` walked the ledger and
announced the next weakest claim regardless of what had just been said, which is a monologue on a
timer: the reader pushes back with something they know from ten years in the industry and the agent
replies with its pre-computed opinion about a different claim.

So this module does one thing: given the claim under discussion, the evidence on both sides, and what
the user just said, produce the agent's actual reply — and let that reply CHANGE THE LEDGER. A user
who says "no, procurement owns that budget, not ops" has just settled a rung, and the ledger has to
show it or the conversation was theatre.

Rule 18: the model owns the semantics (does this answer the claim? does it change it?). This module
owns the mechanics, the closed shape, and the fail-safe — with no model the agent still advances,
just without listening, and says so rather than pretending.
"""
from __future__ import annotations

import json

from .schema import CALL_ONLY, QUESTION, SETTLEABLE

# What the agent is allowed to do with a turn. Anything else is not a move.
MOVES = ("attacked", "settled", "needs_person")
# What the user's answer is allowed to do to the claim under discussion.
EFFECTS = ("none", "revise", "answered", "contradicted", "irrelevant")

_SYSTEM = """\
You are stress-testing a startup thesis with its author. You are not their assistant and not their
critic — you are the person in the room whose job is to find where the thesis has no right to be
confident yet.

You are given ONE CLAIM the thesis rests on, the evidence we found FOR and AGAINST it, and what the
author just said. Reply to THEM, about THIS claim.

How to reply:
- Two to four sentences. Speak plainly. No headings, no bullet lists, no preamble.
- Engage with what they actually said. If they gave you information we did not have, say what it
  changes — and if it settles the claim, say so and move on rather than re-litigating.
- If they asserted something without evidence, say that it is now the load-bearing assumption and
  name who could confirm it. Do not accept it and do not dismiss it.
- If the record contradicts them, quote the specific thing and ask how it squares.
- Never flatter. Never say "great point". Never summarise what they just said back to them.
- If this claim is settled either way, end by naming the next thing you want to press on.

Also decide what their answer DID to the claim:
  none        — they did not address it
  revise      — the claim should be reworded; give the new wording
  answered    — they answered it from their own knowledge (this is now `stated` evidence from them)
  contradicted— what they said argues against the claim
  irrelevant  — this claim does not apply to their thesis and should be set aside

And which move this turn is:
  attacked    — you pressed on a weakness
  settled     — this rung is done for now
  needs_person— only a named kind of person can resolve it

Return ONE JSON object exactly matching this schema:

{"reply": "...", "move": "attacked|settled|needs_person", "effect": "none|revise|answered|contradicted|irrelevant",
 "revised_claim": "", "next_rung": ""}

Output ONLY the JSON object."""


def _ev_lines(evidence: list[dict], limit: int = 4) -> str:
    out = []
    for e in (evidence or [])[:limit]:
        if e.get("signal_only"):
            continue
        side = "AGAINST" if e.get("side") == "against" else "FOR"
        who = e.get("said_by") or e.get("source_key") or "source"
        out.append(f"- [{side} · {e.get('register', 'stated')} · {who}] "
                   f"{(e.get('quote') or '')[:220]}")
    return "\n".join(out) or "- (nothing congruent was found on either side)"


def _prompt(*, thesis: str, claim: dict, said: str, history: list[dict]) -> str:
    convo = "\n".join(f"{t.get('role', 'user')}: {(t.get('text') or '')[:300]}"
                      for t in (history or [])[-6:])
    rung = claim.get("rung", "")
    settle = SETTLEABLE.get(rung, "corpus")
    hard = ("\nNOTE: no document can settle this rung — only a person who has lived it can. Do not "
            "pretend the record could answer it." if settle == CALL_ONLY else "")
    return (f"THESIS:\n{thesis}\n\n"
            f"CLAIM UNDER DISCUSSION ({rung}): {claim.get('claim', '')}\n"
            f"The rung asks: {QUESTION.get(rung, '')}\n"
            f"Current verdict: {claim.get('verdict', 'open')}{hard}\n\n"
            f"EVIDENCE:\n{_ev_lines(claim.get('evidence') or [])}\n\n"
            f"CONVERSATION SO FAR:\n{convo or '(this is the first exchange)'}\n\n"
            f"THE AUTHOR JUST SAID:\n{said}\n\nReturn the JSON now.")


def project_cost() -> dict:
    return {"calls": 1, "projected_usd": 0.002}


# ---- follow-up over a SET of claims (the tested-phase agent) -------------------------------------
# After the thesis is tested, the conversation is one agent the author asks about a claim OR a set of
# claims they select. It EXPLAINS the evidence; it never re-grades a verdict, rewrites a case, or moves
# the recommendation — that grading is done, once, by the explicit Test step. (Contrast `reply` above,
# the older per-rung stress move that could mutate the ledger; the tested-phase path uses this instead.)
_FOLLOWUP_SYSTEM = """\
You are helping an investor read the evidence behind a startup thesis they have already tested. They
have selected one or more CLAIMS and asked a question about them. Answer it.

Rules:
- Ground every statement in the evidence given for the selected claims, or in the thesis itself. If the
  evidence does not answer the question, say so plainly and say what evidence would.
- Two to four sentences. Plain speech. No headings, no lists, no flattery.
- Report the evidence's register honestly: a filing is a fact, a press release or forum post is a
  stated claim or a signal, never dressed up as more than it is.
- You are explaining, not deciding. Do NOT announce a new verdict, a buy/pass call, or investment
  advice. If they push on the recommendation, point them to the claims that drive it and what is still
  open.
- Do not invent sources, numbers, or quotes. If you don't have it, say you don't have it.

Return ONE JSON object: {"reply": "..."}. Output ONLY the JSON object."""


def _claims_block(claims: list[dict]) -> str:
    out = []
    for c in claims or []:
        head = f"CLAIM [{c.get('rung', '')}] ({c.get('verdict', 'open')}): {c.get('claim', '')}"
        out.append(head + "\n" + _ev_lines(c.get("evidence") or [], limit=6))
    return "\n\n".join(out) or "(no claims selected)"


def _followup_prompt(*, thesis: str, claims: list[dict], said: str, history: list[dict]) -> str:
    convo = "\n".join(f"{t.get('role', 'user')}: {(t.get('text') or '')[:300]}"
                      for t in (history or [])[-6:])
    return (f"THESIS:\n{thesis}\n\nSELECTED CLAIMS AND THEIR EVIDENCE:\n{_claims_block(claims)}\n\n"
            f"CONVERSATION SO FAR:\n{convo or '(this is the first question)'}\n\n"
            f"THE AUTHOR ASKS:\n{said}\n\nReturn the JSON now.")


async def follow_up(llm_json, *, thesis: str, claims: list[dict], said: str,
                    history: list[dict]) -> dict:
    """Explain the selected claims' evidence. READ-ONLY: returns only {reply}; never changes the
    ledger. Never raises. With no model, points the reader at the evidence deterministically."""
    said = (said or "").strip()
    n = len([c for c in (claims or []) if c])
    if llm_json is None or not said:
        which = "these claims" if n != 1 else "this claim"
        return {"reply": f"Here is the evidence gathered for {which}; I could not add a written read "
                         "just now — the sources on each side are shown above."}
    try:
        raw = await llm_json(_FOLLOWUP_SYSTEM,
                             _followup_prompt(thesis=thesis, claims=claims, said=said, history=history))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a follow-up never blocks or corrupts
        return {"reply": "I couldn't read that just now. The evidence on each selected claim is shown "
                         "above — try asking again, or narrow to one claim."}
    txt = str(d.get("reply") or "").strip()
    return {"reply": txt[:1200] or "I don't have evidence in the selected claims that answers that."}


async def reply(llm_json, *, thesis: str, claim: dict, said: str, history: list[dict]) -> dict:
    """-> {reply, move, effect, revised_claim, next_rung}. Never raises.

    With no model we do NOT fabricate engagement — the caller falls back to advancing the ledger and
    tells the reader the agent could not read their answer. A confident non-sequitur is worse than
    an admission.
    """
    said = (said or "").strip()
    if llm_json is None or not said:
        return {}
    try:
        raw = await llm_json(_SYSTEM, _prompt(thesis=thesis, claim=claim, said=said,
                                              history=history))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001
        return {}
    txt = str(d.get("reply") or "").strip()
    if not txt:
        return {}
    move = str(d.get("move") or "attacked")
    eff = str(d.get("effect") or "none")
    return {"reply": txt[:1200],
            "move": move if move in MOVES else "attacked",
            "effect": eff if eff in EFFECTS else "none",
            "revised_claim": str(d.get("revised_claim") or "").strip()[:400],
            "next_rung": str(d.get("next_rung") or "").strip()}
