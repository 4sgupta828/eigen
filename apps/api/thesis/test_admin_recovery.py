from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api.thesis import store


class RecConn:
    """A minimal fake connection that records queries and serves scripted fetch results, so the new
    admin/delete/adopt store functions can be exercised without a real Postgres."""
    def __init__(self, *, thesis_exists: bool = True, rows: list | None = None):
        self.thesis_exists = thesis_exists
        self.rows = rows or []
        self.queries: list[tuple[str, tuple]] = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def execute(self, query: str, *args):
        self.queries.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args):
        self.queries.append((query, args))
        if "RETURNING id" in query:
            return {"id": args[0]} if self.thesis_exists else None
        return None

    async def fetch(self, query: str, *args):
        self.queries.append((query, args))
        return self.rows


class RecPool:
    def __init__(self, conn: RecConn):
        self.conn = conn

    def acquire(self):
        return self.conn


@pytest.mark.asyncio
async def test_delete_thesis_unpublishes_board_then_deletes(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    conn = RecConn(thesis_exists=True)
    ok = await store.delete_thesis(RecPool(conn), "t1")
    assert ok is True
    joined = " || ".join(q for q, _ in conn.queries)
    assert "DELETE FROM ts_board WHERE thesis_id" in joined
    assert "DELETE FROM ts_thesis WHERE id" in joined
    # board must be cleared BEFORE the thesis row (no orphaned public entry mid-delete)
    board_i = next(i for i, (q, _) in enumerate(conn.queries) if "DELETE FROM ts_board" in q)
    thesis_i = next(i for i, (q, _) in enumerate(conn.queries) if "DELETE FROM ts_thesis" in q)
    assert board_i < thesis_i


@pytest.mark.asyncio
async def test_delete_missing_thesis_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    assert await store.delete_thesis(RecPool(RecConn(thesis_exists=False)), "nope") is False


@pytest.mark.asyncio
async def test_adopt_mints_a_token_whose_hash_is_stored(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    conn = RecConn(thesis_exists=True)
    token = await store.adopt_thesis(RecPool(conn), "t1")
    assert token
    upd = next((q, a) for q, a in conn.queries if "UPDATE ts_thesis SET owner_token_hash" in q)
    # the stored hash must be the hash of the returned token, and the returned token itself never stored
    assert upd[1][1] == store.hash_owner_token(token)
    assert token not in upd[1]


@pytest.mark.asyncio
async def test_adopt_missing_thesis_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    assert await store.adopt_thesis(RecPool(RecConn(thesis_exists=False)), "nope") is None


@pytest.mark.asyncio
async def test_claim_binds_owner_id_and_clears_capability(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    conn = RecConn(thesis_exists=True)
    ok = await store.claim_thesis_to_account(RecPool(conn), "t1", "acct-42")
    assert ok is True
    upd = next((q, a) for q, a in conn.queries if "UPDATE ts_thesis SET owner_id" in q)
    assert "owner_token_hash = ''" in upd[0]          # capability token dropped — account owns it now
    assert upd[1] == ("t1", "acct-42")


@pytest.mark.asyncio
async def test_claim_requires_an_account(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    assert await store.claim_thesis_to_account(RecPool(RecConn(thesis_exists=True)), "t1", "") is False


@pytest.mark.asyncio
async def test_all_theses_maps_rows_with_board_flag(monkeypatch) -> None:
    monkeypatch.setattr(store, "ensure_schema", _noop)
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    rows = [{"id": "t1", "title": "T", "thesis": "sentence", "on_board": True,
             "settled": 2, "claims": 5, "updated_at": now}]
    out = await store.all_theses(RecPool(RecConn(rows=rows)))
    assert out == [{"id": "t1", "title": "T", "thesis": "sentence", "on_board": True,
                    "settled": 2, "claims": 5, "updated_at": now.isoformat()}]


async def _noop(*_a, **_k):
    return None
