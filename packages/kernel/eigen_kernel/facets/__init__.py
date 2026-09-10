"""Facets, contracts and the evaluator — the one mechanism behind search, navigation, calibration and
refresh (docs/specs/facet-contract-evaluator.md). Domain-free: keys and vocabularies come from the
vertical manifest; this package knows types, grammar, filtering, ranking and counting."""
from .contract import MODES, Contract, edit, state_of, validate_contract
from .evaluate import FacetWeights, calibrated_pct, diagnose_musts, evaluate, pool_from_counts
from .directions import (Direction, cluster_directions, facet_directions, rank_directions, worth_steering)
from .intent_check import IntentCheck, Reading, evidence, history_pack, worth_asking
from .intent_check import parse as parse_intent
from .lexicon import LexiconPlan, Span, find_spans, plan_from_spans
from .schema import UNKNOWN, FacetKey, FacetSchema, FacetType
from .store import FacetStore, InMemoryFacetStore, count_rows, matches_must

__all__ = ["UNKNOWN", "Contract", "FacetKey", "FacetSchema", "FacetStore", "FacetType", "FacetWeights", "InMemoryFacetStore",
           "Direction", "IntentCheck", "LexiconPlan", "Reading", "Span", "cluster_directions",
           "evidence", "facet_directions", "find_spans", "history_pack", "parse_intent", "worth_asking",
           "plan_from_spans", "rank_directions", "worth_steering",
           "MODES", "calibrated_pct", "count_rows", "diagnose_musts", "edit", "evaluate", "matches_must", "pool_from_counts", "state_of", "validate_contract"]
