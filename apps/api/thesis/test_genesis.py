from __future__ import annotations

import pytest

from api.thesis import genesis


def _two(converse_out, validator_out):
    """A fake that answers as the PARTNER for the converse prompt and the VALIDATOR for the grader
    prompt — so turn() exercises the real two-model split with validator_llm=None (same seam, dispatched
    by system prompt)."""
    async def call(system, _user):
        return validator_out if "You grade a draft" in system else converse_out
    return call


@pytest.mark.asyncio
async def test_ready_only_when_the_validator_says_ready():
    converse = {"reply": "Noted.",
                "proposed_thesis": "Mid-market 3PLs will pay for automated route re-planning, "
                                   "displacing spreadsheet dispatch, because labour cost exceeds software."}
    validator = {"status": "ready", "gaps": ["should be ignored when ready"],
                 "assumptions": ["driver labour cost keeps rising"]}
    r = await genesis.turn(_two(converse, validator), said="logistics route planning saas",
                           history=[], budget_left=3)
    assert r["ready"] is True and r["status"] == "ready"
    assert r["questions"] == []                  # ready ⇒ no questions even if the grader wrote some
    assert r["assumptions"] == ["driver labour cost keeps rising"]   # surfaced for the user to test
    assert "route re-planning" in r["proposed_thesis"]


@pytest.mark.asyncio
async def test_partner_cannot_self_declare_ready_validator_blocks_a_topic():
    # The partner returns a confident sentence; the validator judges it a bare topic → NOT ready.
    converse = {"reply": "Here's a framing.", "proposed_thesis": "AI in logistics is a big opportunity."}
    validator = {"status": "blocked", "gaps": ["Name the buyer and the claim you'd test."],
                 "assumptions": []}
    r = await genesis.turn(_two(converse, validator), said="ai logistics", history=[], budget_left=3)
    assert r["ready"] is False and r["status"] == "blocked"   # anti-rubber-stamp: the grader gates
    assert r["questions"] == ["Name the buyer and the claim you'd test."]


@pytest.mark.asyncio
async def test_needs_sharpening_surfaces_the_validators_gaps_capped_at_two():
    converse = {"reply": "Who is this for?", "proposed_thesis": "Someone will pay for scheduling software."}
    validator = {"status": "needs_sharpening",
                 "gaps": ["Which segment specifically?", "What do they use today?", "third dropped"],
                 "assumptions": ["scheduling is a recurring pain"]}
    r = await genesis.turn(_two(converse, validator), said="scheduling tool", history=[], budget_left=3)
    assert r["ready"] is False
    assert r["questions"] == ["Which segment specifically?", "What do they use today?"]   # capped at two
    assert r["missing"] == r["questions"]


@pytest.mark.asyncio
async def test_no_model_falls_open_with_the_users_own_words():
    r = await genesis.turn(None, said="raw idea in the user's words", history=[], budget_left=3)
    assert r["ready"] is True
    assert r["proposed_thesis"] == "raw idea in the user's words"
    assert r["questions"] == []


@pytest.mark.asyncio
async def test_spent_budget_never_traps_the_user():
    converse = {"proposed_thesis": "still vague"}
    validator = {"status": "blocked", "gaps": ["one", "two"], "assumptions": []}
    r = await genesis.turn(_two(converse, validator), said="hmm", history=[], budget_left=0)
    assert r["ready"] is True                    # budget spent ⇒ proceed, do not keep asking
    assert r["questions"] == []


@pytest.mark.asyncio
async def test_bad_json_from_the_partner_falls_open():
    async def boom(_s, _u):
        raise ValueError("model returned junk")
    r = await genesis.turn(boom, said="an idea", history=[], budget_left=2)
    assert r["ready"] is True
    assert r["proposed_thesis"] == "an idea"


@pytest.mark.asyncio
async def test_validate_clamps_status_and_caps_lists():
    async def grader(_s, _u):
        return {"status": "maybe", "gaps": ["a", "b", "c"],
                "assumptions": ["1", "2", "3", "4", "5"]}
    v = await genesis.validate(grader, thesis="a draft thesis", history=[])
    assert v["status"] == "needs_sharpening"     # unknown status → the safe middle band, never 'ready'
    assert v["gaps"] == ["a", "b"]               # gaps capped at two
    assert len(v["assumptions"]) == 4            # assumptions capped at four


@pytest.mark.asyncio
async def test_validate_no_grader_falls_open():
    v = await genesis.validate(None, thesis="anything", history=[])
    assert v["status"] == "ready" and v["gaps"] == []   # code still gates on budget elsewhere


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
