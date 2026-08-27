"""QuestionContract — Evidence Contract stage 3 (kernel-generic mechanics).

A contract describes the SHAPE of evidence a question requires: `mode` — "enumerative" (the
question demands enumerating concrete candidate items) vs "exploratory" (today's behavior) —
plus the candidate `entities` and the required evidence `axes`. This module owns MECHANICS
only: one small derivation call, structural expansion into retrieval legs, and computable
entity↔claim slot matching. ALL domain vocabulary (which items a practitioner would consider,
which safety/interaction axes matter) lives in the VERTICAL's derivation prompt, supplied via
the manifest — the kernel litmus holds: a legal vertical reuses this file untouched.

Fail-safe (Rule 18): no prompt / LLM error / malformed or abstained output → None → the caller
keeps today's exploratory behavior byte-identical. The LLM owns the semantic judgment (what to
enumerate, which axes are required); code owns the structural expansion + containment checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from eigen_kernel.providers.llm import LLMClient


@dataclass
class Contract:
    mode: str                                  # "enumerative" | "exploratory"
    entities: list[str] = field(default_factory=list)   # candidate items (enumerative mode)
    axes: list[str] = field(default_factory=list)       # required evidence dimensions (short phrases)
    # Evidence STANCE (answer-contract): the vertical-defined regime a question demands — e.g.
    # "current" (news/latest → recency-first) vs "established" (proven/benchmarked/reviewed →
    # authority-first). An OPAQUE string: the kernel never interprets it; the vertical names the
    # stances in its derivation prompt and defines each one's knobs in `answer_profiles`. "" = no
    # stance emitted → the caller keeps its default regime (byte-identical).
    stance: str = ""
    # SUBJECT KIND — an OPAQUE LLM judgment about what the question is ABOUT: "specific_entity" =
    # diligence on ONE named company/product/project; "person" = one named individual;
    # "general" / "" = not (a landscape, how/why, comparison, or any non-single-entity ask).
    # The kernel never interprets it; a vertical's derivation prompt (only when it asks for the
    # field) names the classes. Domain-free (kernel litmus). "" = not emitted → callers keep
    # their default behavior (byte-identical).
    subject_kind: str = ""
    # REFLECTION fields (flag EIGEN_REFLECTION; emitted only by the reflection prompt variant, so a
    # non-reflection derivation leaves them all inert → byte-identical). These carry the "heart of the
    # question" so the caller can steer retrieval + compose toward the user's real intent WITHOUT
    # replacing the literal question. All default to inert values; every consumer guards `if field:`.
    intent: str = ""                       # short inferred user job; "" = none
    intent_confidence: str = ""            # "high" | "medium" | "low" | "" — steer only on high/medium
    answer_brief: str = ""                 # "a great answer must deliver…"; "" = none
    resolved_question: str = ""            # faithful restatement — additive retrieval seed, NEVER a substitute
    ambiguity_risk: str = ""               # "high" | "medium" | "low" | "" — gates the disambiguation probe
    candidates: list[str] = field(default_factory=list)   # distinct candidate readings of an ambiguous subject


class _ContractOut(BaseModel):
    """Structured derivation output. Defaults make abstention safe: an empty/partial emission
    parses as exploratory-with-nothing, which the validator degrades to a no-op contract."""
    mode: str = "exploratory"
    entities: list[str] = []
    axes: list[str] = []
    stance: str = ""                            # evidence regime (vertical-defined); "" = default
    subject_kind: str = ""                       # opaque subject judgment (vertical-defined); "" = default
    intent: str = ""                             # reflection: inferred user job; "" = default
    intent_confidence: str = ""                  # reflection: high|medium|low|""; steer only on high/medium
    answer_brief: str = ""                       # reflection: what a great answer must deliver; "" = default
    resolved_question: str = ""                  # reflection: faithful restatement (additive, never a substitute)
    ambiguity_risk: str = ""                     # reflection: high|medium|low|""; gates the disambiguation probe
    candidates: list[str] = []                   # reflection: distinct candidate readings of an ambiguous subject


async def derive_contract(question: str, llm: LLMClient, derivation_prompt: str | None,
                          max_tokens: int = 400, attempts: int = 2) -> Contract | None:
    """Derive the Contract, RETRYING once on a None result. A None means the derivation call errored or
    emitted an invalid mode — a transient flake that would otherwise silently drop the answer to the thin
    default shape (the muted-answer path). Two attempts make that rare; a genuine no-prompt/no-llm case
    still returns None immediately (no wasted call). The per-attempt logic is `_derive_contract_once`."""
    if llm is None or not (derivation_prompt or "").strip() or not (question or "").strip():
        return None
    for _ in range(max(1, int(attempts))):
        c = await _derive_contract_once(question, llm, derivation_prompt, max_tokens)
        if c is not None:
            return c
    return None


async def _derive_contract_once(question: str, llm: LLMClient, derivation_prompt: str,
                                max_tokens: int) -> Contract | None:
    """ONE small LLM call → Contract, or None on ANY failure (LLM error, invalid mode) — the fail-safe
    is today's behavior, never a heuristic guess."""
    try:
        # NO temperature override: the planner model runs with extended thinking, and the API
        # rejects temperature≠1 there — the bare except then silently killed EVERY derivation
        # (contract None → exploratory fallback; caught via the run-artifact diag). Derivation
        # consistency is carried by the vertical prompt's MANDATORY-inclusion rules instead.
        res = await llm.complete(system=derivation_prompt,
                                 messages=[{"role": "user", "content": question}],
                                 response_format=_ContractOut, max_tokens=max_tokens)
        p = res.parsed
    except Exception:   # noqa: BLE001 — fail-safe: derivation must never break the answer path
        return None
    mode = (getattr(p, "mode", "") or "").strip().lower()
    if mode not in ("enumerative", "exploratory"):
        return None
    entities = [e.strip() for e in (getattr(p, "entities", None) or [])
                if isinstance(e, str) and e.strip()]
    axes = [a.strip() for a in (getattr(p, "axes", None) or [])
            if isinstance(a, str) and a.strip()]
    stance = (getattr(p, "stance", "") or "").strip().lower()   # opaque; validated by the vertical map
    subject_kind = (getattr(p, "subject_kind", "") or "").strip().lower()   # opaque; keep only known classes
    if subject_kind not in ("specific_entity", "person", "general"):
        subject_kind = ""                      # anything else (incl. hallucinated labels) → no-op default
    # REFLECTION fields (inert unless the reflection prompt emitted them). Confidence/risk are clamped to
    # the known enum (a hallucinated label → "" = no-op); free-text fields are stripped; candidates filtered.
    intent = (getattr(p, "intent", "") or "").strip()
    answer_brief = (getattr(p, "answer_brief", "") or "").strip()
    resolved_question = (getattr(p, "resolved_question", "") or "").strip()
    intent_confidence = (getattr(p, "intent_confidence", "") or "").strip().lower()
    if intent_confidence not in ("high", "medium", "low"):
        intent_confidence = ""
    ambiguity_risk = (getattr(p, "ambiguity_risk", "") or "").strip().lower()
    if ambiguity_risk not in ("high", "medium", "low"):
        ambiguity_risk = ""
    candidates = [c.strip() for c in (getattr(p, "candidates", None) or [])
                  if isinstance(c, str) and c.strip()]
    if mode == "enumerative" and not entities and not axes:
        mode = "exploratory"                   # no ROWS and no COLUMNS → nothing to tabulate → inert
        #                                        contract (not None) so the verdict stays observable.
    #  NOTE: enumerative WITH axes but no named entities is KEPT — a "build me a table of all X" ask
    #  names the DIMENSIONS (axes) but not the items; the row entities are DISCOVERED from evidence at
    #  compose (the contract-rendered enumerative shape). The old code demoted this to exploratory,
    #  which is exactly why such asks never tabulated.
    return Contract(mode=mode, entities=entities, axes=axes, stance=stance, subject_kind=subject_kind,
                    intent=intent, intent_confidence=intent_confidence, answer_brief=answer_brief,
                    resolved_question=resolved_question, ambiguity_risk=ambiguity_risk, candidates=candidates)


