"""Merged search for startups, offline: recipes probed by a fake slice, evaluated by a fake evaluator, fused, judged
by a fake blind judge; the merged order and the numbers on the card. Plus the index-aware collapse rule and U
diagnostics over the same fakes."""
from __future__ import annotations

import asyncio

from eigen_kernel.facets import Contract

from api.startups import contract_search as cs
from api.startups.schema import KIND


def run(coro):
    return asyncio.run(coro)


ROWS = {"strict": ["a", "b", "c"], "relaxed:metro": ["b", "d", "e", "a"], "default": ["c", "f"]}
SIZES = {"strict": 3, "relaxed:metro": 40, "default": 12}


async def slice_fn(must, exclude):
    if "metro" in must and "customer" in must:
        return 3
    if "metro" not in must and "customer" in must:
        return 40
    return 12


async def evaluate_fn(contract, counts=True):
    name = "strict" if "metro" in contract.must and "customer" in contract.must else ("relaxed:metro" if "customer" in contract.must else "default")
    rows = [{"id": i, "kind": KIND, "sim": 0.5, "facets": {"tech_area": ["ai_infra"]}, "numeric": {}, "company": {"name": i.upper(), "one_liner": "x"}} for i in ROWS[name]]
    return {"rows": rows, "counts": {"tech_area": {"ai_infra": 3}} if counts else {}, "coverage": {"matched": SIZES[name]}, "contract": contract.to_dict(), "labels": {}}


async def judge(system, user):
    assert "STARTUPS" in system and "WORDS: ai infra for banks" in user
    ids = [line.split("]")[0][1:] for line in user.split("ROWS:\n")[1].splitlines() if line.startswith("[")]
    names = {line.split("]")[0][1:]: line.split("] ")[1].split(" ·")[0] for line in user.split("ROWS:\n")[1].splitlines() if line.startswith("[")}
    return {"verdicts": [{"id": i, "fit": ("no" if names[i] == "D" else "partial" if names[i] == "E" else "yes"), "why": "test"} for i in ids]}


def test_merged_search_fuses_recipes_and_orders_by_verdicts():
    c = Contract(kind=KIND, text="ai infra for banks", must={"tech_area": ["ai_infra"], "metro": ["boston"], "customer": ["enterprise"]})
    out = run(cs.merged_search(c, user_keys={"tech_area"}, evaluate_fn=evaluate_fn, slice_fn=slice_fn, llm_json=judge))
    names = [r["name"] for r in out["merge"]["recipes"]]
    assert names[0] == "strict" and "relaxed:metro" in names and "default" in names
    ids = [r["id"] for r in out["rows"]]
    assert ids[-1] == "d" and out["rows"][-1]["fit"] == "no"                  # judged 'no' sinks below everything
    assert ids[0] in ("a", "b", "c") and out["rows"][0]["fit"] == "yes"
    assert out["rows"][0]["found_by"] and out["merge"]["fits"] >= 3 and out["merge"]["weak"] is False
    assert out["counts"] == {"tech_area": {"ai_infra": 3}}                     # the rail's layer is the strict contract's
    off = run(cs.merged_search(c, user_keys={"tech_area"}, evaluate_fn=evaluate_fn, slice_fn=slice_fn, llm_json=judge, off=["relaxed:metro"]))
    assert "relaxed:metro" not in [r["name"] for r in off["merge"]["recipes"]] and "d" not in [r["id"] for r in off["rows"]]


def test_index_aware_demotes_a_collapsing_compiled_must_never_the_users():
    async def sl(must, exclude):
        return 3 if "metro" in must else 400
    c = Contract(kind=KIND, text="x", must={"tech_area": ["ai_infra"], "metro": ["boston"]})
    c2, notes = run(cs.index_aware(c, user_keys=set(), slice_fn=sl, coverage={"metro": 0.35}))
    assert "metro" not in c2.must and c2.prefer["metro"] == ["boston"] and notes[0]["rule"] == "collapsing"
    c3, notes3 = run(cs.index_aware(c, user_keys={"metro"}, slice_fn=sl, coverage={"metro": 0.35}))
    assert c3.must["metro"] == ["boston"] and notes3 == []
    d = run(cs.u_diagnostics(c, user_keys={"metro"}, slice_fn=sl))
    assert d[0]["key"] == "metro" and d[0]["pool_with"] == 3 and d[0]["pool_without"] == 400


def test_judge_row_and_brief_shapes():
    row = {"id": "acme.ai", "facets": {"tech_area": ["ai_infra", "fintech"], "stage": ["seed"], "metro": ["bay_area"], "country": ["us"], "program": ["yc"]},
           "numeric": {"total_disclosed_funding": 12e6}, "company": {"name": "Acme", "one_liner": "inference for banks", "founders": [{"name": "Jane"}]}}
    line = cs.judge_row("r1", row)
    assert line.startswith("[r1] Acme · inference for banks · areas: AI infra, fintech · sells to: — · stage: seed · funding: $12.0M disclosed · HQ: Bay Area/US · founders: Jane · program: Y Combinator")
    b = cs.judge_brief("ai infra for banks", {"must": {"tech_area": ["ai_infra"], "total_disclosed_funding": {"min": 5e6}}, "prefer": {"program": ["yc"]}, "scope": {"exclude": {"country": ["us"]}}, "center": {"key": "stage", "value": "seed"}})
    assert "REQUIRED: tech area: AI infra; total disclosed funding: min 5e+06; not country: US" in b and "PREFERRED: program: Y Combinator" in b and "STAGE: around seed" in b
