"""The startup guided intake, offline: a fake compiler, fake counts, a scripted model. What is asserted here is
the ANALYST contract — it asks only what the index can answer, it may never invent a filter, an open question
sharpens the words the search matches on, memory rides every turn, and with no model at all the deterministic
gate still lands a usable search."""
from __future__ import annotations

import asyncio

from eigen_kernel.facets import Contract

from api.startups.intake import ANALYST_BUDGET, MAX_QUESTIONS, StartupIntake, understood_words
from api.startups.schema import KIND

# stage is known for 8 of 900 here — as in production, where it is known for none.
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


def _walk(svc, opening, replies):
    """Drive a whole intake: the opening, then one chip/skip per turn. Returns every turn."""
    turns = [run(svc.step(state=None, message=opening))]
    for r in replies:
        last = turns[-1]
        if last["stage"] == "ready":
            break
        turns.append(run(svc.step(state=last["state"], answer={"name": last["question"]["name"], "value": r})))
    return turns


# ---------------------------------------------------------------- the deterministic floor (no model)
def test_without_a_model_the_gate_still_lands_a_search():
    svc = _svc()
    r = run(svc.step(state=None, message=""))
    assert r["stage"] == "opening"
    r = run(svc.step(state=r["state"], message="AI infra startups selling to banks"))
    assert r["stage"] == "questions" and r["question"]["name"] == "tech_area" and r["question"]["multi"]
    assert {o[0] for o in r["question"]["options"][:3]} == {"ai_infra", "fintech", "robotics"}
    assert 3 <= len(r["question"]["options"]) <= 20     # a question is a choice, not a catalogue
    r = run(svc.step(state=r["state"], answer={"name": "tech_area", "value": ["ai_infra", "fintech"]}))
    assert r["state"]["kernel"]["contract"]["must"] == {"tech_area": ["ai_infra", "fintech"]}
    while r["stage"] != "ready":
        r = run(svc.step(state=r["state"], answer={"name": r["question"]["name"], "value": "__skip__"}))
    assert r["ready"]["pool"] == 900 and r["ready"]["contract"]["kind"] == "company"


def test_stage_is_never_asked_when_the_index_cannot_answer_it():
    """The question that could not change a single result. It is retired by MEASUREMENT — stage is known for
    8 of 900 here — not by a hardcoded ban, so it returns by itself if coverage ever lands."""
    svc = _svc()
    turns = _walk(svc, "deep tech platforms for ML and data", ["__skip__"] * 8)
    asked = [t["question"]["name"] for t in turns if t.get("question")]
    assert "stage" not in asked
    assert "founder_count" not in asked[:1]     # never the FIRST thing an analyst asks


def test_search_now_ends_immediately():
    svc = _svc()
    r = run(svc.step(state=None, message="robotics", search_now_flag=True))
    assert r["stage"] == "ready" and r["ready"]["contract"]["text"] == "robotics"


# ---------------------------------------------------------------- the analyst
def _analyst(script):
    """A scripted analyst. `script` is a list of replies; the calls it received are recorded for assertions."""
    calls = []

    async def llm(system, user):
        import json as _j
        calls.append({"system": system, "payload": _j.loads(user)})
        return script[min(len(calls) - 1, len(script) - 1)]
    return llm, calls


def test_analyst_asks_an_open_question_and_the_answer_sharpens_the_words():
    """The distinction the schema cannot hold: one tech_area covers training, inference and eval alike, so the
    only thing that separates them is the text the semantic leg matches on."""
    llm, calls = _analyst([
        {"understanding": "You want the infrastructure layer, not the apps on top.", "text": "platforms for ML training and data systems",
         "question": {"kind": "open", "key": "layer", "words": "Training-time infrastructure, or inference and serving?",
                      "why": "they are different companies", "options": ["training", "inference and serving", "both"]}, "ready": False},
        {"understanding": "Training-time infrastructure at scale.", "text": "distributed training infrastructure and model serving at scale",
         "question": None, "ready": True},
    ])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="deep tech platforms that power ML and data systems"))
    assert r["question"]["kind"] == "open" and r["question"]["words"].startswith("Training-time")
    assert [o[0] for o in r["question"]["options"]] == ["training", "inference and serving", "both"]
    r = run(svc.step(state=r["state"], answer={"name": "layer", "value": "training"}))
    assert r["stage"] == "ready"
    # the answer reached the words the search matches on — which is the leg that actually separates these companies
    assert r["ready"]["contract"]["text"] == "distributed training infrastructure and model serving at scale"
    assert "Training-time infrastructure at scale." in r["ready"]["understood"]


