"""What a share must guarantee: it shows what the sender saw, and it is not guessable."""
from __future__ import annotations

from api import shares


def test_a_token_is_unguessable_and_unique():
    seen = {shares.new_token() for _ in range(500)}
    assert len(seen) == 500
    assert all(len(t) == 22 for t in seen)


def test_a_mode_must_be_one_we_render():
    import asyncio

    class FakeConn:
        async def execute(self, *a, **k):
            return "OK"

    for bad in ("", "email", "admin"):
        try:
            asyncio.run(shares.create(FakeConn(), mode=bad, title="t", query={}, payload={}))
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass


def test_an_oversized_page_is_refused_rather_than_truncated():
    import asyncio

    class FakeConn:
        async def execute(self, *a, **k):
            return "OK"

    big = {"moments": [{"text": "x" * 1000} for _ in range(1000)]}
    try:
        asyncio.run(shares.create(FakeConn(), mode="voices", title="t", query={}, payload=big))
        raise AssertionError("accepted an oversized payload")
    except ValueError as e:
        assert "narrow" in str(e)      # a share that quietly dropped half its results would lie
