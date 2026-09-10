"""TDD for directions (kernel — docs/specs/intent-convergence-loop.md §3).

Pure: no DB, no model, no domain vocabulary.
"""
from __future__ import annotations

from eigen_kernel.facets import FacetKey, FacetSchema, FacetType
from eigen_kernel.facets.directions import (Direction, cluster_directions, facet_directions,
                                             rank_directions, worth_steering)

SCHEMA = FacetSchema(keys=(
    FacetKey(key="mode", type=FacetType.categorical, kinds=("thing",), label="Mode",
             values=("remote", "hybrid", "onsite")),
    FacetKey(key="tier", type=FacetType.ordinal, kinds=("thing",), label="Tier",
             values=("junior", "mid", "senior", "staff_plus")),
))


def test_a_direction_is_offered_only_when_it_would_actually_change_the_set():
    """A value holding 98 % of the slice is not a choice — picking it changes nothing, and picking
    against it leaves nothing."""
    counts = {"mode": {"remote": 98, "onsite": 2}}
    assert facet_directions(counts, SCHEMA, "thing") == []
    counts = {"mode": {"remote": 50, "onsite": 50}}
    got = facet_directions(counts, SCHEMA, "thing")
    assert {d.values[0] for d in got} == {"remote", "onsite"}
    assert all(d.hits == 50 and d.score > 0.9 for d in got)


def test_a_split_near_half_beats_a_lopsided_one():
    counts = {"mode": {"remote": 50, "onsite": 50}, "tier": {"senior": 90, "junior": 10}}
    ranked = rank_directions(facet_directions(counts, SCHEMA, "thing"), top=2)
    assert ranked[0].key == "mode"


def test_the_menu_asks_three_different_questions_not_three_values_of_one():
    counts = {"mode": {"remote": 34, "hybrid": 33, "onsite": 33},
              "tier": {"senior": 55, "junior": 45}}
    ranked = rank_directions(facet_directions(counts, SCHEMA, "thing"), top=3)
    assert len({d.key for d in ranked}) == len(ranked), "one direction per key"


def test_an_emergent_cluster_is_offered_both_ways_round():
    """'These are mostly agency reposts' is most useful as a way to say NOT THAT — and `avoid` is a
    thing the contract already carries."""
    groups = [{"name": "tour guide", "ids": [1, 2, 3, 4]}]
    got = cluster_directions(groups, 10)
    assert {d.section for d in got} == {"must", "avoid"}
    keep = next(d for d in got if d.section == "must")
    drop = next(d for d in got if d.section == "avoid")
    assert keep.hits == 4 and drop.hits == 6
    assert drop.label == "not tour guide"


def test_only_one_half_of_a_cluster_reaches_the_menu():
    groups = [{"name": "tour guide", "ids": [1, 2, 3, 4, 5]}]
    ranked = rank_directions(cluster_directions(groups, 10), top=3)
    assert len(ranked) == 1, "keep-these and drop-these are one question, not two"


def test_facet_and_cluster_candidates_are_comparable_on_one_scale():
    """The whole point of the shared score: a seniority split and an emergent cluster have to be
    rankable against each other, or the menu is just whichever source ran first."""
    counts = {"tier": {"senior": 90, "junior": 10}}          # lopsided facet
    groups = [{"name": "tour guide", "ids": list(range(5))}]  # even cluster
    ranked = rank_directions(facet_directions(counts, SCHEMA, "thing") + cluster_directions(groups, 10), top=1)
    assert ranked[0].source == "cluster"


# ---------------------------------------------------------------- the gate

def test_a_small_result_set_is_still_steered():
    """DELIBERATE REVERSAL of the ported behaviour, on the owner's instruction: "directions should show
    always — it helps refine query with explicit user feedback loop".

    The old rule stayed silent below twenty-five results, on the theory that a reader who had narrowed
    that far had converged. That theory is backwards. Someone looking at six results they did not want has
    converged on nothing, and removing the steering at that exact moment takes away the one control that
    could rescue the query. Steering is most valuable when the results are wrong, and results are often
    wrong when they are few.

    A high match score does not silence it either, and never did: "backend engineer" with 691 results got
    nothing under an even earlier rule, though seniority, place and work mode all split it usefully."""
    ok, why = worth_steering({"pool": 18, "best_match": 88})
    assert ok is True and why


def test_only_an_undividable_set_is_left_alone():
    """The single remaining silence: fewer than two rows cannot be divided into two groups. Everything
    above that offers, and the quality bar lives in the candidates rather than in this gate."""
    assert worth_steering({"pool": 5, "best_match": 20})[0] is True
    assert worth_steering({"pool": 2})[0] is True
    ok, why = worth_steering({"pool": 1})
    assert ok is False and "nothing to split" in why


def test_an_ambiguous_query_is_steered_even_when_the_matches_look_good():
    """`PM` silently chose product over project. A high match score on the wrong reading is exactly the
    case a clarifying question exists for."""
    ok, _ = worth_steering({"pool": 400, "best_match": 95}, ambiguous=True)
    assert ok is True


def test_a_direction_that_barely_moves_the_set_is_never_offered():
    """The quality bar, now that the gate is about the set rather than the query: a 96/4 split is not a
    choice, and offering it is the low-quality question the research warns about in different clothes."""
    counts = {"mode": {"remote": 96, "onsite": 4}}
    assert rank_directions(facet_directions(counts, SCHEMA, "thing")) == []
    counts = {"mode": {"remote": 60, "onsite": 40}}
    assert rank_directions(facet_directions(counts, SCHEMA, "thing"))


class TestCoverageGuard:
    """A key most of the pool has no value for cannot steer it."""

    def _schema(self):
        from eigen_kernel.facets import FacetKey, FacetSchema, FacetType
        return FacetSchema(keys=(
            FacetKey(key="area", type=FacetType.categorical, kinds=("c",), values=("a", "b"), label="Area"),
            FacetKey(key="thin", type=FacetType.categorical, kinds=("c",), values=("x", "y"), label="Thin"),
        ))

    def test_a_sparsely_known_key_is_not_offered(self):
        """Measured: a 232-company pool was offered a split that kept one company, because the share was
        computed over the two rows that had the key at all."""
        from eigen_kernel.facets import facet_directions
        counts = {"thin": {"x": 1, "y": 1}, "area": {"a": 120, "b": 100}}
        got = facet_directions(counts, self._schema(), "c", pool=232)
        assert {d.key for d in got} == {"area"}, "the thin key filters by absence, not by intent"

    def test_without_a_pool_the_guard_abstains(self):
        from eigen_kernel.facets import facet_directions
        counts = {"thin": {"x": 1, "y": 1}}
        assert facet_directions(counts, self._schema(), "c") , "no pool given means the guard cannot judge"
