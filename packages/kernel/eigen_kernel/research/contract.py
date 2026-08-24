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
    # diligence on ONE named company/product/project; "general" / "" = not (a landscape, how/why,
    # comparison, or any non-single-entity ask). The kernel never interprets it; a vertical's
    # derivation prompt (only when it asks for the field) names the classes. Domain-free (kernel
    # litmus). "" = not emitted → callers keep their default behavior (byte-identical).
    subject_kind: str = ""


class _ContractOut(BaseModel):
    """Structured derivation output. Defaults make abstention safe: an empty/partial emission
    parses as exploratory-with-nothing, which the validator degrades to a no-op contract."""
    mode: str = "exploratory"
    entities: list[str] = []
    axes: list[str] = []
    stance: str = ""                            # evidence regime (vertical-defined); "" = default
    subject_kind: str = ""                       # opaque subject judgment (vertical-defined); "" = default


async def derive_contract(question: str, llm: LLMClient, derivation_prompt: str | None,
                          max_tokens: int = 400) -> Contract | None:
    """ONE small LLM call → Contract, or None on ANY failure (no prompt, LLM error, invalid
    mode) — the fail-safe is today's behavior, never a heuristic guess. An enumerative verdict
    with zero entities cannot steer anything, so it degrades to exploratory (valid, inert)."""
    if llm is None or not (derivation_prompt or "").strip() or not (question or "").strip():
        return None
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
    if subject_kind not in ("specific_entity", "general"):
        subject_kind = ""                      # anything else (incl. hallucinated labels) → no-op default
    if mode == "enumerative" and not entities:
        mode = "exploratory"                   # nothing to enumerate → inert contract, not None,
        #                                        so the derivation verdict stays observable in diag
    return Contract(mode=mode, entities=entities, axes=axes, stance=stance, subject_kind=subject_kind)


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
    if contract.mode == "exploratory":
        if not contract.axes:
            return []
        cap = min(cap, 4)
        axes: list[str] = contract.axes
        entities: list[str] = []               # axis-only: no entity expansion for exploratory
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
