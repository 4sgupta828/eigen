"""Web-search provider port + deterministic fake.

Mechanism only — which sites/providers to curate is a vertical concern and is
supplied through the vertical contract, never hardcoded here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .base import ProviderMode, guard_live, resolve_mode
from .cassette import Cassette, hash_request


@dataclass
class WebResult:
    url: str
    title: str
    snippet: str
    body: str | None = None
    published: str | None = None       # ISO-ish publish date when the provider reports one
    highlights: tuple[str, ...] = ()   # query-aware extracts (Exa) — spans from ANYWHERE in the page


@runtime_checkable
class WebSearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 10) -> list[WebResult]: ...


class FakeWebSearch:
    """Offline web search returning canned results per query (tests)."""

    def __init__(self, canned: dict[str, list[WebResult]] | None = None):
        self._canned = canned or {}

    async def search(self, query: str, *, max_results: int = 10) -> list[WebResult]:
        return self._canned.get(query, [])[:max_results]


class CassetteWebSearch:
    """Wrap an inner WebSearchClient with replay/record/live — free eval/CI."""

    def __init__(self, inner: WebSearchClient | None, *, cassette_root: Path,
                 namespace: str = "web", mode: ProviderMode | str | None = None):
        self._inner = inner
        self._mode = resolve_mode(mode)
        self._cassette = Cassette(root=cassette_root, namespace=namespace)

    async def search(self, query: str, *, max_results: int = 10) -> list[WebResult]:
        key = hash_request("web", query, max_results)
        if self._mode is ProviderMode.REPLAY:
            return [WebResult(**r) for r in self._cassette.replay(key, hint=query)]
        guard_live(self._mode)
        if self._inner is None:
            raise RuntimeError("CassetteWebSearch in record/live mode requires an inner client")
        results = await self._inner.search(query, max_results=max_results)
        if self._mode is ProviderMode.RECORD:
            self._cassette.record(key, [asdict(r) for r in results])
        return results
