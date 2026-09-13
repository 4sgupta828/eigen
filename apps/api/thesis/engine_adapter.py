"""Wire the domain-free decision engine (eigen_kernel.decision) to this app's real retrieval and model.

The engine takes injected seams — `gather(question) -> evidence` and `synthesize(question, evidence) ->
answer`. Here we build those from the app's existing evidence machinery (`attack.attack_claim`) and an
LLM, so the kernel never learns what a corpus or a filing is. The active vertical's DecisionProfile
(from the manifest) supplies the aspects, questions directive, and judgment.
"""
from __future__ import annotations

import json

from eigen_kernel.decision import sanitize_answer, NOT_ESTABLISHED


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
You are a diligence analyst answering ONE question about a decision, grounded ONLY in the evidence given.
Write a THOROUGH, evidence-backed answer — not a one-liner.

How to answer:
- Make it substantive and specific. Pull out the concrete facts — the numbers, percentages, dollar
  amounts, named companies/people, dates, mechanisms — that the evidence actually contains. A good
  answer teaches the reader what the record says; a vague gloss ("some firms do X") is a failure.
- Write ONE point per sentence, 4–8 distinct points, EACH covering a DIFFERENT facet (do not restate
  the same fact twice). Order them: the strongest supporting facts, then any contradicting or
  qualifying facts, then what the record leaves open.
- Each sentence leads with the fact (the company, the number, the party) — never with "the evidence"
  or "the record" — and cites the specific evidence id(s) it rests on.
- Report each source in its honest register: a filing or granted patent states a fact; a press
  release, preprint, or forum post is a stated claim or a market signal — never dress a signal up as a
  fact. Where the evidence is one-sided or conflicts, say so.
- Do not invent sources, numbers, or quotes. Every sentence must cite at least one given evidence id.

ALWAYS EXPLAIN — never leave the reader with a bare "not established":
- If the evidence directly answers the question, give the comprehensive cited answer above.
- If it does NOT directly answer it, still be useful: put whatever the record DOES contain that bears
  on the question into `sentences` (cited — e.g. adjacent facts, proxies, related figures), and use
  the `note` field to explain, in plain language, WHAT is missing to settle it and WHAT KIND of source
  would (a filed figure, a named buyer, a benchmark). The note describes our COVERAGE — what we found
  and what we didn't — it never asserts a new fact about the world.
- Only when the record is truly, entirely silent do you leave `sentences` empty — and even then the
  `note` must explain what was searched and what would answer it."""


# What each lens is FOR — so the model frames its answer to the actual intent of the question, not just
# the bare target. Full context (thesis + aspect + intent) makes a one-line target legible.
_LENS_INTENT = {
    "seek_support": "We are looking for evidence that this holds.",
    "seek_contradiction": "This is a red-team probe — we are looking for evidence that UNDERMINES the "
                          "aspect. Finding the statement true counts AGAINST the thesis.",
    "resolve_ambiguity": "The thesis could go two ways here; we want which the record actually shows.",
    "challenge_assumption": "This tests a hidden premise the thesis rests on.",
}


def make_synthesize(llm_json, directive: str | None = None, *, thesis: str = "", aspect: str = ""):
    """Grounded, cited answer per question — carrying FULL CONTEXT: the thesis under test, the aspect of
    it this question probes, and the lens intent (why we ask). The model returns a JSON array of
    sentences each carrying its citation ids; the kernel's `sanitize_answer` gates them and emits
    [[e:<id>]] prose. Never fabricates."""
    system = directive or _SYNTH_DEFAULT

    async def synthesize(question, evidence):
        allowed = [str(e.get("id")) for e in (evidence or []) if e.get("id")]
        listing = "\n".join(
            f"[{e.get('id')}] ({e.get('register', '')}/{e.get('evidence_kind', '')}"
            + (f" · {e.get('source_subject')}" if e.get('source_subject') else "")
            + (f" · {e.get('period')}" if e.get('period') else "") + ") "
            f"{str(e.get('quote') or '')[:400]}" for e in evidence[:16])
        intent = _LENS_INTENT.get(getattr(question, "kind", None) and question.kind.value, "")
        ctx = ""
        if thesis:
            ctx += f"THESIS UNDER TEST: {thesis}\n"
        if aspect:
            ctx += f"ASPECT OF THE THESIS: {aspect}\n"
        if intent:
            ctx += f"WHY WE ASK: {intent}\n"
        empty_note = ("The corpus and open-web search returned nothing that speaks to this question. "
                      "A direct source — a filing, a named figure, or a benchmark — would be "
                      "needed to settle it.")
        if llm_json is None or not allowed:
            # No model, or no evidence at all: still explain rather than leaving a bare gap.
            return "" if llm_json is None else empty_note
        user = (ctx + f"QUESTION: {question.text}\nSTATEMENT UNDER TEST: {question.target}\n\n"
                f"EVIDENCE (cite by the bracketed id):\n{listing}\n\n"
                'Return ONE JSON object: {"sentences": [{"text": "...", "evidence_ids": ["id", ...]}], '
                '"note": "..."}. Write a THOROUGH answer (4–8 sentences) using as much relevant evidence '
                "as possible; each sentence cites its id(s). If the evidence does not fully settle the "
                "question, put what it DOES show in sentences and use `note` to explain what is missing "
                "and what source would settle it. Output ONLY the JSON object.")
        try:
            raw = await llm_json(system, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            items = d.get("sentences") or []
            note = str(d.get("note") or "").strip()
        except Exception:      # noqa: BLE001 — never blocks; falls back to an honest coverage note
            items, note = [], ""
        cited = sanitize_answer(items, allowed)
        if cited and cited != NOT_ESTABLISHED:
            # A real answer, plus the model's caveat about what remains open, when it gave one.
            return cited + ("\n\n" + note if note else "")
        # Nothing qualified: return the honest gap explanation (uncited coverage note), never a bare
        # "not established". The client renders a note (no [[e:id]] markers) as a muted explanation.
        return note or empty_note

    return synthesize
