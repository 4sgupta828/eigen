from __future__ import annotations

import pytest

from api.thesis import genesis


def _llm(out):
    async def call(_system, _user):
        return out
    return call


@pytest.mark.asyncio
async def test_turn_restates_the_thesis_and_proposes_a_refinement_every_turn():
    out = {"thesis": "Mid-market SaaS security teams will pay for goal-scoped agent authorization, "
                     "displacing RBAC/ABAC, because agents change resource scope mid-task.",
           "reply": "Is the buyer the security team or platform-eng? If platform-eng, the wedge is CI/CD agents.",
           "ready": False}
    out2 = dict(out, assumptions=["agents will proliferate in prod"], open_threads=["which buyer segment"],
                resolved=[], thought="buyer still vague")
    r = await genesis.turn(_llm(out2), said="agent authorization vs RBAC", history=[], budget_left=6,
                           memory={"assumptions": ["prior"], "open_threads": [], "resolved": []})
    assert r["proposed_thesis"].startswith("Mid-market SaaS security teams")
    assert "platform-eng" in r["reply"]
    assert r["ready"] is False
    assert r["memory"]["open_threads"] == ["which buyer segment"]              # memory carried out
    assert r["thought"] == "buyer still vague"


@pytest.mark.asyncio
async def test_explicit_proceed_signal_flips_ready_even_if_the_model_hesitates():
    out = {"thesis": "A specific falsifiable thesis.", "reply": "one more angle?", "ready": False}
    r = await genesis.turn(_llm(out), said="looks good, proceed", history=[{"role": "user", "text": "x"}],
                           budget_left=6)
    assert r["ready"] is True                     # code honours "proceed" even when the model says false
    assert r["proposed_thesis"] == "A specific falsifiable thesis."


@pytest.mark.asyncio
async def test_memory_falls_back_to_prior_when_the_model_drops_a_field():
    # model returns no assumptions this turn -> keep the prior ones (don't lose memory)
    out = {"thesis": "T", "reply": "r", "ready": False, "open_threads": ["x"]}
    r = await genesis.turn(_llm(out), said="hmm", history=[{"role": "user", "text": "a"}], budget_left=6,
                           memory={"assumptions": ["keep me"], "open_threads": [], "resolved": ["done"]})
    assert r["memory"]["assumptions"] == ["keep me"]      # carried forward
    assert r["memory"]["open_threads"] == ["x"]           # updated
    assert r["memory"]["resolved"] == ["done"]            # carried forward


@pytest.mark.asyncio
async def test_no_model_or_spent_budget_or_bad_json_never_traps_the_author():
    assert (await genesis.turn(None, said="idea", history=[], budget_left=6))["ready"] is True
    assert (await genesis.turn(_llm({"x": 1}), said="idea", history=[], budget_left=0))["ready"] is True
    async def boom(_s, _u):
        raise ValueError("junk")
    assert (await genesis.turn(boom, said="idea", history=[], budget_left=3))["ready"] is True


@pytest.mark.asyncio
async def test_sample_thesis_generates_a_sentence_and_is_safe_without_a_model():
    out = await genesis.sample_thesis(_llm({"thesis": "Mid-market clinics will pay for X, displacing Y."}))
    assert out.startswith("Mid-market clinics will pay")
    assert await genesis.sample_thesis(None) == ""


@pytest.mark.asyncio
async def test_sample_thesis_swallows_a_bad_model():
    async def boom(_s, _u):
        raise ValueError("down")
    assert await genesis.sample_thesis(boom) == ""


@pytest.mark.asyncio
async def test_sample_thesis_keeps_a_detailed_thesis_up_to_the_raised_cap():
    # The sample is now a DETAILED (~250-300 word) thesis; the proposed-thesis path bound was raised
    # from 600 to THESIS_CAP (2000, matching commit) so it is no longer clipped to a one-liner.
    detailed = "Word " * 700               # ~3500 chars of whole sentences, far over the old 600 cap
    detailed = ". ".join(detailed.split()) + "."
    out = await genesis.sample_thesis(_llm({"thesis": detailed}))
    assert 600 < len(out) <= genesis.THESIS_CAP
    assert out.endswith(".") and " " not in out[-3:]   # clipped on a sentence boundary, never mid-word


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


@pytest.mark.asyncio
async def test_sample_thesis_generates_a_sentence_and_is_safe_without_a_model():
    out = await genesis.sample_thesis(_llm({"thesis": "Mid-market clinics will pay for X, displacing Y."}))
    assert out.startswith("Mid-market clinics will pay")
    assert await genesis.sample_thesis(None) == ""       # no model → nothing (never fabricate blindly)


@pytest.mark.asyncio
async def test_sample_thesis_swallows_a_bad_model():
    async def boom(_s, _u):
        raise ValueError("down")
    assert await genesis.sample_thesis(boom) == ""