def render_contract_directive(*, voice: str | None, shapes: dict | None, default: str | None,
                              mode: str, entities=None, axes=None) -> str:
    """CONTRACT-RENDERED COMPOSE (voice ⟂ shape). Assemble the compose directive from the derived
    contract: the universal VOICE + the SHAPE for `mode` (else `default`), and for an ENUMERATIVE shape
    append the contract's concrete items+dimensions so the model builds the exact grid asked for.

    Pure + structural (Rule 18): the kernel selects the shape by `mode` (a structural key) and interpolates
    the item/axis LISTS; it never parses the opaque vertical prose. Voice and shape are ORTHOGONAL — the
    voice never carries a shape verdict, so a shape never fights the voice (no stapled-on contradiction).
    Returns the assembled directive (voice alone if no shape; "" if neither)."""
    v = (voice or "").strip()
    shape = ((shapes or {}).get(mode) or default or "").strip()
    out = (v + "\n\n" + shape) if (v and shape) else (v or shape)
    if mode == "enumerative":
        items = [str(e).strip() for e in (entities or []) if str(e).strip()]
        dims = [str(a).strip() for a in (axes or []) if str(a).strip()]
        if items:
            out += "\n\nITEMS to enumerate (one row each): " + "; ".join(items[:40]) + "."
        if dims:
            out += "\nDIMENSIONS (one column each): " + "; ".join(dims[:12]) + "."
    return out


