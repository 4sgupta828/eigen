"""Bind candidate spans to a claim without trusting the query that discovered them.

Discovery provides recall. This seam decides whether an exact source span supports, contradicts, or
merely contextualizes a claim while retaining the identity needed to audit that decision. A missing
or malformed semantic judge fails closed to context.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json


@dataclass(frozen=True)
class EvidenceCandidate:
    id: str
    quote: str
    block_text: str
    document_id: str
    block_id: str
    source_subject: str = ""
    evidence_kind: str = ""
    period: str = ""
    facets: dict = field(default_factory=dict)
    signal_only: bool = False
    discovery_side: str = ""


_SYSTEM = """\
Judge how each exact source span relates to the claim. Discovery direction is not evidence polarity.
For each candidate return: candidate_id; relation supports|contradicts|context; and booleans entailed,
on_subject, kind_ok, period_ok. `entailed` means the quoted words directly warrant the relationship.
`on_subject` means the source subject is the claim subject. `kind_ok` means this type of evidence can
establish what the claim asserts. `period_ok` means its time period applies. When unsure, use context
and false. Return only {"bindings":[...]} JSON."""


def _base(candidate: EvidenceCandidate, *, span_ok: bool) -> dict:
    row = asdict(candidate)
    row.pop("block_text", None)
    row["span_hash"] = hashlib.sha256(candidate.quote.encode("utf-8")).hexdigest()
    row["relation"] = "signal" if candidate.signal_only else "context"
    row["gate_results"] = {"span_ok": span_ok, "entailed": False, "on_subject": False,
                           "kind_ok": False, "period_ok": False}
    row["reason"] = ("Signal-only material is non-decisive." if candidate.signal_only
                     else "Semantic binding unavailable.")
    return row


def _prompt(claim: str, candidates: list[EvidenceCandidate]) -> str:
    payload = {
        "claim": claim,
        "candidates": [{
            "candidate_id": c.id,
            "quote": c.quote,
            "source_subject": c.source_subject,
            "evidence_kind": c.evidence_kind,
            "period": c.period,
        } for c in candidates],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def bind_candidates(claim: str, candidates: list[EvidenceCandidate], judge_llm) -> list[dict]:
    """Return persistence-ready rows with stable provenance and fail-closed gate outcomes."""
    rows: dict[str, dict] = {}
    judgeable: list[EvidenceCandidate] = []
    for candidate in candidates:
        span_ok = bool(candidate.quote) and candidate.quote in (candidate.block_text or "")
        rows[candidate.id] = _base(candidate, span_ok=span_ok)
        if span_ok and not candidate.signal_only:
            judgeable.append(candidate)

    if not judgeable or judge_llm is None:
        return [rows[c.id] for c in candidates]

    try:
        raw = await judge_llm(_SYSTEM, _prompt(claim, judgeable))
        parsed = raw if isinstance(raw, dict) else json.loads(raw)
        bindings = parsed.get("bindings") if isinstance(parsed, dict) else []
    except Exception:  # a judge outage cannot promote evidence
        bindings = []

    known = {candidate.id for candidate in judgeable}
    for binding in bindings or []:
        if not isinstance(binding, dict):
            continue
        candidate_id = str(binding.get("candidate_id") or "")
        if candidate_id not in known:
            continue
        gates = {"span_ok": True,
                 "entailed": binding.get("entailed") is True,
                 "on_subject": binding.get("on_subject") is True,
                 "kind_ok": binding.get("kind_ok") is True,
                 "period_ok": binding.get("period_ok") is True}
        requested = str(binding.get("relation") or "context").strip().lower()
        decisive = requested in ("supports", "contradicts") and all(gates.values())
        rows[candidate_id]["relation"] = requested if decisive else "context"
        rows[candidate_id]["gate_results"] = gates
        rows[candidate_id]["reason"] = str(binding.get("reason") or "")[:400]

    return [rows[c.id] for c in candidates]


__all__ = ["EvidenceCandidate", "bind_candidates"]
