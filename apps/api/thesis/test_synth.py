import pytest
from api.thesis import synth


class _Profile:
    def aspects(self):
        return []
    def pitch_deck_spec(self):
        return ("dir", {"one_liner": "x"}, [{"key": "problem", "title": "Problem"}])


GOOD_DECK = {"empty": False, "spine": {"one_liner": {"text": "A great pitch."}},
             "sections": [{"key": "problem", "title": "Problem", "headline": {"text": "Real pain."}, "points": [{"text": "p"}]}]}


def test_deck_substantive():
    assert synth._deck_substantive(GOOD_DECK) is True
    assert synth._deck_substantive({"empty": True}) is False
    assert synth._deck_substantive({"spine": {}, "sections": [{"key": "a", "headline": {"text": ""}, "points": []}]}) is False


@pytest.mark.asyncio
async def test_blank_rebuild_keeps_good_deck(monkeypatch):
    calls = {"set": 0}
    async def fake_get(pool, thesis_id, trusted=True):
        return {"pitch_deck": GOOD_DECK, "collective_take": {}, "thesis": "T", "subject": {}}
    async def fake_list_questions(pool, tid):
        return [{"id": "q1", "target_status": "target_supported", "answer": "Real. [[e:e1]]",
                 "text": "?", "inquiry_name": "L", "aspect_key": "problem"}]
    async def fake_set(pool, tid, deck):
        calls["set"] += 1
    monkeypatch.setattr(synth.tstore, "get", fake_get)
    monkeypatch.setattr(synth.tstore, "list_questions", fake_list_questions)
    monkeypatch.setattr(synth.tstore, "set_pitch_deck", fake_set)
    # llm_json that yields a BLANK deck (simulates a hiccup / all units gated out)
    async def blank_llm(_s, _u):
        return {"spine": {}, "sections": [{"key": "problem", "points": []}]}
    out = await synth.synthesize_deck(None, "t1", _Profile(), blank_llm)
    assert calls["set"] == 0                          # did NOT overwrite
    assert out["deck"] is GOOD_DECK                    # kept the good deck


@pytest.mark.asyncio
async def test_zero_findings_keeps_good_deck(monkeypatch):
    calls = {"set": 0}
    async def fake_get(pool, thesis_id, trusted=True):
        return {"pitch_deck": GOOD_DECK, "collective_take": {}, "thesis": "T", "subject": {}}
    async def fake_list_questions(pool, tid):
        return []                                      # no findings
    async def fake_set(pool, tid, deck):
        calls["set"] += 1
    monkeypatch.setattr(synth.tstore, "get", fake_get)
    monkeypatch.setattr(synth.tstore, "list_questions", fake_list_questions)
    monkeypatch.setattr(synth.tstore, "set_pitch_deck", fake_set)
    out = await synth.synthesize_deck(None, "t1", _Profile(), lambda *a, **k: None)
    assert calls["set"] == 0 and out["deck"] is GOOD_DECK


@pytest.mark.asyncio
async def test_take_falls_back_to_strong_seam_when_reasoning_blank(monkeypatch):
    """If the reasoning seam returns a blank take, synthesize_all retries on the strong seam so the take
    actually rebuilds (the "regenerate did nothing" bug)."""
    calls = {"take_set": None}
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE as prof
    async def fake_get(pool, thesis_id, trusted=True):
        return {"thesis": "T", "subject": {}, "collective_take": {}}
    async def fake_list_questions(pool, tid):
        return [{"id": "q1", "target_status": "target_supported", "answer": "Real fact. [[e:e1]]",
                 "text": "?", "inquiry_name": "L", "aspect_key": "problem_exists"}]
    async def fake_set_take(pool, tid, take):
        calls["take_set"] = take
    monkeypatch.setattr(synth.tstore, "get", fake_get)
    monkeypatch.setattr(synth.tstore, "list_questions", fake_list_questions)
    monkeypatch.setattr(synth.tstore, "set_collective_take", fake_set_take)

    async def reasoning(_s, _u):    # the deep seam fails / returns nothing
        raise RuntimeError("reasoning model timed out")
    async def strong(_s, _u):       # the strong seam succeeds
        return {"bottom_line": {"text": "The record leans fund.", "finding_ids": ["F1"]},
                "sections": [{"key": "problem_exists", "grounded": [{"text": "Real fact.", "finding_ids": ["F1"]}], "analysis": []}]}
    out = await synth.synthesize_all(None, "t1", prof, strong, take_llm_json=reasoning)
    assert out["rebuilt"] is True
    assert calls["take_set"] is not None and calls["take_set"]["bottom_line"]["text"].startswith("The record leans")


def test_bound_findings_ranks_by_priority_and_caps():
    # 40 findings, each ~1000-char answer → far over budget; keeps the crux (P0) first, within the cap.
    fs = ([{"id": f"c{i}", "priority": 0, "line": "crux", "question": "q", "answer": "x" * 1000} for i in range(10)]
          + [{"id": f"a{i}", "priority": 2, "line": "cov", "question": "q", "answer": "y" * 1000} for i in range(30)])
    kept, truncated = synth._bound_findings(fs, max_chars=8000, per_answer=1000)
    assert truncated is True
    assert all(f["priority"] == 0 for f in kept)        # P0 crux kept first
    assert 1 <= len(kept) <= 10
    # a small set is never truncated
    kept2, trunc2 = synth._bound_findings(fs[:3], max_chars=8000, per_answer=1000)
    assert trunc2 is False and len(kept2) == 3
