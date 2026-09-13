"""Eval harness: produce an answer for each gold question through the REAL pipeline, judge it, aggregate.

`run_eval` is decoupled — it takes an injected `produce(item) -> (answer, evidence)` and a `judge_llm`,
so it is unit-tested with fakes and never spends. `build_producer` wires the real attack+synthesis path
(the same seams routes.py uses) for a live baseline run; that run spends (retrieval + LLM), so it is
gated by the caller (see run.py).
"""
from __future__ import annotations

import json
import os

from .judge import aggregate, judge_answer


def load_gold(path: str | None = None) -> list[dict]:
    p = path or os.path.join(os.path.dirname(__file__), "gold.json")
    with open(p) as fh:
        return (json.load(fh) or {}).get("items") or []


def build_producer(*, dsn, web_client, relation_llm, synth_llm, refuter_llm, tenant, reformulate_llm=None):
    """An async producer(item) -> (answer, evidence) over the real pipeline — attack_claim gathers +
    gates evidence (always_retrieve, so call_only aspects still surface what the record says), and
    make_synthesize writes the grounded answer. Mirrors routes._run_question_rows' answer path; we take
    the ANSWER (the thing we're grading), so the per-aspect verdict machinery is not needed here."""
    from .. import attack as atk
    from ..engine_adapter import make_synthesize
    from eigen_kernel.decision import Question, QuestionKind

    async def producer(item):
        aspect_prompt = item.get("question") or item.get("target") or ""
        ctx = f"Thesis under test: {item.get('thesis','')} | Aspect: {aspect_prompt}"
        res = await atk.attack_claim(dsn, claim=item.get("target", ""),
                                     settleable=item.get("settleable", "corpus"), judge_llm=refuter_llm,
                                     extra_context=ctx, web_client=web_client, relation_llm=relation_llm,
                                     evidence_policy=None, tenant=tenant, always_retrieve=True,
                                     reformulate_llm=reformulate_llm)
        evidence = res.get("evidence") or []
        synth = make_synthesize(synth_llm, thesis=item.get("thesis", ""), aspect=aspect_prompt)
        q = Question(kind=QuestionKind.SEEK_SUPPORT, text=item.get("question", ""),
                     target=item.get("target", ""), polarity=1)
        answer = await synth(q, evidence)
        return answer, evidence

    return producer


async def run_eval(items, *, produce, judge_llm) -> dict:
    """Produce + judge each gold item; return per-item results and the aggregate baseline. Never raises
    on one item — a producer/judge failure records a 0-scored row so the run always completes."""
    results = []
    for item in items:
        try:
            answer, evidence = await produce(item)
        except Exception as exc:      # noqa: BLE001 — one item's failure never sinks the batch
            answer, evidence = "", []
            results.append({"id": item.get("id"), "answer": "", "evidence_n": 0, "error": str(exc)[:200],
                            "scores": {}})
            continue
        scores = await judge_answer(judge_llm, question=item.get("question", ""),
                                    thesis=item.get("thesis", ""), aspect=item.get("question", ""),
                                    rubric_focus=item.get("rubric_focus", ""), answer=answer,
                                    evidence=evidence)
        results.append({"id": item.get("id"), "answer": answer, "evidence_n": len(evidence),
                        "scores": scores})
    return {"results": results, "summary": aggregate(results)}


def format_report(report: dict) -> str:
    """A compact human-readable baseline table for the terminal."""
    rows = ["id                     ev  cov spec grnd use  OVR  missing",
            "---------------------  --  --- ---- ---- ---  ---  -------"]
    for r in report["results"]:
        s = r.get("scores", {})
        rows.append("%-21s  %2d  %3s %4s %4s %3s  %3s  %s" % (
            (r.get("id") or "")[:21], r.get("evidence_n", 0),
            s.get("coverage", "-"), s.get("specificity", "-"), s.get("groundedness", "-"),
            s.get("usefulness", "-"), s.get("overall", "-"), (s.get("missing") or r.get("error") or "")[:60]))
    a = report["summary"]
    rows.append("---------------------  --  --- ---- ---- ---  ---")
    rows.append("MEANS (n=%d, scored=%d)      cov=%.2f spec=%.2f grnd=%.2f use=%.2f  OVERALL=%.2f" % (
        a.get("n", 0), a.get("n_scored", 0), a.get("coverage", 0), a.get("specificity", 0),
        a.get("groundedness", 0), a.get("usefulness", 0), a.get("overall", 0)))
    return "\n".join(rows)
