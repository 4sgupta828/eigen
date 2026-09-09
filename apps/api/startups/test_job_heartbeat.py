"""A spending job must keep its heartbeat even when nothing it reads decides anything.

`routes.py` marks any 'running' job whose `updated_at` is 30 minutes stale as orphaned. Only
`_progress` refreshes that column, and in both fact passes the call sat at the FOOT of the loop,
past a `continue` for a model error and a `continue` for the ordinary "this text does not say how
they charge". So a pass whose companies mostly do not decide — the normal case, measured at 0 of
200 on the current corpus — never beat, and the watchdog killed it mid-spend with an empty progress
row and no record of what it had cost. That is how job 72 died.
"""
from __future__ import annotations

import asyncio

from api.startups import pipeline


class _Conn:
    def __init__(self, rows): self._rows = rows
    async def fetch(self, *a, **k): return self._rows
    async def fetchval(self, *a, **k): return "running"
    async def execute(self, *a, **k): return "UPDATE 1"


class _Acquire:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return _Acquire(self._c)


class _Store:
    """Records the writes; the heartbeat is what the test is about."""
    def __init__(self, rows):
        self._pool = _Pool(_Conn(rows))
        self.facts = []
    async def ensure_schema(self): return None
    async def pool(self): return self._pool
    async def replace_facts(self, cid, src, facts, **k): self.facts.append((cid, facts))


def _rows(n):
    return [{"id": f"c{i}.com", "name": f"C{i}", "one_liner": "builds things",
             "description": "a company", "pricing": None, "home": None} for i in range(n)]


def _run(rows, answer, kind="business_model", beats=None):
    beats = [] if beats is None else beats
    store = _Store(rows)

    async def llm_json(system, user): return answer

    orig = pipeline._progress

    async def spy(st, jid, progress, status="running", error=""):
        beats.append(dict(progress))
        return await orig(st, jid, progress, status, error)

    pipeline._progress = spy
    try:
        fn = getattr(pipeline, f"run_{kind}")
        return asyncio.run(fn(store, pipeline.Providers(llm_json=llm_json), limit=len(rows),
                              max_usd=10.0, jid=1)), beats
    finally:
        pipeline._progress = orig


def test_a_pass_where_nothing_decides_still_beats():
    # the exact shape of the run that died: every company reads fine and decides nothing
    out, beats = _run(_rows(45), {"business_model": "unknown", "quote": "", "confident": False})
    assert out["of"] == 45 and out["decided"] == 0 and out["unknown"] == 45
    assert len(beats) >= 3, "a pass with no decisions wrote no heartbeat — the watchdog will kill it"


def test_a_pass_where_every_call_raises_still_beats():
    beats: list = []

    class _Boom(dict):
        pass

    async def boom(system, user): raise RuntimeError("provider down")

    store = _Store(_rows(45))
    orig = pipeline._progress

    async def spy(st, jid, progress, status="running", error=""):
        beats.append(dict(progress))
        return await orig(st, jid, progress, status, error)

    pipeline._progress = spy
    try:
        out = asyncio.run(pipeline.run_business_model(store, pipeline.Providers(llm_json=boom),
                                                      limit=45, max_usd=10.0, jid=1))
    finally:
        pipeline._progress = orig
    assert out["read"] == 0
    assert len(beats) >= 3, "a provider outage must not look like a dead thread"


def test_the_careers_pass_beats_when_no_page_lists_a_role():
    rows = [{"id": f"c{i}.com", "name": f"C{i}", "url": f"https://c{i}.com/careers",
             "text": "We are a team that values curiosity. " * 20} for i in range(45)]
    out, beats = _run(rows, {"roles": []}, kind="careers_roles")
    assert out["of"] == 45 and out["roles"] == 0
    assert len(beats) >= 3


def test_the_last_beat_records_the_whole_pass():
    out, beats = _run(_rows(45), {"business_model": "unknown", "quote": "", "confident": False})
    assert beats[-1]["done"] == 45 and beats[-1]["of"] == 45
