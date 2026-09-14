"""Golden relevance eval for startup search — does the search surface companies a human agrees are
relevant, especially ones whose own words differ from the investor's query?

Runs the gold set (`data/eval_relevance_gold.json`) against a live API and reports recall@K and MRR of
each case's expected set, per condition. Read-only against the corpus; the only spend is one query
expansion per case (a cheap model call) plus, in `--mode merged`, the blind judge.

    # baseline vs. HyDE query expansion, against prod, single mode (no judge):
    railway run -s eigen-api -- env PYTHONPATH=apps .venv/bin/python -m api.startups.eval_relevance \\
        --base https://eigen-api-production.up.railway.app

`--deployed` skips local expansion and just measures the endpoint as it is (use after the fix ships, to
confirm the deployed search reproduces the gain).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from . import pipeline
from .query_expand import expand_query

GOLD = Path(__file__).parent / "data" / "eval_relevance_gold.json"
KS = (5, 10, 60)


def _ranks(rows: list[dict], expected: list[str]) -> dict[str, int | None]:
    by_id = {str(r.get("id")): i + 1 for i, r in enumerate(rows)}
    return {d: by_id.get(d) for d in expected}


def _metrics(cases_ranks: list[dict]) -> dict:
    """recall@K over ALL expected across cases; MRR = mean over expected of 1/rank (0 if absent)."""
    total = sum(len(c["ranks"]) for c in cases_ranks)
    out: dict = {"expected_total": total}
    for k in KS:
        hit = sum(1 for c in cases_ranks for r in c["ranks"].values() if r is not None and r <= k)
        out[f"recall@{k}"] = round(hit / total, 3) if total else 0.0
    mrr = sum((1.0 / r) for c in cases_ranks for r in c["ranks"].values() if r) / total if total else 0.0
    out["mrr"] = round(mrr, 3)
    out["absent"] = sum(1 for c in cases_ranks for r in c["ranks"].values() if r is None)
    return out


async def _search(client: httpx.AsyncClient, base: str, text: str, mode: str) -> list[dict]:
    body = {"contract": {"text": text, "must": {}, "prefer": {}, "merge": {"mode": mode}, "limit": 60}}
    resp = await client.post(f"{base}/startups/evaluate", json=body, timeout=90)
    resp.raise_for_status()
    return resp.json().get("rows", []) or []


async def run(base: str, mode: str, deployed: bool) -> None:
    gold = json.loads(GOLD.read_text())
    cases = gold["cases"]
    llm_json = None if deployed else pipeline.Providers.from_env().llm_json
    if not deployed and llm_json is None:
        raise SystemExit("no LLM configured for expansion; run under `railway run -s eigen-api` or pass --deployed")

    base_ranks: list[dict] = []
    exp_ranks: list[dict] = []
    async with httpx.AsyncClient() as client:
        for c in cases:
            q, expected, thin = c["query"], c["expected"], set(c.get("thin") or [])
            base_rows = await _search(client, base, q, mode)
            br = _ranks(base_rows, expected)
            base_ranks.append({"query": q, "ranks": br})

            if deployed:
                er = br
            else:
                expanded = await expand_query(llm_json, q)
                exp_rows = await _search(client, base, expanded or q, mode) if expanded else base_rows
                er = _ranks(exp_rows, expected)
            exp_ranks.append({"query": q, "ranks": er})

            print(f"\n=== {q!r}  ({'deployed' if deployed else 'baseline vs expanded'}, mode={mode}) ===")
            for d in expected:
                mark = " [thin]" if d in thin else ""
                b, e = br[d], er[d]
                arrow = "" if deployed else f"  ->  {e if e else 'ABSENT'}"
                delta = ""
                if not deployed and b != e:
                    if e and (not b or e < b):
                        delta = "  ✅ better"
                    elif b and (not e or e > b):
                        delta = "  ⚠️ worse"
                print(f"   {d:26}{mark:8} baseline={b if b else 'ABSENT'}{arrow}{delta}")

    print("\n" + "=" * 60)
    print("BASELINE:", _metrics(base_ranks))
    if not deployed:
        print("EXPANDED:", _metrics(exp_ranks))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("EIGEN_EVAL_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--mode", default="single", choices=["single", "merged"])
    ap.add_argument("--deployed", action="store_true", help="measure the endpoint as-is (no local expansion)")
    args = ap.parse_args()
    asyncio.run(run(args.base, args.mode, args.deployed))


if __name__ == "__main__":
    main()
