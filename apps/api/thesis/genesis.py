"""Genesis — converse a messy idea into a concrete, falsifiable thesis, before any decomposition.

The old flow took whatever the user first typed and decomposed it. A one-liner missing its buyer or its
substitute decomposes into ten vague claims, and the whole stress test inherits the vagueness. This
module is the fix: one analyst turn that reads the conversation so far and produces (a) a short reply,
(b) its best one-sentence formalization of the thesis, and (c) — ONLY when something load-bearing is
missing — up to two NEUTRAL clarifying questions.

Rule 18, as everywhere in this app: the MODEL owns the wording (the reply, the proposed sentence, the
question text); CODE owns the gate (is the thesis concrete enough to decompose?) and the fail-safe. The
gate reads the model's OWN structured output — it does NOT make a second `decompose` call to probe
readiness (that would be a circular LLM round-trip). And the HUMAN owns the thesis: genesis only
proposes; nothing is committed until the user confirms the sentence.

Mirrors the guided-analyst discipline (`apps/api/startups/intake.py`): one small JSON call per turn,
capped by a budget, and every failure mode (no model, bad JSON, spent budget) falls open to `ready`
with the user's own words — never trap the user behind an interrogation.
"""
from __future__ import annotations

import json

# The three load-bearing elements a startup thesis needs before it can be decomposed into a falsifiable
# ladder: WHAT is sold, WHO buys it, and what they do TODAY instead (the substitute it must displace).
ELEMENTS = ("product", "buyer", "substitute")

# How many analyst turns the model gets before code stops asking and lets the user proceed with what
# they have. Two questions is usually the whole of it; three turns is the ceiling.
GENESIS_BUDGET = 3

_SYSTEM = """\
You help an investor turn a rough idea into ONE concrete, falsifiable startup thesis — a decision to
be informed against — before we break it into claims and test it.

A good thesis names three things: the PRODUCT (what is sold), the BUYER (which specific segment pays,
not "companies"), and the SUBSTITUTE (what they do today instead — the thing this must displace). It
is stated flatly enough to be FALSE. Example: "Mid-market logistics firms will pay for automated route
re-planning, replacing the manual dispatch they run in spreadsheets today."

Each turn you are given the conversation so far and the author's latest message. Do THREE things:
1. Write your best single-sentence formalization of their thesis so far, in their own nouns. Fill in
   what they clearly implied; do NOT invent a segment or a substitute they did not gesture at.
2. Decide, for each of {product, buyer, substitute}, whether the thesis now names it.
3. If — and only if — one is still missing or too vague to decompose, ask ONE short, NEUTRAL question
   for each missing element (at most two). A question surfaces what you need; it never argues for a
   framing or leads them toward a more fundable thesis. If nothing load-bearing is missing, ask
   nothing.

Rules:
- Reply in one or two plain sentences. No flattery, no "great idea", no headings.
- Never state the thesis as settled or promising — you are formalizing it, not endorsing it.
- The author owns the final sentence; you propose, they confirm.

Return ONE JSON object exactly matching this schema:

{"reply": "...",
 "proposed_thesis": "<one falsifiable sentence>",
 "subject_present": {"product": true|false, "buyer": true|false, "substitute": true|false},
 "questions": ["<neutral question>", ...]}

Output ONLY the JSON object."""


def _prompt(*, said: str, history: list[dict]) -> str:
    convo = "\n".join(f"{t.get('role', 'user')}: {(t.get('text') or '')[:300]}"
                      for t in (history or [])[-8:])
    return (f"CONVERSATION SO FAR:\n{convo or '(this is the first message)'}\n\n"
            f"THE AUTHOR JUST SAID:\n{said}\n\nReturn the JSON now.")


def project_cost() -> dict:
    return {"calls": 1, "projected_usd": 0.002}


async def turn(llm_json, *, said: str, history: list[dict], budget_left: int) -> dict:
    """One genesis turn. -> {reply, proposed_thesis, questions, ready}. Never raises.

    `ready` is CODE's call over the model's structured output: true when the thesis names all three
    load-bearing elements, or when the budget is spent, or when there is no model — so the user is
    never trapped. Questions are capped at two and only for genuinely-missing elements.
    """
    said = (said or "").strip()
    fallback = {"reply": "", "proposed_thesis": said, "questions": [], "ready": True}
    # No model, or the budget is spent: fall open with the user's own words as the proposed thesis.
    if llm_json is None or budget_left <= 0:
        return fallback
    if not said and not history:
        return fallback
    try:
        raw = await llm_json(_SYSTEM, _prompt(said=said, history=history))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — a genesis turn never blocks the user
        return fallback

    proposed = str(d.get("proposed_thesis") or said).strip()[:600]
    present = d.get("subject_present") or {}
    missing = [e for e in ELEMENTS if not bool(present.get(e))]
    # The model may only ask for elements CODE agrees are missing, capped at two.
    raw_qs = [str(q).strip() for q in (d.get("questions") or []) if str(q).strip()]
    questions = raw_qs[:2] if missing else []
    # Ready is code's, over the model's structured read: all elements present ⇒ decomposable now.
    ready = not missing
    return {"reply": str(d.get("reply") or "").strip()[:800],
            "proposed_thesis": proposed,
            "questions": questions,
            "ready": ready,
            "missing": missing}
