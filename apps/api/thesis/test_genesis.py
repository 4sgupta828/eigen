from __future__ import annotations

import pytest

from api.thesis import genesis


def _llm(out):
    async def call(_system, _user):
        return out
    return call


@pytest.mark.asyncio
async def test_turn_converses_and_the_model_owns_ready():
    # A real conversational turn: the model replies and decides readiness itself (factra's pattern).
    r = await genesis.turn(_llm({"reply": "Who signs the cheque — which segment?", "ready": False}),
                           said="a routing tool for logistics", history=[], budget_left=6)
    assert r["ready"] is False
    assert "which segment" in r["reply"].lower()


@pytest.mark.asyncio
async def test_turn_ready_when_the_model_says_ready():
    r = await genesis.turn(_llm({"reply": "Ready — I'll draft the questions.", "ready": True}),
                           said="mid-market 3PLs, displacing spreadsheets", history=[], budget_left=6)
    assert r["ready"] is True and "ready" in r["reply"].lower()


@pytest.mark.asyncio
async def test_no_model_or_spent_budget_never_traps_the_author():
    assert (await genesis.turn(None, said="an idea", history=[], budget_left=6))["ready"] is True
    r = await genesis.turn(_llm({"reply": "more?", "ready": False}), said="x", history=[], budget_left=0)
    assert r["ready"] is True                     # budget spent ⇒ proceed, do not keep asking


@pytest.mark.asyncio
async def test_bad_json_falls_open_ready():
    async def boom(_s, _u):
        raise ValueError("model returned junk")
    r = await genesis.turn(boom, said="an idea", history=[], budget_left=3)
    assert r["ready"] is True


@pytest.mark.asyncio
async def test_synthesize_lands_one_clean_sentence_from_the_whole_conversation():
    history = [{"role": "user", "text": "route planning saas"},
               {"role": "agent", "text": "For whom?"},
               {"role": "user", "text": "mid-market 3PLs, they use spreadsheets today"}]
    synth = _llm("Mid-market 3PLs will pay for automated route re-planning, displacing spreadsheet "
                 "dispatch, because planner labour cost exceeds the software above ~40 trucks.")
    out = await genesis.synthesize(synth, history=history, said="")
    assert out.startswith("Mid-market 3PLs will pay")
    assert "spreadsheet" in out


@pytest.mark.asyncio
async def test_synthesize_tolerates_a_json_wrapper_and_falls_back_without_a_model():
    out = await genesis.synthesize(_llm({"thesis": "A clean sentence."}), history=[], said="raw idea")
    assert out == "A clean sentence."                       # unwrapped from JSON if the model wraps it
    # No model → the author's own words stand (never fabricate a thesis).
    fb = await genesis.synthesize(None, history=[{"role": "user", "text": "my raw thesis words"}], said="")
    assert fb == "my raw thesis words"


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
