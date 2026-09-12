from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from api.thesis import store


class FakeConn:
    def __init__(self, thesis: dict | None = None):
        self.thesis = thesis
        self.queries: list[tuple[str, tuple]] = []
        self.runs: dict[tuple[str, str], dict] = {}

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, query: str, *args):
        self.queries.append((query, args))
        if "UPDATE ts_run SET state='failed'" in query:
            row = next((r for r in self.runs.values()
                        if r["thesis_id"] == args[0] and r["id"] == args[1]), None)
            if row:
                row.update({"state": "failed", "stage": args[2], "error": args[3]})
        return "OK"

    async def fetchrow(self, query: str, *args):
        self.queries.append((query, args))
        if "FROM ts_thesis" in query:
            if not self.thesis:
                return None
            if "share_token = $1" in query and self.thesis.get("share_token") != args[0]:
                return None
            return self.thesis
        if "FROM ts_run" in query and "idempotency_key" in query:
            return self.runs.get((args[0], args[1]))
        if "FROM ts_run" in query and "state IN" in query:
            return next((r for r in self.runs.values()
                         if r["thesis_id"] == args[0] and r["state"] in ("approved", "running")), None)
        if "FROM ts_run" in query and "id = $2" in query:
            return next((r for r in self.runs.values()
                         if r["thesis_id"] == args[0] and r["id"] == args[1]), None)
        if "INSERT INTO ts_run" in query:
            row = {"id": args[0], "thesis_id": args[1], "idempotency_key": args[2],
                   "state": "approved", "stage": "approved", "projected_usd": args[3],
                   "approved_usd": args[4], "actual_usd": 0.0, "metadata": args[5],
                   "error": {}}
            self.runs[(args[1], args[2])] = row
            return row
        if "UPDATE ts_run" in query and "actual_usd=actual_usd+$5" in query:
            row = next((r for r in self.runs.values()
                        if r["thesis_id"] == args[0] and r["id"] == args[1]), None)
            if not row or row["actual_usd"] + args[4] > row["approved_usd"]:
                return None
            row.update({"stage": args[2], "state": args[3],
                        "actual_usd": row["actual_usd"] + args[4]})
            return row
        if "UPDATE ts_thesis SET share_token=$2" in query:
            if self.thesis and self.thesis["id"] == args[0]:
                self.thesis["share_token"] = args[1]
                return {"share_token": args[1]}
            return None
        return None

    async def fetch(self, query: str, *args):
        self.queries.append((query, args))
        if "FROM ts_claim" in query or "FROM ts_evidence" in query or "FROM ts_turn" in query:
            return []
        return []


class FakePool:
    def __init__(self, thesis: dict | None = None):
        self.conn = FakeConn(thesis)

    def acquire(self):
        return self.conn


def _thesis(*, owner_id: str = "owner-1", owner_token_hash: str = "") -> dict:
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    return {"id": "t1", "owner_id": owner_id, "owner_token_hash": owner_token_hash,
            "title": "A thesis", "thesis": "A sufficiently long thesis sentence.", "subject": {},
            "share_token": "share-secret", "revision": 0, "focus_rung": "", "overall": "",
            "decision": {}, "research_status": "not_run", "created_at": now, "updated_at": now}


@pytest.mark.asyncio
async def test_authenticated_owner_can_read_but_wrong_or_missing_owner_cannot() -> None:
    pool = FakePool(_thesis())

    assert (await store.get(pool, thesis_id="t1", owner_id="owner-1"))["is_owner"] is True
    assert await store.get(pool, thesis_id="t1", owner_id="owner-2") is None
    assert await store.get(pool, thesis_id="t1") is None


@pytest.mark.asyncio
async def test_anonymous_owner_requires_matching_capability() -> None:
    pool = FakePool(_thesis(owner_id="", owner_token_hash=store.hash_owner_token("capability")))

    assert (await store.get(pool, thesis_id="t1", owner_token="capability"))["is_owner"] is True
    assert await store.get(pool, thesis_id="t1", owner_token="wrong") is None


@pytest.mark.asyncio
async def test_share_token_is_read_only_and_secrets_are_stripped() -> None:
    pool = FakePool(_thesis())

    shared = await store.get(pool, thesis_id="t1", share_token="share-secret")

    assert shared["is_owner"] is False
    assert "share_token" not in shared
    assert "owner_token_hash" not in shared


@pytest.mark.asyncio
async def test_empty_owner_recent_returns_nothing_without_querying_rows() -> None:
    pool = FakePool(_thesis(owner_id=""))

    assert await store.recent(pool, owner_id="") == []
    assert not any("GROUP BY t.id" in query for query, _args in pool.conn.queries)


@pytest.mark.asyncio
async def test_recent_query_is_strictly_owner_scoped() -> None:
    pool = FakePool()

    assert await store.recent(pool, owner_id="owner-1") == []
    query, args = next((q, a) for q, a in pool.conn.queries if "GROUP BY t.id" in q)
    assert "t.owner_id = $1" in query
    assert "$1 = ''" not in query
    assert args[0] == "owner-1"


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_same_research_run() -> None:
    pool = FakePool()

    first = await store.create_run(pool, thesis_id="t1", idempotency_key="request-1",
                                   projected_usd=0.021, approved_usd=0.03,
                                   metadata={"claims": 4})
    second = await store.create_run(pool, thesis_id="t1", idempotency_key="request-1",
                                    projected_usd=0.021, approved_usd=0.03,
                                    metadata={"claims": 4})

    assert first["id"] == second["id"]
    assert len(pool.conn.runs) == 1


