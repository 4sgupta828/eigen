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
