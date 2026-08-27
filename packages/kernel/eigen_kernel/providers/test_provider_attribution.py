"""CompositeWebSearch provider attribution: each merged hit records EVERY engine that returned its URL
(single engine ⇒ novel to it), so downstream can attribute cited evidence per search source."""
import asyncio

from eigen_kernel.providers.websearch import CompositeWebSearch, WebResult


class _Stub:
    def __init__(self, results):
        self._r = results
    async def search(self, query, *, max_results=10, open_web=False, recency_days=None, max_chars=None):
        return list(self._r)


def test_composite_tags_providers_per_url():
    exa = _Stub([WebResult(url="https://a.com/x", title="A", snippet="", provider="exa"),
                 WebResult(url="https://shared.com/y", title="S", snippet="", provider="exa")])
    brave = _Stub([WebResult(url="https://b.com/z", title="B", snippet="", provider="brave"),
                   WebResult(url="https://shared.com/y", title="S", snippet="", provider="brave")])
    out = asyncio.run(CompositeWebSearch([exa, brave]).search("q"))
    by_url = {r.url: r for r in out}
    # a.com only from exa → novel to exa
    assert by_url["https://a.com/x"].providers == ("exa",)
    # b.com only from brave → novel to brave
    assert by_url["https://b.com/z"].providers == ("brave",)
    # shared.com returned by BOTH → not novel to either
    assert set(by_url["https://shared.com/y"].providers) == {"brave", "exa"}
    assert len(out) == 3          # deduped by url


def test_single_provider_hit_is_novel():
    exa = _Stub([WebResult(url="https://only.com/1", title="O", snippet="", provider="exa")])
    out = asyncio.run(CompositeWebSearch([exa]).search("q"))
    assert out[0].providers == ("exa",)
