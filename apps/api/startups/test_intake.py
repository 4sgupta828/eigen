"""The startup guided intake, offline: a fake compiler, fake counts, no model. Order of questions, how answers
land (stage → centre, funding band → range, area → must), search-now, and the ready card."""
from __future__ import annotations

import asyncio

from eigen_kernel.facets import Contract

from api.startups.intake import StartupIntake, understood_words
from api.startups.schema import KIND

COUNTS = {"_total": 900, "tech_area": {"ai_infra": 300, "fintech": 300, "robotics": 300}, "stage": {"seed": 5, "series_a": 3, "unknown": 892},
          "total_disclosed_funding": {"1m_5m": 200, "5m_20m": 250, "20m_50m": 150, "unknown": 300}, "country": {"us": 850, "uk": 50},
          "founder_count": {"1": 300, "2": 400, "3": 200}, "program": {"yc": 900}, "customer": {"enterprise": 100, "unknown": 800},
          "business_model": {"unknown": 900}, "hiring": {"1_5": 100, "unknown": 800}, "last_round_months": {"6_12": 200, "12_24": 300, "unknown": 400}, "metro": {"bay_area": 500, "new_york": 200}}


async def fake_compile(text):
    return Contract(kind=KIND, text=text), []


async def fake_counts(must, exclude):
    return COUNTS


def _svc(llm=None):
    return StartupIntake(llm_json=llm, counts_fn=fake_counts, compile_fn=fake_compile)


def run(coro):
    return asyncio.run(coro)


def test_opening_then_required_questions_then_ready():
    svc = _svc()
    r = run(svc.step(state=None, message=""))
    assert r["stage"] == "opening"
    r = run(svc.step(state=r["state"], message="AI infra startups selling to banks"))
    assert r["stage"] == "questions" and r["question"]["name"] == "tech_area" and r["question"]["multi"]
    assert [o[0] for o in r["question"]["options"]][:3] == ["ai_infra", "fintech", "robotics"]
    r = run(svc.step(state=r["state"], answer={"name": "tech_area", "value": ["ai_infra", "fintech"]}))
    assert r["question"]["name"] == "stage" and [o[0] for o in r["question"]["options"]][:2] == ["pre_seed", "seed"]   # vocabulary order, counts shown
    r = run(svc.step(state=r["state"], answer={"name": "stage", "value": "seed"}))
    c = r["state"]["kernel"]["contract"]
    assert c["must"] == {"tech_area": ["ai_infra", "fintech"]} and c["center"] == {"key": "stage", "value": "seed", "span": 1} and c["prefer"] == {"stage": ["seed"]}
    # optional: funding is spread → asked; program (single value) and business model (all unknown) never
    assert r["question"]["name"] == "total_disclosed_funding"
    r = run(svc.step(state=r["state"], answer={"name": "total_disclosed_funding", "value": "5m_20m"}))
    assert r["state"]["kernel"]["contract"]["must"]["total_disclosed_funding"] == {"min": 5000000.0}
    # second optional (founder count is spread), then ready — budget of 2 optional
    assert r["question"]["name"] in ("founder_count", "country", "last_round_months")
    r = run(svc.step(state=r["state"], answer={"name": r["question"]["name"], "value": "__skip__"}))
    assert r["stage"] == "ready"
    ready = r["ready"]
    assert ready["pool"] == 900 and "AI infra, fintech" in ready["understood"] and "centred on seed" in ready["understood"]
    assert ready["contract"]["kind"] == "company" and len(ready["transcript_audit"]) >= 6


def test_search_now_ends_immediately():
    svc = _svc()
    r = run(svc.step(state=None, message="robotics", search_now_flag=True))
    assert r["stage"] == "ready" and r["ready"]["contract"]["text"] == "robotics"


def test_typed_answer_uses_the_model_and_lands_extra_keys():
    async def llm(system, user):
        assert "tech_area" in system
        return {"answers": {"tech_area": ["robotics"], "country": "us"}, "free_text": "", "search_now": False}
    svc = _svc(llm)
    r = run(svc.step(state=None, message="hardware companies"))
    r = run(svc.step(state=r["state"], message="robotics, in the US please"))
    c = r["state"]["kernel"]["contract"]
    assert c["must"]["tech_area"] == ["robotics"] and c["must"]["country"] == ["us"]


def test_understood_words_reads_ranges_and_exclusions():
    s = understood_words({"text": "ai infra", "must": {"tech_area": ["ai_infra"], "total_disclosed_funding": {"min": 5e6}}, "scope": {"exclude": {"program": ["yc"]}}, "center": {"key": "stage", "value": "seed"}})
    assert "AI infra" in s and "≥ $5M" in s and "excluding Y Combinator" in s and "centred on seed" in s


def test_stage_in_the_opening_becomes_the_centre_and_refinements_merge():
    from eigen_kernel.facets import Contract
    async def compile_(text):
        if "seed" in text:
            return Contract(kind=KIND, text=text, prefer={"stage": ["seed"]}, must={"tech_area": ["ai_infra"]}), []
        return Contract(kind=KIND, text=text, must={"country": ["us"]}), []
    svc = StartupIntake(llm_json=None, counts_fn=fake_counts, compile_fn=compile_)
    r = run(svc.step(state=None, message="seed ai infra"))
    c = r["state"]["kernel"]["contract"]
    assert c["center"] == {"key": "stage", "value": "seed", "span": 1}
    r = run(svc.step(state=r["state"], search_now_flag=True))
    r = run(svc.step(state=r["state"], message="in the US"))
    c = r["state"]["kernel"]["contract"] if r["stage"] != "ready" else r["ready"]["contract"]
    assert c["must"] == {"tech_area": ["ai_infra"], "country": ["us"]} and c["center"]["value"] == "seed"
