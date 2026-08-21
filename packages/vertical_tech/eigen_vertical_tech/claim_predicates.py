"""Slice-1 competitive-landscape predicate registry (VERTICAL-owned vocabulary).

The claim-graph STORE (`apps/api/claimgraph.py`) is domain-neutral: entity kinds,
predicate names, and their object/temporal policies arrive as DATA. This module is
that data for the tech vertical — the ~6 load-bearing predicates that make a real
competitive-landscape answer groundable (panel call: ~6, not 3, not ~10).

Keeping the vocabulary here (not in the store) honors the kernel/vertical split:
the store consumes `SLICE1_PREDICATES` in `ensure_schema()` and seeds them into
`rs_predicate` (idempotent, `ON CONFLICT DO NOTHING` so a later status change is
never clobbered). The LLM owns which predicate a span asserts (Rule 18); code only
validates the emitted name against this closed registry.

Each entry:
  name            — the predicate key (must be stable; it is a claim's `predicate`).
  status          — 'active' (production extraction emits only active predicates).
  object_kind     — 'value' (a text/number literal) | 'entity' (a ref to another
                    resolved entity) | 'either'.
  cardinality     — 'single' (one current value per subject) | 'multi' (a set).
  temporal_policy — 'static' | 'point' | 'interval'. Slice-1 landscape facts are
                    treated as static (no valid_time churn); Slice-2+ widen this.
  description     — human/LLM-facing gloss of what the predicate asserts.
"""
from __future__ import annotations

SLICE1_PREDICATES: list[dict] = [
    {
        "name": "operates_in_category",
        "status": "active",
        "object_kind": "entity",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company operates in / competes within the "
                       "given market category (object is a category entity). This "
                       "is the claim that PLACES a company on the landscape map.",
    },
    {
        "name": "offers_product",
        "status": "active",
        "object_kind": "value",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company offers the named product or product "
                       "line (object is the product name as stated).",
    },
    {
        "name": "targets_customer",
        "status": "active",
        "object_kind": "value",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company targets the named customer segment / "
                       "buyer / market (e.g. 'enterprise', 'SMB', 'developers').",
    },
    {
        "name": "uses_technology",
        "status": "active",
        "object_kind": "value",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company builds on / uses the named technology, "
                       "approach, or architecture (object is the technology name).",
    },
    {
        "name": "claims_differentiator",
        "status": "active",
        "object_kind": "value",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company asserts the named differentiator / "
                       "positioning claim about itself (object is the claim text).",
    },
    {
        "name": "compared_to",
        "status": "active",
        "object_kind": "entity",
        "cardinality": "multi",
        "temporal_policy": "static",
        "description": "The subject company is compared to / positioned against "
                       "another company (object is a company entity) — the direct "
                       "competitor / substitute signal.",
    },
]