def test_the_analyst_may_choose_and_phrase_but_never_invent():
    """A key that is not on the measured shortlist is refused, and the deterministic gate takes the turn."""
    llm, calls = _analyst([{"understanding": "", "text": "", "question": {"kind": "key", "key": "secret_sauce", "words": "What sauce?"}, "ready": False}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    assert r["question"]["name"] != "secret_sauce"
    assert r["question"]["name"] in ("tech_area", "country", "total_disclosed_funding", "customer", "metro", "last_round_months", "founder_count", "program", "hiring")


def test_the_analyst_may_not_offer_a_value_the_index_does_not_hold():
    llm, _ = _analyst([{"question": {"kind": "open", "key": "layer", "words": "Which layer?", "options": ["a", "b"]}, "ready": False},
                       {"question": {"kind": "key", "key": "country", "words": "Where?", "options": ["us", "atlantis"]}, "ready": False}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    r = run(svc.step(state=r["state"], answer={"name": "layer", "value": "a"}))
    assert r["question"]["name"] == "country"
    assert [o[0] for o in r["question"]["options"]] == ["us", "uk"]     # our counts, never the model's list


def test_memory_rides_every_turn():
    """What the analyst understood, what the investor ruled out, and everything already asked come back to it."""
    llm, calls = _analyst([
        {"understanding": "Infrastructure, not applications.", "ruled_out": ["consumer apps"], "text": "ML infrastructure",
         "question": {"kind": "open", "key": "layer", "words": "Which layer?", "options": ["training", "serving"]}, "ready": False},
        {"understanding": "Infrastructure, not applications.", "ruled_out": ["consumer apps"], "text": "ML infrastructure",
         "question": {"kind": "key", "key": "country", "words": "Where should they be based?"}, "ready": False},
        {"understanding": "US infrastructure companies.", "text": "US ML infrastructure", "question": None, "ready": True},
    ])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ML infra, no consumer stuff"))
    r = run(svc.step(state=r["state"], answer={"name": "layer", "value": "training"}))
    r = run(svc.step(state=r["state"], answer={"name": "country", "value": "us"}))
    second = calls[2]["payload"]
    assert second["understanding_so_far"] == "Infrastructure, not applications."
    assert second["ruled_out"] == ["consumer apps"]
    assert "country" in second["already_asked"]
    assert second["search_so_far"]["must"]["country"] == ["us"]
    assert any(m["said"] for m in second["conversation"])
    assert r["ready"]["ruled_out"] == ["consumer apps"]


def test_the_first_question_is_about_what_they_build_not_how_they_sell():
    """The opening question's SHAPE is the vertical's call, not the model's. Told merely to prefer an open
    question, the first production run asked for a business model and labelled it "open"; so on turn one the
    facets are withheld outright and a facet proposal is structurally inadmissible."""
    llm, calls = _analyst([{"question": {"kind": "key", "key": "country", "words": "Where are they based?"}, "ready": False},
                           {"question": None, "ready": True}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    assert calls[0]["payload"]["can_filter_on"] == []                       # nothing to filter on, only the thesis
    assert "MUST BE kind" in calls[0]["system"]
    assert (r.get("question") or {}).get("name") != "country"               # the facet grab is refused


def test_the_analyst_only_sees_keys_the_index_can_answer():
    llm, calls = _analyst([{"question": {"kind": "open", "key": "layer", "words": "Which layer?", "options": ["a", "b"]}, "ready": False},
                           {"question": None, "ready": True}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    run(svc.step(state=r["state"], answer={"name": "layer", "value": "a"}))
    offered = {c["key"] for c in calls[1]["payload"]["can_filter_on"]}      # the SECOND turn sees the facets
    assert "stage" not in offered and "business_model" not in offered      # 0.9% and 0% known here
    assert "country" in offered and "total_disclosed_funding" in offered


def test_the_model_is_called_at_most_once_per_turn_and_is_budgeted():
    """API credit discipline: one small call per turn, and the analyst stops asking after its budget."""
    llm, calls = _analyst([{"understanding": "u", "text": "t", "question": {"kind": "open", "key": "k", "words": "w?", "options": ["a", "b"]}, "ready": False}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    turns = 1
    while r["stage"] != "ready" and turns < 12:
        r = run(svc.step(state=r["state"], answer={"name": r["question"]["name"], "value": "__skip__"}))
        turns += 1
    assert r["stage"] == "ready"
    assert len(calls) == turns                       # exactly one model call per turn, never two
    assert r["state"]["kernel"]["counts_asked"]["analyst"] <= ANALYST_BUDGET


def test_a_broken_model_never_breaks_the_intake():
    async def llm(system, user):
        raise RuntimeError("provider down")
    r = run(_svc(llm).step(state=None, message="robotics companies"))
    assert r["stage"] in ("questions", "ready")
    if r["stage"] == "questions":
        assert r["question"]["name"] in ("tech_area", "country", "total_disclosed_funding", "customer", "metro", "last_round_months", "founder_count", "program", "hiring")


# ---------------------------------------------------------------- the read-back
def test_understood_words_reads_like_a_person():
    s = understood_words({"text": "ai infra", "must": {"tech_area": ["ai_infra"], "total_disclosed_funding": {"min": 5e6}},
                          "scope": {"exclude": {"program": ["yc"]}}, "center": {"key": "stage", "value": "seed"}})
    assert "building in AI infra" in s and "at least $5M" in s and "not Y Combinator" in s and "centred on seed" in s
    assert "≥" not in s and "min" not in s


def test_understood_words_says_the_bounds_the_way_a_person_would():
    s = understood_words({"must": {"founder_count": {"min": 2.0, "max": 2.0}}})
    assert "2 founders" in s and "≤" not in s


def test_the_analysts_own_read_back_leads_and_the_filters_still_show():
    s = understood_words({"text": "training infra", "must": {"country": ["us"]}}, understanding="You want training infrastructure sold to labs.")
    assert s.startswith("You want training infrastructure sold to labs.")
    assert "based in US" in s and "training infra" in s


def test_stage_in_the_opening_becomes_the_centre_and_refinements_merge():
    svc = _svc()

    async def compile_with_stage(text):
        c = Contract(kind=KIND, text=text)
        if "seed" in text:
            c.prefer["stage"] = ["seed"]
        if "robot" in text:
            c.must["tech_area"] = ["robotics"]
        return c, []

    svc.compile_fn = compile_with_stage
    r = run(svc.step(state=None, message="seed robotics"))
    assert r["state"]["kernel"]["contract"]["center"] == {"key": "stage", "value": "seed", "span": 1}
    while r["stage"] != "ready":
        r = run(svc.step(state=r["state"], answer={"name": r["question"]["name"], "value": "__skip__"}))
    assert r["ready"]["contract"]["center"]["value"] == "seed"


def test_a_typed_reply_never_leaves_a_question_to_be_asked_again():
    """Even with no analyst to read it — no model, or its budget spent — a question the investor has already
    been asked is spent. Asking the same thing twice is the fastest way to stop sounding like an analyst."""
    svc = _svc()                                   # no model at all
    r = run(svc.step(state=None, message="ai infra startups"))
    first = r["question"]["name"]
    r = run(svc.step(state=r["state"], message="not sure, whatever you think"))
    assert first in r["state"]["kernel"]["asked"]
    assert (r["question"] or {}).get("name") != first


def test_an_open_question_answered_in_words_still_reaches_the_query():
    llm, _ = _analyst([{"question": {"kind": "open", "key": "layer", "words": "Which layer?", "options": ["a"]}, "ready": False},
                       {"question": None, "ready": True}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ML platforms"))
    assert r["question"]["kind"] == "open"
    r = run(svc.step(state=r["state"], message="the serving layer, GPU scheduling"))
    assert "layer" in r["state"]["kernel"]["asked"]
    assert r["stage"] == "ready"


def test_a_spent_analyst_budget_ends_the_intake_rather_than_handing_back_to_the_gate():
    """The first production run asked its three model questions and then the deterministic gate quietly
    added a fourth — a metro, right after a country. A budget that caps only the model's questions caps
    nothing; an analyst that has decided it has enough stops."""
    llm, calls = _analyst([{"question": {"kind": "open", "key": "k1", "words": "w?", "options": ["a", "b"]}, "ready": False}])
    svc = _svc(llm)
    r = run(svc.step(state=None, message="ai infra"))
    asked = 0
    while r["stage"] != "ready" and asked < 10:
        r = run(svc.step(state=r["state"], answer={"name": r["question"]["name"], "value": "__skip__"}))
        asked += 1
    assert r["stage"] == "ready"
    assert r["state"]["kernel"]["counts_asked"]["analyst"] <= ANALYST_BUDGET
    assert len(r["state"]["kernel"]["asked"]) <= MAX_QUESTIONS      # whoever chose them


def test_the_read_back_is_addressed_to_the_investor_not_about_them():
    """The leading line of the ready card is read BY the person it describes."""
    s = understood_words({"text": "ml infra", "prefer": {"business_model": ["saas"]}},
                         understanding="You want the training layer, not the applications.")
    assert s.startswith("You want ")
    assert "Ranking up companies on a SaaS model." in s
    assert "They want" not in s
