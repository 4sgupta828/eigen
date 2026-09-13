from __future__ import annotations

import pytest

from api.thesis.eval import judge as J
from api.thesis.eval.harness import load_gold, run_eval, format_report


def test_gold_set_is_well_formed():
    items = load_gold()
    assert len(items) >= 3
    for it in items:
        for k in ("id", "thesis", "aspect_key", "settleable", "question", "target", "rubric_focus"):
            assert it.get(k), f"{it.get('id')} missing {k}"


@pytest.mark.asyncio
async def test_judge_parses_and_clamps():
    async def llm(system, user):
        return {"coverage": 5, "specificity": 4, "groundedness": 9, "usefulness": 0,
                "overall": 4, "rationale": "solid", "missing": "a filed figure"}
    s = await J.judge_answer(llm, question="q", thesis="t", aspect="a", rubric_focus="rf",
                             answer="ans [[e:e1]]", evidence=[{"id": "e1", "quote": "x"}])
    assert s["coverage"] == 5 and s["specificity"] == 4
    assert s["groundedness"] == 5            # clamped to 5
    assert s["usefulness"] == 1              # 0 → clamped up to the 1..5 floor
    assert s["overall"] == 4 and s["missing"] == "a filed figure"


@pytest.mark.asyncio
async def test_judge_is_safe_without_a_model():
    s = await J.judge_answer(None, question="q", thesis="t", aspect="a", rubric_focus="", answer="", evidence=[])
    assert s["overall"] == 0 and s["coverage"] == 0


def test_aggregate_means_ignore_unscored():
    res = [{"scores": {"coverage": 4, "specificity": 4, "groundedness": 4, "usefulness": 4, "overall": 4}},
           {"scores": {"coverage": 2, "specificity": 2, "groundedness": 2, "usefulness": 2, "overall": 2}},
           {"scores": {}}]   # unscored (judge failed) — excluded from means
    a = J.aggregate(res)
    assert a["n"] == 3 and a["n_scored"] == 2 and a["overall"] == 3.0 and a["coverage"] == 3.0


@pytest.mark.asyncio
async def test_run_eval_end_to_end_with_fakes():
    items = [{"id": "x", "thesis": "T", "question": "Q", "target": "target", "rubric_focus": "rf"},
             {"id": "boom", "thesis": "T", "question": "Q2", "target": "t2", "rubric_focus": "rf"}]
    async def produce(item):
        if item["id"] == "boom":
            raise RuntimeError("retrieval down")
        return "A grounded answer. [[e:e1]]", [{"id": "e1", "quote": "q"}]
    async def judge(system, user):
        return {"coverage": 4, "specificity": 3, "groundedness": 5, "usefulness": 4, "overall": 4,
                "rationale": "ok", "missing": ""}
    rep = await run_eval(items, produce=produce, judge_llm=judge)
    assert rep["summary"]["n"] == 2 and rep["summary"]["n_scored"] == 1   # 'boom' failed → unscored
    assert rep["results"][0]["scores"]["overall"] == 4 and rep["results"][0]["evidence_n"] == 1
    assert rep["results"][1]["error"] == "retrieval down"
    assert "OVERALL=4.00" in format_report(rep)                            # report renders the baseline
