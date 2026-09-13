"""Wire the domain-free decision engine (eigen_kernel.decision) to this app's real retrieval and model.

The engine takes injected seams — `gather(question) -> evidence` and `synthesize(question, evidence) ->
answer`. Here we build those from the app's existing evidence machinery (`attack.attack_claim`) and an
LLM, so the kernel never learns what a corpus or a filing is. The active vertical's DecisionProfile
(from the manifest) supplies the aspects, questions directive, and judgment.
"""
from __future__ import annotations

import json
import re

from eigen_kernel.decision import sanitize_answer, sanitize_table, NOT_ESTABLISHED

# Distinctive tokens for citation recovery: multi-digit numbers (750, 20, 1000, 5.6) and proper
# nouns / model names (OpenAI, AlphaSense, WSE-3, GPT-5.6). These are what tie a sentence to the
# specific source it was drawn from; common words are not distinctive and are ignored.
_NUM = re.compile(r"\d[\d.,]*\d|\d")
_PROP = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
_STOP = {"The", "This", "That", "These", "Those", "Cerebras", "There", "While", "However", "Their",
         "It", "Its", "A", "An", "In", "On", "For", "As", "Named", "Specific", "Further"}


def _distinctive(text: str) -> tuple[set, set]:
    nums = {n.replace(",", "") for n in _NUM.findall(text or "") if len(n.replace(",", "").replace(".", "")) >= 2}
    props = {p for p in _PROP.findall(text or "") if len(p) >= 4 and p not in _STOP}
    return nums, props


def _haystacks(evidence: list[dict]) -> list:
    hs = []
    for e in evidence or []:
        eid = str(e.get("id") or "")
        if not eid:
            continue
        txt = str(e.get("block_text") or e.get("quote") or "")
        hn, hp = _distinctive(txt)
        hs.append((eid, hn, {p.lower() for p in hp}, txt.lower()))
    return hs


def _bind_ids(text: str, haystacks: list) -> list[str]:
    """The evidence id(s) whose source text contains this text's distinctive tokens (a shared number, or
    ≥2 shared proper nouns). [] when nothing matches — the caller then drops the unit, so grounding stays
    honest. Used to rescue a sentence OR a table row the model wrote but forgot to tag."""
    snums, sprops = _distinctive(text or "")
    sprops_l = {p.lower() for p in sprops}
    scored = []
    for eid, hn, hp, hl in haystacks:
        num_hit = len(snums & hn)
        prop_hit = len(sprops_l & hp)
        prop_sub = sum(1 for p in sprops_l if len(p) >= 5 and p in hl)   # multi-word entities
        score = num_hit * 2 + max(prop_hit, prop_sub)
        if num_hit >= 1 or prop_hit >= 2 or prop_sub >= 2:
            scored.append((score, eid))
    scored.sort(reverse=True)
    return [eid for _s, eid in scored[:2]]


def _recover_citations(items: list[dict], evidence: list[dict]) -> list[dict]:
    """When the model writes a factual sentence but forgets its `evidence_ids`, bind it to the evidence
    row(s) whose source text actually contains its distinctive tokens. Keeps grounding honest — a
    sentence that matches no source stays uncited and is dropped downstream — while rescuing real
    findings the model failed to tag. Sentences the model DID cite are left untouched."""
    haystacks = _haystacks(evidence)
    out = []
    for it in items or []:
        ids = [str(x) for x in ((it or {}).get("evidence_ids") or []) if str(x)]
        if ids:
            out.append(it); continue
        text = str((it or {}).get("text") or "")
        if not text.strip():
            continue
        bound = _bind_ids(text, haystacks)
        if bound:
            out.append({**it, "evidence_ids": bound})
        # else: no source contains this sentence's specifics → drop it (sanitize would too)
    return out


def _recover_table(table, evidence: list[dict]):
    """Same rescue for a comparison table: a row the model left untagged is bound to the source whose
    text contains the row's distinctive tokens (the entity name + its metrics). Without this, a table
    the model built but forgot to cite is dropped whole and the answer collapses to a bare note — the
    exact failure this repairs."""
    if not isinstance(table, dict) or not (table.get("rows") or []):
        return table
    haystacks = _haystacks(evidence)
    rows = []
    for r in (table.get("rows") or []):
        ids = [str(x) for x in ((r or {}).get("evidence_ids") or []) if str(x)]
        if ids:
            rows.append(r); continue
        cells = [str(c) for c in ((r or {}).get("cells") or [])]
        bound = _bind_ids(" ".join(cells), haystacks)
        if bound:
            rows.append({**r, "evidence_ids": bound})
        # else: row binds to no source → dropped (sanitize_table would too)
    return {**table, "rows": rows}


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

