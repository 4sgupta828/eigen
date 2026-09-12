"""Technology-investing judgment for the generic Test Thesis mechanics.

The app stores and moves evidence; this policy decides when that evidence is strong enough to move
an investment-critical claim.  Keeping the vocabulary and thresholds here lets another vertical
replace the policy without teaching the kernel what an investor, buyer, or funding decision is.
"""
from __future__ import annotations

from dataclasses import dataclass


CRITICAL_RUNGS = frozenset({
    "problem_exists",
    "status_quo_costs",
    "already_spending",
    "buyer_nameable",
    "switching_feasible",
    "willingness_to_pay",
    "enough_buyers",
})

_BLOCKING = frozenset({
    "open",
    "conflicted",
    "under_tested",
    "attack_unavailable",
    "failed",
    "primary_research_needed",
    "unsettleable",
})
_REQUIRED_GATES = ("span_ok", "entailed", "on_subject", "kind_ok", "period_ok")


def _qualified(row: dict) -> bool:
    gates = row.get("gate_results") or {}
    return row.get("relation") in ("supports", "contradicts") and all(
        gates.get(name) is True for name in _REQUIRED_GATES
    )


def _independent(rows: list[dict]) -> int:
    return len({
        str(r.get("independence_key") or r.get("document_id") or r.get("source_url") or "").strip()
        for r in rows
        if str(r.get("independence_key") or r.get("document_id") or r.get("source_url") or "").strip()
    })


@dataclass(frozen=True)
class TechThesisPolicy:
    """Small, deterministic threshold policy; prose generation cannot override it."""

    critical_rungs: frozenset[str] = CRITICAL_RUNGS

    def is_critical(self, rung: str) -> bool:
        return rung in self.critical_rungs

    def qualify(self, evidence: list[dict], *, settleable: str) -> tuple[str, str]:
        usable = [row for row in evidence if _qualified(row)]
        supporting = [row for row in usable if row["relation"] == "supports"]
        contradicting = [row for row in usable if row["relation"] == "contradicts"]

        def enough(rows: list[dict]) -> bool:
            return any(bool(row.get("is_controlling")) for row in rows) or _independent(rows) >= 2

        has_for = enough(supporting)
        has_against = enough(contradicting)
        if has_for and has_against:
            return "conflicted", "Qualified, independent evidence points both ways."
        if has_against:
            return "contradicted", "Qualified evidence contradicts this claim."
        if has_for:
            return "supported", "Qualified evidence supports this claim."

        call_rows = [row for row in usable if row.get("source_key") == "call"]
        if settleable == "call_only" or call_rows:
            return ("primary_research_needed",
                    "One account cannot settle this claim; seek an independent account or corroboration.")
        return "under_tested", "The completed search found no qualifying evidence either way."

    def decide(self, claims: list[dict]) -> dict[str, object]:
        critical = [claim for claim in claims if bool(claim.get("critical"))]
        contradicted = [c for c in critical if c.get("research_status") == "contradicted"]
        if contradicted:
            return {"recommendation": "pass",
                    "decisive_claims": [str(c.get("rung") or "") for c in contradicted],
                    "reason": "A critical claim is contradicted."}

        if critical and all(c.get("research_status") == "supported" for c in critical):
            return {"recommendation": "fund",
                    "decisive_claims": [str(c.get("rung") or "") for c in critical],
                    "reason": "Every critical claim has qualified support and no blocker remains."}

        unresolved = [c for c in critical if c.get("research_status") in _BLOCKING
                      or c.get("research_status") != "supported"]
        return {"recommendation": "continue_diligence",
                "decisive_claims": [str(c.get("rung") or "") for c in unresolved],
                "reason": ("Critical evidence is incomplete or conflicted."
                           if critical else "No decision-critical claims are defined.")}


THESIS_POLICY = TechThesisPolicy()


__all__ = ["CRITICAL_RUNGS", "THESIS_POLICY", "TechThesisPolicy"]
