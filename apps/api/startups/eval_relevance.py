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


def _metrics(cases_ranks: list[dict], *, only: str | None = None) -> dict:
    """recall@K over expected across cases; MRR = mean over expected of 1/rank (0 if absent).
    `only`='thin' restricts to vocabulary-gap anchors, 'control' to the rest."""
    def keep(c, d):
        if only is None:
            return True
        is_thin = d in set(c.get("thin") or [])
        return is_thin if only == "thin" else not is_thin
    pairs = [(c, d, r) for c in cases_ranks for d, r in c["ranks"].items() if keep(c, d)]
    total = len(pairs)
    out: dict = {"expected_total": total}
    for k in KS:
        out[f"recall@{k}"] = round(sum(1 for _, _, r in pairs if r is not None and r <= k) / total, 3) if total else 0.0
    out["mrr"] = round(sum((1.0 / r) for _, _, r in pairs if r) / total, 3) if total else 0.0
    out["absent"] = sum(1 for _, _, r in pairs if r is None)
    return out


async def _search(client: httpx.AsyncClient, base: str, text: str, mode: str) -> list[dict]:
    body = {"contract": {"text": text, "must": {}, "prefer": {}, "merge": {"mode": mode}, "limit": 60}}
    resp = await client.post(f"{base}/startups/evaluate", json=body, timeout=90)
    resp.raise_for_status()
    return resp.json().get("rows", []) or []


async def _search_compiled(client: httpx.AsyncClient, base: str, query: str, mode: str) -> list[dict]:
    """The REAL user path: compile the brief into a contract (musts, prefers), then search it. Measures
    #2b (compile policy) end to end — a hard tech_area must that excludes adjacent-area companies shows up
    here where the bare-query eval cannot see it."""
    cr = await client.post(f"{base}/startups/compile", json={"text": query}, timeout=60)
    cr.raise_for_status()
    contract = (cr.json() or {}).get("contract") or {"text": query}
    contract["merge"] = {"mode": mode}
    contract["limit"] = 60
    resp = await client.post(f"{base}/startups/evaluate", json={"contract": contract}, timeout=90)
    resp.raise_for_status()
    return resp.json().get("rows", []) or []


async def run(base: str, mode: str, deployed: bool, compiled: bool = False) -> None:
    gold = json.loads(GOLD.read_text())
    cases = gold["cases"]
    deployed = deployed or compiled   # compiled mode measures the endpoint as-is (compile happens server-side)
    llm_json = None if deployed else pipeline.Providers.from_env().llm_json
    if not deployed and llm_json is None:
        raise SystemExit("no LLM configured for expansion; run under `railway run -s eigen-api` or pass --deployed")

    base_ranks: list[dict] = []
    exp_ranks: list[dict] = []
    async with httpx.AsyncClient() as client:
        for c in cases:
            q, expected, thin = c["query"], c["expected"], set(c.get("thin") or [])
            if compiled:
                try:
                    rows = await _search_compiled(client, base, q, mode)
                except Exception as e:   # noqa: BLE001 — one case's timeout must not sink the whole aggregate
                    print(f"  {q!r:44} ERROR {type(e).__name__} — counted as all-absent")
                    rows = []
                r = _ranks(rows, expected)
                base_ranks.append({"query": q, "ranks": r, "thin": list(thin)})
                exp_ranks.append({"query": q, "ranks": r, "thin": list(thin)})
                miss = [d for d in expected if r[d] is None]
                print(f"  {q!r:44} recall@60={sum(1 for v in r.values() if v)}/{len(expected)}  absent={miss}")
                continue
            base_rows = await _search(client, base, q, mode)
            br = _ranks(base_rows, expected)
            base_ranks.append({"query": q, "ranks": br, "thin": list(thin)})

            if deployed:
                er = br
            else:
                expanded = await expand_query(llm_json, q)
                exp_rows = await _search(client, base, expanded or q, mode) if expanded else base_rows
                er = _ranks(exp_rows, expected)
            exp_ranks.append({"query": q, "ranks": er, "thin": list(thin)})

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

    ranks = exp_ranks if not deployed else base_ranks
    print("\n" + "=" * 60)
    if not deployed:
        print("BASELINE:", _metrics(base_ranks))
        print("EXPANDED:", _metrics(exp_ranks))
    else:
        print("ALL:    ", _metrics(ranks))
        print("THIN:   ", _metrics(ranks, only="thin"))
        print("CONTROL:", _metrics(ranks, only="control"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("EIGEN_EVAL_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--mode", default="single", choices=["single", "merged"])
    ap.add_argument("--deployed", action="store_true", help="measure the endpoint as-is (no local expansion)")
    ap.add_argument("--compiled", action="store_true", help="real path: compile each brief -> contract -> search (end to end)")
    args = ap.parse_args()
    asyncio.run(run(args.base, args.mode, args.deployed, args.compiled))


if __name__ == "__main__":
    main()
