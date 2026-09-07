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


def test_a_history_fingerprint_folds_a_repeated_search():
    from api import history
    a = history.fingerprint({"q": "pivot", "kinds": ["video"], "days": 7})
    b = history.fingerprint({"days": 7, "kinds": ["video"], "q": "pivot"})   # same search, keys reordered
    c = history.fingerprint({"q": "pivot", "kinds": ["podcast"], "days": 7})
    assert a == b and a != c


def test_history_is_only_kept_for_a_signed_in_account():
    import asyncio

    class FakeConn:
        def __init__(self): self.writes = 0
        async def execute(self, *a, **k):
            self.writes += 1
            return "OK"

    c = FakeConn()
    asyncio.run(history.record(c, "", mode="voices", title="t", query={"q": "x"}, hits=1))
    assert c.writes == 0        # anonymous searches are not logged to the server at all


from api import history  # noqa: E402
