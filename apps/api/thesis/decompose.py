"""Thesis -> claims. One model call, and the model does not get to judge anything.

The ladder in `schema.py` is FIXED. The model's only job is to instantiate each rung for this
particular thesis — what is the problem, who has it, which segment, what is the substitute — in the
concrete language of the thesis rather than the abstract language of the rung.

It never decides `settleable`. That comes from the schema, because a model that has just written an
encouraging sentence about willingness to pay will happily mark it settleable, and willingness to pay
for a product that does not exist is exactly the thing no document can settle. Hardcoding it is the
difference between a stress test and a mirror.
"""
from __future__ import annotations

import json

from .schema import LADDER, QUESTION, SETTLEABLE

_SYSTEM = """\
You turn a startup thesis into the specific, falsifiable claims it rests on.

You are given a THESIS and a fixed LADDER of questions. For each rung, write the claim THIS thesis
needs to be true, in the concrete nouns of the thesis — the actual product, buyer, segment and
substitute — not the abstract words of the rung.

Rules:
- A claim must be capable of being FALSE. "Will it sell" is not a claim. "Mid-market logistics firms
  already pay for route-optimisation software" is.
- Use the thesis's own segment and product words. Never widen to "companies" or "the market".
- No hedging, no "may", no "could". State it flatly so it can be attacked.
- If a rung genuinely does not apply to this thesis, still write the claim it would need; do not skip.
- Do NOT judge whether a claim is true, likely, or checkable. That is not your job here.

Also extract the subject: the product, the buyer segment, the incumbent or substitute it replaces,
and the job it does.

Return ONE JSON object exactly matching this schema:

{"subject": {"product": "...", "segment": "...", "substitute": "...", "job": "..."},
 "claims": [{"rung": "<rung key>", "claim": "<falsifiable sentence>"}]}

Output ONLY the JSON object."""


def _prompt(thesis: str) -> str:
    rungs = "\n".join(f"- {k}: {QUESTION[k]}" for k, _q, _s, _w in LADDER)
    return f"THESIS:\n{thesis.strip()}\n\nLADDER:\n{rungs}\n\nReturn the JSON now."


def project_cost() -> dict:
    """One small call. Priced like the other single-shot compilers in the app."""
    return {"calls": 1, "projected_usd": 0.002}


async def decompose(llm_json, thesis: str) -> dict:
    """-> {"subject": {...}, "claims": [{rung, claim, settleable}]}.

    `llm_json` is the app's JSON-chat seam (the same one startups/investors use). With no model
    configured we still return the full ladder, with each rung carrying the generic question as its
    claim — a thinner thesis, never a failed one.
    """
    t = (thesis or "").strip()
    if not t:
        return {"subject": {}, "claims": []}

    data: dict = {}
    if llm_json is not None:
        try:
            # The app's JSON seam is POSITIONAL — `llm_json(system, user) -> dict` (startups/
            # pipeline.py). Calling it with keywords raises, the except swallows it, and the ladder
            # comes back generic with nothing to say that it failed. Matched deliberately.
            raw = await llm_json(_SYSTEM, _prompt(t))
            data = raw if isinstance(raw, dict) else json.loads(raw)
        except Exception:      # noqa: BLE001 — a decomposer we cannot reach is a generic ladder
            data = {}

    by_rung = {}
    for c in (data.get("claims") or []):
        k = str((c or {}).get("rung") or "").strip()
        txt = str((c or {}).get("claim") or "").strip()
        if k in SETTLEABLE and txt:
            by_rung[k] = txt

    claims = []
    for k, q, _s, _w in LADDER:
        claims.append({
            "rung": k,
            "claim": by_rung.get(k) or q,       # the rung's own question is the honest fallback
            # NOT from the model. Ever.
            "settleable": SETTLEABLE[k],
        })
    subject = data.get("subject") if isinstance(data.get("subject"), dict) else {}
    return {"subject": {k: str(v)[:200] for k, v in (subject or {}).items() if v}, "claims": claims}