@pytest.mark.asyncio
async def test_second_active_run_is_rejected() -> None:
    pool = FakePool()
    await store.create_run(pool, thesis_id="t1", idempotency_key="request-1",
                           projected_usd=0.02, approved_usd=0.03, metadata={})

    with pytest.raises(store.ActiveRunError):
        await store.create_run(pool, thesis_id="t1", idempotency_key="request-2",
                               projected_usd=0.02, approved_usd=0.03, metadata={})


@pytest.mark.asyncio
async def test_anonymous_creation_returns_capability_but_stores_only_hash() -> None:
    pool = FakePool()

    created = await store.create(pool, thesis="A sufficiently long thesis sentence.", claims=[],
                                 subject={}, owner_id="")

    assert created["owner_token"]
    assert "share_token" not in created
    query, args = next((q, a) for q, a in pool.conn.queries if "INSERT INTO ts_thesis" in q)
    assert "owner_token_hash" in query
    assert created["owner_token"] not in args
    assert store.hash_owner_token(created["owner_token"]) in args


@pytest.mark.asyncio
async def test_evidence_write_keeps_stable_identity_and_is_idempotent() -> None:
    pool = FakePool()
    row = {"id": "ev-stable", "side": "for", "relation": "supports", "register": "filed",
           "source_key": "edgar", "quote": "A direct result.", "document_id": "doc-1",
           "block_id": "block-2", "source_subject": "Entity A",
           "evidence_kind": "measured_result", "period": "2026-Q2",
           "span_hash": "a" * 64, "gate_results": {"span_ok": True},
           "facets": {"issuer": "Entity A"}, "run_id": "run-1"}

    assert await store.add_evidence(pool, "t1", "problem_exists", [row]) == 1
    query, args = next((q, a) for q, a in pool.conn.queries if "INSERT INTO ts_evidence" in q)
    assert "document_id" in query and "gate_results" in query and "ON CONFLICT" in query
    assert args[0] == "ev-stable"
    assert "doc-1" in args and "block-2" in args and "run-1" in args
    placeholders = [int(n) for n in re.findall(r"\$(\d+)", query)]
    assert max(placeholders) == len(args)


@pytest.mark.asyncio
async def test_run_progress_cannot_exceed_approved_cost() -> None:
    pool = FakePool()
    run = await store.create_run(pool, thesis_id="t1", idempotency_key="request-1",
                                 projected_usd=0.02, approved_usd=0.02, metadata={})

    advanced = await store.advance_run(pool, thesis_id="t1", run_id=run["id"],
                                       stage="binding", actual_delta=0.015)
    assert advanced["actual_usd"] == 0.015
    with pytest.raises(store.SpendCapError):
        await store.advance_run(pool, thesis_id="t1", run_id=run["id"],
                                stage="synthesis", actual_delta=0.006)


@pytest.mark.asyncio
async def test_run_can_be_loaded_and_failed_with_structured_error() -> None:
    pool = FakePool()
    run = await store.create_run(pool, thesis_id="t1", idempotency_key="request-1",
                                 projected_usd=0.02, approved_usd=0.02, metadata={})

    assert (await store.get_run(pool, thesis_id="t1", run_id=run["id"]))["state"] == "approved"
    await store.fail_run(pool, thesis_id="t1", run_id=run["id"], stage="retrieval",
                         error={"code": "corpus_unavailable"})
    failed = await store.get_run(pool, thesis_id="t1", run_id=run["id"])
    assert failed["state"] == "failed"
    assert failed["error"] == {"code": "corpus_unavailable"}


@pytest.mark.asyncio
async def test_decision_write_keeps_research_state_separate() -> None:
    pool = FakePool()

    await store.set_decision(pool, "t1", {"recommendation": "continue_diligence"},
                             research_status="completed")

    query, args = next((q, a) for q, a in pool.conn.queries if "UPDATE ts_thesis SET decision" in q)
    assert "research_status=$3" in query
    assert args[2] == "completed"


@pytest.mark.asyncio
async def test_share_issue_and_revoke_rotate_the_read_only_capability() -> None:
    pool = FakePool(_thesis())

    issued = await store.issue_share(pool, "t1")
    assert issued and issued != "share-secret"
    await store.revoke_share(pool, "t1")

    assert pool.conn.thesis["share_token"] != issued


@pytest.mark.asyncio
async def test_revising_claim_invalidates_old_evidence_and_decision_state() -> None:
    pool = FakePool()

    await store.revise_claim(pool, "t1", "problem_exists", "A materially revised claim.")

    updates = [(q, a) for q, a in pool.conn.queries if "UPDATE ts_claim" in q]
    deletes = [(q, a) for q, a in pool.conn.queries if "DELETE FROM ts_evidence" in q]
    assert len(updates) == 1 and "research_status = 'open'" in updates[0][0]
    assert len(deletes) == 1
    assert updates[0][1][:2] == ("t1", "problem_exists")
