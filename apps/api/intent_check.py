"""THE INTENT DEBUGGER — does the search understand what was asked, and if not, what else could it mean?

This is not the `directions` chips and it is not the rail. Both of those FILTER WHAT CAME BACK, key by key,
with counts. The thing neither can do is ask whether the QUESTION was understood, because that is a reading
rather than a count, and two readings of the same words retrieve different firms.

It costs ONE model call, and only when the search is genuinely unsure (`worth_asking`): a short query, one
the lexicon read two ways, or a result set nothing matched well. Cached on the query, the contract that ran
and the conversation so far, so re-asking the same thing inside the window is free.

Shared by both search modes, which is why it sits here rather than inside either of them: the mechanics are
identical and only the words differ, so the prompt module is a parameter. (`apps/api/jobs.py` was factored
out for the same reason — two copies of one contract drift.)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from eigen_kernel.facets import evidence, parse_intent, worth_asking

_log = logging.getLogger(__name__)
TTL_SECONDS = 900.0
MAX_CACHE = 300
# One small JSON call per unsure search turn. Projected before any of this ran: the evidence pack is capped
# at 12k characters and the answer is a few hundred tokens, so a turn is well under a cent — but it is a
# call on the hot path, which is why `worth_asking` gets to say no and why the cache window is generous.
PROJECTED_USD_PER_TURN = 0.004


async def check(*, llm_json, kind: str, query: str, contract, out: dict, rows: list, schema,
                prompt, cache: dict, ambiguous: bool = False, history: list | None = None) -> dict | None:
    """{understanding, noticed, believed, question, readings, ask, why} — or None when it could not run.

    A question we cannot ask must never fail a search, so every failure here returns None and the results
    render exactly as they would have.
    """
    if llm_json is None:
        return None
    try:
        ok, why = worth_asking(query, out.get("coverage") or {}, ambiguous=ambiguous, history=history)
        if not ok:
            return {"readings": [], "why": why}
        # The conversation is part of the key: the same words after a different exchange deserve a
        # different question, and caching across that would re-ask what was just answered.
        key = (kind, (query or "").strip().lower(),
               json.dumps(getattr(contract, "must", {}) or {}, sort_keys=True),
               json.dumps(history or [], sort_keys=True, default=str)[:600])
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL_SECONDS:
            return dict(hit[1])
        ev = evidence(query, contract, rows, out.get("counts") or {}, schema, kind=kind, history=history)
        # eigen's `llm_json` is a COROUTINE function (see startups/compile.py), unlike roster's, which is
        # sync and reached through a thread. Wrapping this one in `to_thread` returns the coroutine object
        # itself and never runs it — the debugger came back blank with no error at all.
        raw = llm_json(prompt.SYSTEM, prompt.user_message(ev))
        if asyncio.iscoroutine(raw):
            raw = await raw
        got = parse_intent(raw, schema, kind)
        res = {**(got.to_dict() if got else {"readings": []}), "why": why}
        if len(cache) > MAX_CACHE:
            cache.clear()
        cache[key] = (time.monotonic(), dict(res))
        return res
    except Exception as e:      # noqa: BLE001 — a question we cannot ask must never fail a search
        _log.warning("intent check unavailable: %s: %s", type(e).__name__, str(e)[:200])
        return None
