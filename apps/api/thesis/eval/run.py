"""Live baseline runner for the thesis answer-quality eval. SPENDS (retrieval + LLM per gold item):
run deliberately, e.g. `PYTHONPATH=apps railway run -s eigen-api .venv/bin/python -m api.thesis.eval.run`.
Prints a baseline table and writes /tmp/eigen_eval_report.json."""
from __future__ import annotations

import asyncio
import json
import os

from api.startups.pipeline import Providers
from api.thesis import attack as atk
from api.thesis.eval.harness import build_producer, format_report, load_gold, run_eval


async def main():
    dsn = os.environ.get("EIGEN_CORPUS_DSN") or ""
    llm = Providers.from_env().llm_json          # default (DeepSeek): relation judge + the eval judge
    from api.thesis.llm import strong_json
    strong = strong_json() or llm                # strong (OpenAI): synthesis + query reformulation
    refuter = None
    try:
        if os.environ.get("OPENAI_API_KEY"):
            from eigen_kernel.providers.openai_client import OpenAILLMClient
            refuter = OpenAILLMClient()
    except Exception:      # noqa: BLE001
        refuter = None
    web = atk._web_client()
    tenant = os.environ.get("EIGEN_TENANT_ID") or "demo"
    strong_on = strong is not llm
    items = load_gold()
    print(f"[eval] {len(items)} gold items · corpus={'yes' if dsn else 'no'} · "
          f"web={'yes' if web else 'no'} · refuter={'yes' if refuter else 'no'} · "
          f"strong(synth+reformulate)={'openai' if strong_on else 'default'} · "
          f"judge={'cross-family' if strong_on else 'same-family'} · tenant={tenant}")
    produce = build_producer(dsn=dsn, web_client=web, relation_llm=llm, synth_llm=strong,
                             refuter_llm=refuter, tenant=tenant, reformulate_llm=strong)
    report = await run_eval(items, produce=produce, judge_llm=llm)   # judge = DeepSeek, cross-family from OpenAI synth
    print("\n" + format_report(report) + "\n")
    try:
        with open("/tmp/eigen_eval_report.json", "w") as fh:
            json.dump(report, fh, indent=2)
        print("[eval] full report → /tmp/eigen_eval_report.json")
    except Exception:      # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
