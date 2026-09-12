from __future__ import annotations

import pytest

from api.thesis import genesis


def _llm(out):
    async def call(_system, _user):
        return out
    return call


@pytest.mark.asyncio
async def test_concrete_thesis_is_ready_with_no_questions():
    out = {"reply": "Noted.",
           "proposed_thesis": "Mid-market logistics firms will pay for automated route re-planning, "
                              "replacing manual dispatch.",
           "subject_present": {"product": True, "buyer": True, "substitute": True},
           "questions": ["ignored because nothing is missing"]}
    r = await genesis.turn(_llm(out), said="logistics route planning saas", history=[], budget_left=3)
    assert r["ready"] is True
    assert r["questions"] == []                 # nothing missing ⇒ no questions, even if the model wrote some
    assert "route re-planning" in r["proposed_thesis"]


@pytest.mark.asyncio
async def test_vague_thesis_asks_for_missing_elements_only_capped_at_two():
    out = {"reply": "Who is this for?",
           "proposed_thesis": "Someone will pay for scheduling software.",
           "subject_present": {"product": True, "buyer": False, "substitute": False},
           "questions": ["Which segment feels this pain?", "What do they use today?",
                         "A third question that should be dropped"]}
    r = await genesis.turn(_llm(out), said="scheduling tool", history=[], budget_left=3)
    assert r["ready"] is False
    assert len(r["questions"]) == 2             # capped at two
    assert set(r["missing"]) == {"buyer", "substitute"}


@pytest.mark.asyncio
async def test_no_model_falls_open_with_the_users_own_words():
    r = await genesis.turn(None, said="raw idea in the user's words", history=[], budget_left=3)
    assert r["ready"] is True
    assert r["proposed_thesis"] == "raw idea in the user's words"
    assert r["questions"] == []


@pytest.mark.asyncio
async def test_spent_budget_never_traps_the_user():
    out = {"proposed_thesis": "still vague",
           "subject_present": {"product": False, "buyer": False, "substitute": False},
           "questions": ["one", "two"]}
    r = await genesis.turn(_llm(out), said="hmm", history=[], budget_left=0)
    assert r["ready"] is True                    # budget spent ⇒ proceed, do not keep asking
    assert r["questions"] == []


@pytest.mark.asyncio
async def test_bad_json_falls_open():
    async def boom(_s, _u):
        raise ValueError("model returned junk")
    r = await genesis.turn(boom, said="an idea", history=[], budget_left=2)
    assert r["ready"] is True
    assert r["proposed_thesis"] == "an idea"


@pytest.mark.asyncio
async def test_follow_up_reasons_over_all_selected_claims_evidence():
    from api.thesis import converse
    captured = {}

    async def spy(_system, user):
        captured["user"] = user
        return {"reply": "Both claims lean the same way."}

    claims = [
        {"rung": "problem_exists", "verdict": "supported", "claim": "The problem occurs.",
         "evidence": [{"side": "for", "register": "filed", "quote": "postmortem describes the pain"}]},
        {"rung": "buyer_nameable", "verdict": "under_tested", "claim": "A buyer owns budget.",
         "evidence": [{"side": "against", "register": "stated", "quote": "no named buyer in filings"}]},
    ]
    out = await converse.follow_up(spy, thesis="A thesis.", claims=claims,
                                   said="do these two agree?", history=[])
    assert out["reply"]
    # the prompt must carry BOTH claims and BOTH quotes — the agent reasons over the union
    assert "problem_exists" in captured["user"] and "buyer_nameable" in captured["user"]
    assert "postmortem describes the pain" in captured["user"]
    assert "no named buyer in filings" in captured["user"]


@pytest.mark.asyncio
async def test_follow_up_no_model_points_at_evidence_without_fabricating():
    from api.thesis import converse
    out = await converse.follow_up(None, thesis="A thesis.",
                                   claims=[{"rung": "problem_exists", "evidence": []}],
                                   said="what does this say?", history=[])
    assert "evidence" in out["reply"].lower()   # deterministic, points at the shown evidence
