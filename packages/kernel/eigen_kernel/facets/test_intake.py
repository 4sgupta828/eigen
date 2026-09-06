"""Intake gates over opaque keys (kernel — no vocabulary): order of questions, budgets, spread, search-now."""
from __future__ import annotations

from eigen_kernel.facets import Contract, FacetKey, FacetSchema, FacetType
from eigen_kernel.facets.intake import IntakeState, apply_answer, next_question, search_now, spread, worth_asking

SCHEMA = FacetSchema(keys=(FacetKey(key="alpha", type=FacetType.categorical, kinds=("thing",), values=("a", "b", "c")),
                           FacetKey(key="beta", type=FacetType.ordinal, kinds=("thing",), values=("low", "mid", "high")),
                           FacetKey(key="gamma", type=FacetType.categorical, kinds=("thing",), values=("x", "y"))))


def test_spread_and_worth_asking():
    assert spread({"a": 50, "b": 50}) == (0.5, 1.0)
    s, known = spread({"a": 95, "b": 5})
    assert abs(s - 0.05) < 1e-9 and known == 1.0
    assert worth_asking({"a": 50, "b": 50}, constrained=False)
    assert not worth_asking({"a": 95, "b": 5}, constrained=False)          # one value dominates: asking changes nothing
    assert not worth_asking({"a": 50, "b": 50, "unknown": 300}, constrained=False)   # mostly unknown: never filter on it
    assert not worth_asking({"a": 50, "b": 50}, constrained=True)


def test_question_order_required_then_optional_then_ready():
    st = IntakeState(stage="questions", contract=Contract(kind="thing").to_dict())
    counts = {"alpha": {"a": 40, "b": 60}, "beta": {"low": 50, "high": 50}, "gamma": {"x": 99, "y": 1}}
    q = next_question(st, required_items=[], required_keys=["alpha"], optional_keys=["beta", "gamma"], counts=counts)
    assert q.kind == "key" and q.name == "alpha" and q.options[0] == ("b", 60) and q.klass == "required"
    st = apply_answer(st, q, "a", mode="must")
    assert st.contract["must"] == {"alpha": ["a"]}
    q = next_question(st, required_items=[], required_keys=["alpha"], optional_keys=["beta", "gamma"], counts=counts)
    assert q.name == "beta" and q.klass == "optional"                         # gamma is not spread → never asked
    st = apply_answer(st, q, None)                                           # declined: no constraint, budget charged
    assert "beta" not in st.contract.get("prefer", {}) and st.counts_asked["optional"] == 1
    assert next_question(st, required_items=[], required_keys=["alpha"], optional_keys=["beta", "gamma"], counts=counts) is None
    assert st.stage == "ready"


def test_search_now_ends_from_any_stage():
    st = IntakeState(stage="direction")
    assert search_now(st).stage == "ready"
