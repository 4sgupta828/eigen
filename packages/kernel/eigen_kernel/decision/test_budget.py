"""The budget allocator + question selection are domain-free mechanics — tested on toy aspects with no
domain vocabulary. They are the fix for 'right number, no rabbit-holing, no duplication' (panel 2026-09-16)."""
from __future__ import annotations

from eigen_kernel.decision import (
    Aspect, Question, QuestionKind,
    allocate_budget, frame_dim_counts, score_questions, select_for_aspect,
)


def _aspects():
    return (Aspect(key="a", prompt="A?", critical=True),
            Aspect(key="b", prompt="B?", critical=True),
            Aspect(key="c", prompt="C?", critical=False),
            Aspect(key="d", prompt="D?", critical=False))


def test_every_aspect_gets_at_least_the_floor_and_at_most_the_cap():
    alloc = allocate_budget(_aspects(), None, total=12, floor=1, cap=4)
    assert set(alloc) == {"a", "b", "c", "d"}
    assert all(1 <= n <= 4 for n in alloc.values())
    assert sum(alloc.values()) <= 12


def test_floor_holds_even_when_total_is_below_the_number_of_aspects():
    # a shallow pass cannot starve a dimension below coverage
    alloc = allocate_budget(_aspects(), None, total=2, floor=1, cap=4)
    assert all(n == 1 for n in alloc.values())


def test_frame_emphasis_pulls_budget_toward_the_flagged_dimension():
    # the frame flags dimension 'c' (non-critical) with two risks → it should out-earn 'd' (non-critical,
    # unflagged), and can even rival the critical ones. Depth follows the decision's risk density.
    frame = {"assumptions": [{"text": "x", "dimension": "c"}],
             "risks": [{"text": "y", "dimension": "c"}], "unknowns": [], "anchors": []}
    assert frame_dim_counts(frame) == {"c": 2}
    alloc = allocate_budget(_aspects(), frame, total=14, floor=1, cap=4)
    assert alloc["c"] > alloc["d"]                    # the flagged dimension gets more than the ignored one


def test_capped_share_reallocates_rather_than_being_lost():
    # one heavily-weighted aspect hits the cap; the leftover flows to the others, not into the void
    frame = {"assumptions": [{"text": "x", "dimension": "a"}] * 6, "risks": [], "unknowns": [], "anchors": []}
    alloc = allocate_budget(_aspects(), frame, total=16, floor=1, cap=3)
    assert alloc["a"] == 3                            # capped
    assert sum(alloc.values()) >= 8                   # the rest absorbed the reallocated share


def _q(kind, target, text=""):
    return Question(kind=kind, text=text or target, target=target, polarity=1)


def test_selection_keeps_required_lenses_first_and_respects_budget():
    qs = [_q(QuestionKind.RESOLVE_AMBIGUITY, "ambiguity about scope"),
          _q(QuestionKind.SEEK_SUPPORT, "the thing works for buyers"),
          _q(QuestionKind.SEEK_CONTRADICTION, "the thing fails at scale")]
    scores = [0.9, 0.2, 0.2]                          # ambiguity is most 'relevant', but is not a required lens
    kept = select_for_aspect(qs, scores, budget=2, floor=1)
    kinds = {k.kind for k in kept}
    assert len(kept) == 2
    assert QuestionKind.SEEK_SUPPORT in kinds and QuestionKind.SEEK_CONTRADICTION in kinds  # required lenses win the slots


def test_dedup_drops_a_near_duplicate_but_never_empties_a_dimension():
    qs = [_q(QuestionKind.SEEK_SUPPORT, "enterprise buyers will switch to the new platform"),
          _q(QuestionKind.SEEK_SUPPORT, "enterprise buyers will switch to the new platform quickly")]
    kept = select_for_aspect(qs, [0.5, 0.5], budget=4, floor=1)
    assert len(kept) == 1                             # the paraphrase is deduped

    # but a single question is NEVER dropped for looking like itself — floor 1 wins
    one = [_q(QuestionKind.SEEK_SUPPORT, "only probe for this dimension")]
    assert len(select_for_aspect(one, [0.5], budget=4, floor=1)) == 1


def test_score_questions_is_neutral_without_a_frame():
    qs = [_q(QuestionKind.SEEK_SUPPORT, "anything"), _q(QuestionKind.SEEK_CONTRADICTION, "else")]
    scores, vecs = score_questions(qs, None)
    assert scores == [0.5, 0.5] and vecs is None      # nothing to bind to → neutral, never dropped as 'irrelevant'