def build_legs(contract: Contract | None, *, cap: int = 12,
               exclude: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Retrieval-leg queries for a contract, capped at `cap` total, deduped case-insensitively
    against themselves and `exclude` (the graph-leg queries — the unified leg budget's other
    members). Structural expansion only — the meaning lives in the contract. None, or an
    exploratory contract without axes → [] (today's behavior).

    ENUMERATIVE allocation (the act-001 starvation fix): FIRST one AXIS-ONLY leg per axis —
    evidence for a relationship axis often lives on the OTHER side's document (the interaction
    section of the standing treatment's label, not each candidate's), which no
    "<entity> <axis>" query reaches; the axis is itself a retrieval-friendly phrase. THEN
    "<entity> <axis>" legs, axis-major round-robin — with the old allocation and a small cap,
    axes beyond the first never got a single leg (the tacrolimus-interaction axis starved in
    the index case).

    EXPLORATORY (the missed-axes finding: 17%+ of must-cover dimensions absent from answers
    despite usable corpus evidence, because exploratory contracts carried no axes and got no
    legs): AXIS-ONLY legs — each axis verbatim as a query, NO entity expansion, capped at
    min(cap, 4). Entities on an exploratory contract are ignored."""
    if contract is None:
        return []
    # exploratory, OR enumerative WITHOUT named entities (rows discovered from evidence) → AXIS-ONLY
    # legs: each axis verbatim, no entity expansion. The enumerative-no-entities case ("table of all X",
    # dimensions named but items not) fans out on the dimensions so the rows can be discovered.
    if contract.mode == "exploratory" or (contract.mode == "enumerative" and not contract.entities):
        if not contract.axes:
            return []
        cap = min(cap, 4)
        axes: list[str] = contract.axes
        entities: list[str] = []               # axis-only: no entity expansion
    elif contract.mode == "enumerative" and contract.entities:
        axes = contract.axes or [""]
        entities = contract.entities
    else:
        return []
    seen = {q.strip().lower() for q in exclude if q and q.strip()}
    out: list[str] = []

    def _add(q: str) -> bool:
        """Append q if novel; return False once the cap is reached."""
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
        return len(out) < cap

    for axis in axes:                      # axis-only legs: cover every REQUIRED dimension first
        if axis.strip() and not _add(axis):
            return out
    for axis in axes:                      # then per-entity legs, axis-major round-robin
        for entity in entities:
            if not _add(f"{entity} {axis}"):
                return out
    return out


def match_entities(entities: list[str], text: str, title: str = "") -> list[str]:
    """Which contract entities a claim FILLS: case-insensitive containment of the entity name
    in the claim text OR its document title. This is computable set membership against the
    contract's OWN closed entity list (Rule 18: code owns structure — no semantic judgment is
    made here; the entity list itself was LLM-derived)."""
    hay = f"{text or ''}\n{title or ''}".lower()
    return [e for e in entities if e and e.strip() and e.strip().lower() in hay]