SHAPE THE ANSWER for the question — do not default to a wall of prose:
- When you are COMPARING or ENUMERATING several items across the same attributes (tools, vendors,
  companies, options, metrics side by side), return a `table`: give `columns` and one `row` per item,
  each row citing its own evidence_ids. A table is far more consumable than prose for a comparison.
- When you are listing several DISTINCT facts that do not share a common structure, set
  "layout":"bullets" so each point renders as its own bullet.
- Use "layout":"prose" only for a genuinely short narrative answer (one or two connected points).
- You may use BOTH: a `table` for the comparison plus a couple of `sentences` that summarize or caveat
  it. Every row and every sentence still cites its evidence_ids — a table row is grounded exactly like
  a sentence, so never put an uncited cell in it.
- BUILD THE STRUCTURE FROM WHAT YOU HAVE: if the question compares or enumerates items (e.g. "all major
  CRMs"), give the table/bullets for the items the evidence DOES cover — never withhold the table just
  because the list may not be exhaustive. Put "which items are missing / not covered" in `note`, not in
  place of the table. A comparison table over 4 named items plus a note beats a bare "would need more
  sources" every time.

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
        # Give the model the FULLER source text (block_text — the whole passage the row was drawn from,
        # e.g. Exa's query-aware highlights + body), not just the 400-char display quote, so the answer
        # has real material to reason over. It still cites by evidence id; congruence was gated at
        # retrieval, so showing more of the same passage deepens the answer without loosening grounding.
        def _ctx(e):
            return (str(e.get("block_text") or e.get("quote") or "").strip()[:1400]) or ""
        listing = "\n".join(
            f"[{e.get('id')}] ({e.get('register', '')}/{e.get('evidence_kind', '')}"
            + (f" · {e.get('source_subject')}" if e.get('source_subject') else "")
            + (f" · {e.get('period')}" if e.get('period') else "") + ") "
            f"{_ctx(e)}" for e in evidence[:20])
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
        eg = allowed[0] if allowed else "abc123"
        user = (ctx + f"QUESTION: {question.text}\nSTATEMENT UNDER TEST: {question.target}\n\n"
                f"EVIDENCE (cite by the bracketed id):\n{listing}\n\n"
                'Return ONE JSON object: {"layout": "bullets"|"prose", '
                '"sentences": [{"text": "...", "evidence_ids": ["<id>", ...]}], '
                '"table": {"columns": ["...", "..."], "rows": [{"cells": ["...", "..."], '
                '"evidence_ids": ["<id>"]}]} , "note": "..."}. Use as much relevant evidence as possible.\n'
                "Choose the SHAPE that makes the answer most consumable: a `table` when comparing or "
                "enumerating items across attributes (omit `table` otherwise); \"bullets\" for a list of "
                "distinct facts; \"prose\" only for a short narrative. You may combine a table with a few "
                "summarizing sentences.\n"
                "CITATIONS ARE MANDATORY on every sentence AND every table row: list the exact bracketed "
                'id(s) it rests on in `evidence_ids` — e.g. {"text": "OpenAI runs GPT-5.6 inference on '
                'Cerebras WSE-3 at 750 tokens/sec.", "evidence_ids": ["' + eg + '"]}. A sentence or row '
                "with empty/missing evidence_ids is DROPPED, so never leave it out. If the evidence does "
                "not settle the question, put what it DOES show (still cited) and use `note` to explain "
                "what is missing and what source would settle it. Output ONLY the JSON object.")
        try:
            raw = await llm_json(system, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            items = d.get("sentences") or []
            table = d.get("table")
            layout = str(d.get("layout") or "").strip().lower()
            note = str(d.get("note") or "").strip()
        except Exception:      # noqa: BLE001 — never blocks; falls back to an honest coverage note
            items, table, layout, note = [], None, "", ""
        # Rescue findings the model wrote but forgot to tag: bind each uncited sentence to the source
        # that actually contains its specifics, so a rich answer never collapses to "not established"
        # over a missing id. The strict gate below still drops anything that binds to no source.
        items = _recover_citations(items, evidence)
        table = _recover_table(table, evidence)
        table_md = sanitize_table(table, allowed)
        # bullets by default for a multi-point answer; prose only when the model asked for it and there
        # is no table alongside. A table renders its rows; the sentences frame or caveat it.
        use_bullets = layout != "prose" and (bool(table_md) or len(items) > 1)
        points = sanitize_answer(items, allowed, bullets=use_bullets)
        parts = [p for p in (table_md, (points if points != NOT_ESTABLISHED else "")) if p]
        cited = "\n\n".join(parts)
        if cited:
            # A real answer, plus the model's caveat about what remains open, when it gave one.
            return cited + ("\n\n" + note if note else "")
        # Nothing qualified: return the honest gap explanation (uncited coverage note), never a bare
        # "not established". The client renders a note (no [[e:id]] markers) as a muted explanation.
        return note or empty_note

    return synthesize
