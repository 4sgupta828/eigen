"""Intake gates over opaque keys (kernel — no vocabulary): order of questions, budgets, spread, search-now, the
measured shortlist a model may choose from, and the memory a later turn reads back."""
from __future__ import annotations

from eigen_kernel.facets import Contract, FacetKey, FacetSchema, FacetType
from eigen_kernel.facets.intake import (IntakeState, accept_question, apply_answer, askable, next_question, remember,
                                        search_now, spread, worth_asking)
from eigen_kernel.facets.schema import UNKNOWN

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


# ---------------------------------------------------------------- the measured shortlist
def _st(**kw):
    return IntakeState(**kw)


def test_askable_drops_what_the_index_cannot_answer():
    """Two ways a key fails to earn a question: the index barely knows it, or it cannot divide the pool."""
    counts = {"known_and_split": {"a": 50, "b": 50},
              "barely_known": {"a": 5, "b": 3, UNKNOWN: 892},        # 0.9% known — nothing to filter on
              "known_but_uniform": {"a": 995, "b": 5},               # known for all, divides nothing
              "single_value": {"a": 900}}                            # not a choice at all
    got = askable(_st(), keys=list(counts), counts=counts)
    assert [a.key for a in got] == ["known_and_split"]


def test_askable_skips_what_is_asked_or_already_constrained():
    counts = {"x": {"a": 50, "b": 50}, "y": {"a": 50, "b": 50}}
    st = _st(asked=["x"], contract={"must": {"y": ["a"]}})
    assert askable(st, keys=["x", "y"], counts=counts) == []


def test_askable_ranks_by_how_much_an_answer_would_move_the_slice():
    counts = {"weak": {"a": 90, "b": 10}, "strong": {"a": 50, "b": 50}}
    assert [a.key for a in askable(_st(), keys=["weak", "strong"], counts=counts)] == ["strong", "weak"]


# ---------------------------------------------------------------- a model may choose and phrase, never invent
def _allowed():
    return askable(_st(), keys=["colour"], counts={"colour": {"red": 40, "blue": 60}})


def test_accept_question_refuses_a_key_that_was_not_measured():
    assert accept_question(_st(), {"kind": "key", "key": "smell", "words": "Which smell?"}, allowed=_allowed()) is None


def test_accept_question_takes_its_options_from_the_counts_not_the_model():
    q = accept_question(_st(), {"kind": "key", "key": "colour", "words": "Which colour?", "options": ["red", "octarine"]}, allowed=_allowed())
    assert q is not None and [v for v, _ in q.options] == ["blue", "red"]      # the invented value is dropped…
    q2 = accept_question(_st(), {"kind": "key", "key": "colour", "words": "?", "options": ["red", "blue"]}, allowed=_allowed())
    assert [v for v, _ in q2.options] == ["blue", "red"]                       # …and a legal pair narrows nothing away


def test_accept_question_refuses_an_unusable_proposal_and_honours_the_budget():
    assert accept_question(_st(), None, allowed=_allowed()) is None
    assert accept_question(_st(), {"kind": "key", "key": "colour"}, allowed=_allowed()) is None       # no words
    spent = _st(counts_asked={"analyst": 4}, budgets={"analyst": 4})
    assert accept_question(spent, {"kind": "key", "key": "colour", "words": "?"}, allowed=_allowed()) is None


def test_an_open_question_needs_no_key_and_carries_its_own_words():
    q = accept_question(_st(), {"kind": "open", "key": "layer", "words": "Which layer?", "why": "different businesses",
                                "options": ["one", "two"]}, allowed=[])
    assert q.kind == "open" and q.name == "layer" and q.words == "Which layer?" and [v for v, _ in q.options] == ["one", "two"]


def test_an_open_answer_never_becomes_a_contract_key():
    q = accept_question(_st(), {"kind": "open", "key": "layer", "words": "Which layer?"}, allowed=[])
    n = apply_answer(_st(), q, "training")
    assert "layer" not in (n.contract.get("must") or {}) and n.answers["layer"] == "training" and "layer" in n.asked


# ---------------------------------------------------------------- memory
def test_remember_carries_the_read_back_and_dedupes_what_was_ruled_out():
    n = remember(_st(), understanding="  they want infrastructure  ", ruled_out=["consumer", "consumer", "hardware"])
    assert n.understanding == "they want infrastructure" and n.ruled_out == ["consumer", "hardware"]
    n2 = remember(n, ruled_out=["consumer", "gaming"])
    assert n2.ruled_out == ["consumer", "hardware", "gaming"]
    assert IntakeState.from_dict(n2.to_dict()).ruled_out == n2.ruled_out      # it survives the round trip
