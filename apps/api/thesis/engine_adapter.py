"""Wire the domain-free decision engine (eigen_kernel.decision) to this app's real retrieval and model.

The engine takes injected seams — `gather(question) -> evidence` and `synthesize(question, evidence) ->
answer`. Here we build those from the app's existing evidence machinery (`attack.attack_claim`) and an
LLM, so the kernel never learns what a corpus or a filing is. The active vertical's DecisionProfile
(from the manifest) supplies the aspects, questions directive, and judgment.
"""
from __future__ import annotations

import json

from eigen_kernel.decision import sanitize_answer


def make_gather(attack_fn):
    """attack_fn(target: str) -> {"evidence": [...]}. Returns a gather cached by target STRING, so two
    questions with the same declarative target (e.g. a seek-support pair) share ONE retrieval — the
    panel's cost fix, without the kernel knowing anything about it."""
    cache: dict[str, list] = {}

    async def gather(question):
        target = question.target
        if target not in cache:
            try:
                res = await attack_fn(target)
                cache[target] = (res or {}).get("evidence", []) or []
            except Exception:      # noqa: BLE001 — a failed retrieval leaves the question untested
                cache[target] = []
        return cache[target]

    return gather


_SYNTH_DEFAULT = """\
You answer ONE question about a decision using ONLY the evidence given. State what the evidence shows,
in its honest register — a filing states a fact, a press release or forum post is a stated claim or a
market signal, never dressed up as more. Do not invent sources, numbers, or quotes. If the evidence does
not answer the question, return an empty list."""


def make_synthesize(llm_json, directive: str | None = None):
    """Grounded, cited answer per question. The model returns a JSON array of sentences each carrying
    its own citation ids; the kernel's `sanitize_answer` gates them (an id must resolve; an uncited or
    wrongly-cited sentence is dropped) and emits [[e:<id>]] prose. Never fabricates."""
    system = directive or _SYNTH_DEFAULT

    async def synthesize(question, evidence):
        allowed = [str(e.get("id")) for e in (evidence or []) if e.get("id")]
        if llm_json is None or not allowed:
            return ""
        listing = "\n".join(
            f"[{e.get('id')}] ({e.get('register', '')}/{e.get('evidence_kind', '')}) "
            f"{str(e.get('quote') or '')[:220]}" for e in evidence[:8])
        user = (f"QUESTION: {question.text}\nSTATEMENT UNDER TEST: {question.target}\n\n"
                f"EVIDENCE (cite by the bracketed id):\n{listing}\n\n"
                'Return ONE JSON object: {"sentences": [{"text": "...", "evidence_ids": ["id", ...]}]}. '
                "Each sentence states only what its cited evidence shows. Output ONLY the JSON object.")
        try:
            raw = await llm_json(system, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            items = d.get("sentences") or []
        except Exception:      # noqa: BLE001 — no prose is fine; the verdict rests on evidence, not narrative
            items = []
        return sanitize_answer(items, allowed)

    return synthesize
