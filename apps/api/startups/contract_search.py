"""CONTRACT SEARCH for startups — roster's guided-intake §12 adapted: choose and MERGE the constraint combinations by
measuring the index instead of guessing, then let one blind judge grade the head against the investor's own words.

  index_aware(c)        — deterministic, no model: a compiled must (never the user's own) that leaves fewer than the
                          viability floor while its removal multiplies the pool ≥ 5×, on a relaxable key, ranks instead.
  merged_search(c)      — recipes (strict · default · relaxed:<key> · loose) → slice-size probes → survivors evaluated
                          → reciprocal-rank fusion → ONE blind judge over the head (yes / partial / no, ≤ 8 words) →
                          merged order (fits, partials, the ungraded tail, then the judged 'no' rows) + the numbers.
The judge reads the BRIEF (words + what is required / preferred), never a contract, and one normalized row shape:
name · one-liner · areas · stage · funding · HQ · founders · program · evidence kind. A verdict is a labelled model
read on the card, never a fact."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Awaitable, Callable

from eigen_kernel.facets import Contract
from eigen_kernel.facets.contract_search import (blind, collapsing_musts, demote, head_precision, order_by_verdicts, recipes, relax_steps, resolve_blind_id,
                                                  rrf_fuse, survivors)

from .schema import KIND, SCHEMA, VALUE_LABELS

# keys a compiled must may be demoted on when it collapses the pool: open sets and the sparse keys (a must on tech
# area or program is the thesis itself and is never demoted by this rule — a small pool there is the answer)
RELAXABLE_KEYS = ("metro", "investor", "lead_investor", "founder_prior_company", "customer", "business_model", "hiring_function", "stage")
LADDER_DEFAULT_KEYS = ("customer", "business_model", "founder_count", "hiring")
JUDGE_HEAD, JUDGE_BATCHES, MERGE_RRF_K, WEAK_FITS = 40, 3, 60, 3
SCARCITY, MIN_RATIO = 20, 5.0
# SMART RELAXING (roster 2026-09-06, adapted): too few results → musts relax to preferences, LEAST important first, the
# compile's before the user's own, until the pool is a good size. The thesis (tech area) and the scope (country) never
# relax — a different area is not "more results". Numeric floors relax last and by removal (a preference cannot hold a
# range); the note says so. Sized to a 14k index (roster: 200 / 30 on 400k).
RELAX_ORDER = ("hiring_function", "hiring", "business_model", "customer", "founder_prior_company", "lead_investor", "investor", "program",
               "founder_count", "last_round_months", "metro", "total_disclosed_funding", "last_round_amount", "financing_scale", "arr", "stage")
RELAX_NEVER = ("tech_area", "country")
RELAX_MIN_SLICE, RELAX_TARGET_ROWS, RELAX_MAX_EVALUATES = 30, 12, 3


def _lab(k: str, v) -> str:
    return VALUE_LABELS.get(str(v)) or str(v).replace("_", " ")


async def index_aware(c: Contract, *, user_keys: set, slice_fn: Callable[[dict, dict], Awaitable[int]], coverage: dict | None) -> tuple[Contract, list[dict]]:
    """Collapsing musts → prefer (scarcity-gated, relaxable keys only, never the user's). Notes say what and why."""
    notes: list[dict] = []
    c = Contract.from_dict(c.to_dict())
    exclude = (c.scope or {}).get("exclude") or {}
    compiled = [k for k in c.must if k not in set(user_keys or ())]
    if not compiled:
        return c, notes
    try:
        pool_with = await slice_fn(dict(c.must), exclude)
    except Exception:   # noqa: BLE001
        return c, notes
    if pool_with >= SCARCITY:
        return c, notes
    without: dict = {}
    for key in compiled:
        try:
            without[key] = await slice_fn({k: v for k, v in c.must.items() if k != key}, exclude)
        except Exception:   # noqa: BLE001
            continue
    relaxable = {k for k in compiled if k in RELAXABLE_KEYS or float((coverage or {}).get(k, 1.0)) < 0.5}
    for col in collapsing_musts(pool_with, without, user_keys=set(user_keys or ()), relaxable_keys=relaxable, min_ratio=MIN_RATIO, scarcity=SCARCITY):
        vals = c.must.pop(col.key, None)
        if isinstance(vals, list) and vals:
            c.prefer[col.key] = sorted(set([str(v) for v in (c.prefer.get(col.key) or [])] + [str(v) for v in vals]))
        notes.append({"rule": "collapsing", "key": col.key, "values": vals, "why": col.reason, "action": "must → prefer"})
    return c, notes


async def u_diagnostics(c: Contract, *, user_keys: set, slice_fn) -> list[dict]:
    """What the user's OWN musts cost, when the pool is small: pool with, pool without (never relaxed for them)."""
    uk = [k for k in c.must if k in set(user_keys or ())]
    if not uk:
        return []
    exclude = (c.scope or {}).get("exclude") or {}
    try:
        pool_with = await slice_fn(dict(c.must), exclude)
    except Exception:   # noqa: BLE001
        return []
    if pool_with >= 50:
        return []
    out = []
    for key in uk:
        try:
            n = await slice_fn({k: v for k, v in c.must.items() if k != key}, exclude)
        except Exception:   # noqa: BLE001
            continue
        vals = c.must[key]
        shown = ", ".join(_lab(key, v) for v in vals) if isinstance(vals, list) else "range"
        out.append({"key": key, "label": (SCHEMA.key(key).label if SCHEMA.key(key) else key), "values": shown, "pool_with": pool_with, "pool_without": n})
    return out


def relax_steps_all(c: Contract, *, user_keys: set) -> list[tuple[str, bool]]:
    """Every must on a key in RELAX_ORDER — list values and numeric floors alike — least important first, the
    compile's before the user's own; the thesis and the scope (RELAX_NEVER) never."""
    rank = {k: i for i, k in enumerate(RELAX_ORDER)}
    uk = set(user_keys or ())
    keys = [k for k in c.must if k in rank and k not in RELAX_NEVER and c.must.get(k)]
    compiled = sorted([k for k in keys if k not in uk], key=lambda k: rank[k])
    own = sorted([k for k in keys if k in uk], key=lambda k: rank[k])
    return [(k, False) for k in compiled] + [(k, True) for k in own]


def demote_any(c: Contract, key: str) -> Contract:
    """A list must → prefer (kernel demote); a numeric floor → removed (a preference cannot hold a range)."""
    if isinstance(c.must.get(key), dict):
        n = Contract.from_dict(c.to_dict()); n.must.pop(key, None); return n
    return demote(c, key)


async def relax_to_enough(c: Contract, *, user_keys: set, slice_fn, evaluate_fn) -> tuple[dict, list[dict]]:
    """Cheap first: the must-slice is probed and relaxed until it holds RELAX_MIN_SLICE; then the search runs and,
    while it returns fewer than RELAX_TARGET_ROWS rows, one more must relaxes per evaluate (≤ RELAX_MAX_EVALUATES).
    Every relaxation is a note; a relaxed must still ranks first; nothing becomes an avoid."""
    notes: list[dict] = []
    steps = relax_steps_all(c, user_keys=set(user_keys or ()))
    cur = Contract.from_dict(c.to_dict())
    exclude = (cur.scope or {}).get("exclude") or {}
    strict_slice = await _safe_size(slice_fn, cur.must, exclude) if cur.must else None

    def _relax_one() -> bool:
        nonlocal cur
        if not steps:
            return False
        key, is_user = steps.pop(0)
        vals = cur.must.get(key)
        cur = demote_any(cur, key)
        notes.append({"rule": "relaxed", "key": key, "values": (vals if isinstance(vals, list) else None), "range": (vals if isinstance(vals, dict) else None),
                      "user": is_user, "action": ("must → prefer" if isinstance(vals, list) else "floor dropped")})
        return True

    size = strict_slice
    while size is not None and size < RELAX_MIN_SLICE and steps:
        if not _relax_one():
            break
        size = await _safe_size(slice_fn, cur.must, exclude) if cur.must else None
        notes[-1]["slice_after"] = size
    out = await evaluate_fn(cur, counts=True)
    n_eval = 1
    while len(out.get("rows") or []) < RELAX_TARGET_ROWS and steps and n_eval < RELAX_MAX_EVALUATES:
        if not _relax_one():
            break
        out = await evaluate_fn(cur, counts=True)
        n_eval += 1
        notes[-1]["rows_after"] = len(out.get("rows") or [])
    if notes:
        notes.append({"rule": "relax_summary", "strict_slice": strict_slice, "final_slice": size, "rows": len(out.get("rows") or []),
                      "relaxed_keys": [n["key"] for n in notes if n.get("rule") == "relaxed"], "user_relaxed": [n["key"] for n in notes if n.get("rule") == "relaxed" and n.get("user")]})
    return out, notes


# ---------------------------------------------------------------- the judge (startup vocabulary)
def judge_prompt() -> str:
    return ("You judge, row by row, whether each of these STARTUPS fits the BRIEF (an investor's own words, then what is REQUIRED and what is "
            "merely PREFERRED). Return ONLY JSON: {\"verdicts\": [{\"id\": the row id exactly as shown in brackets (e.g. \"r3\"), \"fit\": \"yes\" | "
            "\"partial\" | \"no\", \"why\": ≤ 8 words}]}, one verdict per row. "
            "yes = what the company builds and whom it sells to agree with the brief and nothing REQUIRED is contradicted. "
            "partial = the right kind of company but one dimension is off or unstated: a stage a step away, an adjacent area, a PREFERRED "
            "place / program / model missing, a stage or funding shown as —. "
            "no = a different kind of company or market, something REQUIRED contradicted, or a resemblance that is keyword-only (the same word "
            "in another sense). Preferences are wishes: a right-kind company lacking a preferred value is 'partial', never 'no'. "
            "Judge ONLY from the facts on the row; — means unknown, and unknown is never a 'no' on its own. Never judge from a name alone.")


def judge_brief(text: str, contract: dict | None) -> str:
    c = contract or {}
    def L(k, vs):
        if isinstance(vs, dict):
            return " ".join(f"{b} {v:g}" for b, v in vs.items())
        return ", ".join(_lab(k, v) for v in (vs if isinstance(vs, list) else [vs]))
    req = "; ".join(f"{k.replace('_', ' ')}: {L(k, v)}" for k, v in (c.get("must") or {}).items() if v)
    pref = "; ".join(f"{k.replace('_', ' ')}: {L(k, v)}" for k, v in (c.get("prefer") or {}).items() if v)
    ex = "; ".join(f"not {k.replace('_', ' ')}: {L(k, v)}" for k, v in ((c.get("scope") or {}).get("exclude") or {}).items() if v)
    ctr = c.get("center") or {}
    parts = [f"WORDS: {(text or '').strip()[:1200]}", f"REQUIRED: {req or '(nothing beyond the words)'}" + (f"; {ex}" if ex else ""), f"PREFERRED: {pref or '(none stated)'}"]
    if ctr.get("key") == "stage" and ctr.get("value"):
        parts.append(f"STAGE: around {_lab('stage', ctr['value'])} (a step away is partial)")
    return "\n".join(parts)


def judge_row(bid: str, row: dict) -> str:
    f = row.get("facets") or {}
    co = row.get("company") or {}
    first = lambda k: _lab(k, (f.get(k) or ["—"])[0]) if f.get(k) else "—"
    many = lambda k, n: ", ".join(_lab(k, x) for x in (f.get(k) or [])[:n]) or "—"
    num = row.get("numeric") or {}
    money = (f"${num['total_disclosed_funding'] / 1e6:.1f}M disclosed" if num.get("total_disclosed_funding") else "—")
    founders = ", ".join((x.get("name") or "") for x in (co.get("founders") or [])[:3]) or "—"
    ev = first("evidence_strength")
    return (f"[{bid}] {co.get('name') or row.get('id')} · {(co.get('one_liner') or '—')[:140]} · areas: {many('tech_area', 2)} · sells to: {first('customer')} "
            f"· stage: {first('stage')} · funding: {money} · HQ: {first('metro')}/{first('country')} · founders: {founders} · program: {first('program')} · evidence: {ev}")


# ---------------------------------------------------------------- merged search
def merge_options(cdict: dict | None) -> dict:
    m = (cdict or {}).get("merge") if isinstance((cdict or {}).get("merge"), dict) else {}
    mode = str(m.get("mode") or "").lower() or None
    return {"mode": mode if mode in ("merged", "single") else None, "off": [str(x) for x in (m.get("off") or []) if str(x)][:8],
            "user_keys": [str(x) for x in (m.get("user_keys") or []) if str(x)][:20], "relax": bool(m.get("relax"))}


async def merged_search(c: Contract, *, user_keys: set, evaluate_fn: Callable[..., Awaitable[dict]], slice_fn, llm_json, off: list[str] | None = None, top: int = 60) -> dict:
    """The evaluate shape (rows / counts / coverage / contract / labels — counts and coverage are the ratified
    contract's) plus `merge`: recipes with their numbers, the judge's tallies, WEAK. Rows carry fit / fit_why / found_by."""
    import time as _t
    t0 = _t.monotonic(); timings: dict = {}
    off = [str(x) for x in (off or [])]
    exclude = (c.scope or {}).get("exclude") or {}
    ladder = recipes(c, user_keys=set(user_keys or ()), relaxable_keys=set(RELAXABLE_KEYS), readings=[], default_keys=set(LADDER_DEFAULT_KEYS))
    kept = [r for r in ladder if r.name not in off] or ladder[:1]
    sizes = await asyncio.gather(*[_safe_size(slice_fn, r.contract.must, exclude) for r in kept])
    surv = survivors(kept, {r.name: n for r, n in zip(kept, sizes)}) or kept[:1]
    timings["probe"] = round(_t.monotonic() - t0, 2); t1 = _t.monotonic()
    for r in surv:
        r.contract.limit = top
    outs = await asyncio.gather(*[evaluate_fn(r.contract, counts=(i == 0)) for i, r in enumerate(surv)])
    timings["evaluate"] = round(_t.monotonic() - t1, 2); t2 = _t.monotonic()
    lists = {r.name: list(o.get("rows") or []) for r, o in zip(surv, outs)}
    fused = rrf_fuse(lists, k=MERGE_RRF_K)
    head = fused[:JUDGE_HEAD]
    seed = int(hashlib.sha1((c.text or "").encode("utf-8")).hexdigest()[:8], 16)
    items, mapping = blind(head, seed=seed)
    verdicts: dict = {}
    judge_error = None
    if items and llm_json is not None:
        brief_txt = "BRIEF\n" + judge_brief(c.text or "", c.to_dict())
        n_b = max(1, min(JUDGE_BATCHES, len(items)))
        batches = [items[i::n_b] for i in range(n_b)]
        async def _grade(batch):
            user = brief_txt + "\n\nROWS:\n" + "\n".join(judge_row(bid, r) for bid, r in batch)
            return await llm_json(judge_prompt(), user)
        results = await asyncio.gather(*[_grade(b) for b in batches], return_exceptions=True)
        for d in results:
            if isinstance(d, Exception) or not isinstance(d, dict):
                judge_error = (str(d)[:120] if isinstance(d, Exception) else "bad judge output")
                continue
            for v in (d.get("verdicts") or []):
                if not isinstance(v, dict):
                    continue
                rid = resolve_blind_id(mapping, v.get("id"))
                fit = str(v.get("fit") or "").lower()
                if rid and fit in ("yes", "partial", "no"):
                    verdicts[rid] = {"fit": fit, "why": str(v.get("why") or "")[:80]}
    timings["judge"] = round(_t.monotonic() - t2, 2); timings["total"] = round(_t.monotonic() - t0, 2)
    ordered = order_by_verdicts(fused, verdicts, head=JUDGE_HEAD)
    tallies = {k: sum(1 for v in verdicts.values() if v["fit"] == k) for k in ("yes", "partial", "no")}
    per_recipe = []
    for r, o in zip(surv, outs):
        rows_r = lists[r.name]; ids_r = {str(x.get("id")) for x in rows_r}
        per_recipe.append({"name": r.name, "why": r.why, "pool": r.pool if r.pool is not None else (o.get("coverage") or {}).get("matched"),
                           "evaluated": len(rows_r), "head_fits": sum(1 for rid, v in verdicts.items() if v["fit"] == "yes" and rid in ids_r),
                           "prec10": head_precision(rows_r, verdicts, k=10), "must": r.contract.must, "prefer": r.contract.prefer})
    strict = outs[0]
    rows = []
    for r in ordered[:top]:
        r = dict(r); r["fit"] = r.pop("_fit", None); r["fit_why"] = r.pop("_why", ""); r["found_by"] = r.pop("_found_by", {}); r.pop("_fused", None)
        rows.append(r)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    merge = {"recipes": per_recipe, "off": [n for n in off if any(x.name == n for x in ladder)], "ladder": [x.name for x in ladder],
             "head": len(head), "graded": len(verdicts), "fits": tallies["yes"], "partials": tallies["partial"], "nos": tallies["no"],
             "weak": bool(items) and tallies["yes"] < WEAK_FITS, "judge_error": judge_error, "prec10": head_precision(ordered, verdicts, k=10),
             "union": len(fused), "timings": timings}
    return {"rows": rows, "counts": strict.get("counts") or {}, "coverage": dict(strict.get("coverage") or {}), "contract": strict.get("contract") or c.to_dict(),
            "labels": strict.get("labels"), "merge": merge}


async def _safe_size(slice_fn, must, exclude):
    try:
        return await slice_fn(dict(must), exclude)
    except Exception:   # noqa: BLE001
        return None
