"""Admin job running, generic over the module that owns the jobs table.

Startup Search grew a job runner — insert a row, run the work on a daemon thread with its own pool, report
progress, honour a cancel, mark the survivors orphaned after a restart — and it is bound to `su_job` and
`StartupStore` in every line (`api/startups/pipeline.py:63-90`, `:897-927`). Investor Search needs the same
contract. Two copies of a cancel/heartbeat protocol drift; this is the one copy, parameterised on the table name
and a store factory.

`api/startups/pipeline.py` is NOT yet ported onto this module. That port is a mechanical change to a module with
live ingest running against it, and it buys nothing until it is done deliberately with its own test run — so it
is a tracked follow-up, and until then `test_job_heartbeat.py` covers the startup copy and `test_jobs.py` covers
this one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import traceback

_log = logging.getLogger(__name__)

ORPHAN_NOTE = ("the API process restarted while this job ran; re-launch it "
               "(jobs resume where they left off)")


class JobCancelled(Exception):
    """Raised inside a job when its row was set to 'cancelling' by the operator."""


class Jobs:
    """The job contract over one table. `store` supplies `pool()` and `ensure_schema()`."""

    def __init__(self, table: str, *, thread_prefix: str = "jobs"):
        self.table = table
        self.thread_prefix = thread_prefix

    async def create(self, store, kind: str, params: dict) -> int:
        pool = await store.pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval(
                f"INSERT INTO {self.table} (kind, params, status) VALUES ($1, $2::jsonb, 'running') RETURNING id",
                kind, json.dumps(params)))

    async def progress(self, store, jid: int, progress: dict, status: str = "running", error: str = "") -> None:
        """Record progress, and stop the job here when a cancel was asked for.

        Every long loop reports progress, which is what makes cancellation possible at all: there is no way to
        interrupt a thread from outside, so the job has to come back and ask.
        """
        pool = await store.pool()
        async with pool.acquire() as conn:
            cur = await conn.fetchval(f"SELECT status FROM {self.table} WHERE id = $1", jid)
            if cur == "cancelling" and status == "running":
                await conn.execute(
                    f"UPDATE {self.table} SET progress = $2::jsonb, status = 'cancelled', updated_at = now() WHERE id = $1",
                    jid, json.dumps(progress))
                raise JobCancelled(jid)
            await conn.execute(
                f"UPDATE {self.table} SET progress = $2::jsonb, status = $3, error = $4, updated_at = now() WHERE id = $1",
                jid, json.dumps(progress), status, error[:2000])

    async def orphan_running(self, store) -> int:
        """After a restart a 'running' row is a zombie — the thread died with the process. Called at startup."""
        await store.ensure_schema()
        pool = await store.pool()
        async with pool.acquire() as conn:
            n = await conn.execute(
                f"UPDATE {self.table} SET status = 'orphaned', error = $1, updated_at = now() "
                f"WHERE status IN ('running', 'cancelling')", ORPHAN_NOTE)
        return int(n.split()[-1]) if n else 0

    async def cancel(self, store, jid: int) -> bool:
        pool = await store.pool()
        async with pool.acquire() as conn:
            n = await conn.execute(
                f"UPDATE {self.table} SET status = 'cancelling', updated_at = now() "
                f"WHERE id = $1 AND status = 'running'", jid)
        return bool(n and n.split()[-1] != "0")

    async def recent(self, store, limit: int = 12) -> list[dict]:
        """The job list, with the stale watchdog applied first: a job whose thread died without a restart (an
        unhandled exit, an OOM) leaves a 'running' row that no startup hook will ever see."""
        await store.ensure_schema()
        pool = await store.pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {self.table} SET status = 'orphaned', error = $1 "
                f"WHERE status IN ('running','cancelling') AND updated_at < now() - interval '30 minutes'",
                ORPHAN_NOTE)
            rows = await conn.fetch(
                f"SELECT id, kind, params, status, progress, error, created_at, updated_at "
                f"FROM {self.table} ORDER BY id DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    def start(self, store, dsn: str, kind: str, params: dict, *, runners: dict, store_factory,
              needs_prov: set | None = None, providers=None, provider_factory=None):
        """Insert the row on the caller's loop (so the caller gets an id), then run on a daemon thread.

        Returns an awaitable of the job id. The thread gets its OWN pool and its own store: the caller's pool
        belongs to the request loop and must not cross a thread boundary.
        """
        async def _go() -> int:
            import asyncpg
            await store.ensure_schema()
            jid = await self.create(store, kind, params)

            async def _ret(p):
                return p

            def _run() -> None:
                async def main():
                    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                    tstore = store_factory(lambda: _ret(pool))
                    try:
                        fn = runners[kind]
                        kw = dict(params)
                        kw["jid"] = jid
                        if needs_prov and kind in needs_prov:
                            prov = providers if providers is not None else (provider_factory() if provider_factory else None)
                            out = await fn(tstore, prov, **kw)          # NEEDS_PROV jobs take providers POSITIONALLY
                        else:
                            out = await fn(tstore, **kw)
                        await self.progress(tstore, jid, out or {}, status="done")
                    except JobCancelled:
                        _log.info("%s job %s (%s) cancelled", self.thread_prefix, kind, jid)
                    except Exception as e:      # noqa: BLE001 — a failed job is a recorded row, never a dead API
                        _log.exception("%s job %s failed", self.thread_prefix, kind)
                        await self.progress(tstore, jid, {}, status="failed",
                                            error=f"{e}\n{traceback.format_exc()[-1500:]}")
                    finally:
                        await pool.close()
                asyncio.run(main())

            threading.Thread(target=_run, daemon=True, name=f"{self.thread_prefix}-{kind}-{jid}").start()
            return jid
        return _go()
