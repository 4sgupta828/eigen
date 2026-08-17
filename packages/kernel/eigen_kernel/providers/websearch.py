"""Web-search provider port + deterministic fake.

Mechanism only — which sites/providers to curate is a vertical concern and is
supplied through the vertical contract, never hardcoded here.
"""
from __future__ import annotations

import re
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
    async def search(self, query: str, *, max_results: int = 10,
                     open_web: bool = False, recency_days: int | None = None) -> list[WebResult]: ...


def _norm_url(u: str) -> str:
    """Normalize a URL for cross-provider dedup: drop scheme, trailing slash, '#…', lowercase host."""
    u = (u or "").strip()
    u = re.sub(r"^https?://", "", u, flags=re.I).split("#", 1)[0].rstrip("/")
    return u.lower()


class CompositeWebSearch:
    """ADDITIVE web leg: fan out to several providers CONCURRENTLY and merge, deduping by URL. Each
    provider is best-effort (a failure/empty contributes nothing). Broadens coverage — e.g. Exa's
    whitelisted, credible results PLUS DuckDuckGo's open-web breadth — while the downstream tier
    classifier + span gate still grade + verify whatever is actually cited. Provider-major interleave
    so EVERY provider gets representation (breadth), not just the first one's list."""

    def __init__(self, clients: list):
        self._clients = [c for c in clients if c is not None]

    async def search(self, query: str, *, max_results: int = 10,
                     open_web: bool = False, recency_days: int | None = None) -> list[WebResult]:
        import asyncio
        lists = await asyncio.gather(
            *(c.search(query, max_results=max_results, open_web=open_web, recency_days=recency_days)
              for c in self._clients),
            return_exceptions=True)
        lists = [r for r in lists if isinstance(r, list)]
        out: list[WebResult] = []
        seen: set[str] = set()
        for rank in range(max((len(r) for r in lists), default=0)):
            for r in lists:
                if rank < len(r):
                    hit = r[rank]
                    key = _norm_url(hit.url)
                    if key and key not in seen:
                        seen.add(key)
                        out.append(hit)
        return out


class FakeWebSearch:
    """Offline web search returning canned results per query (tests)."""

    def __init__(self, canned: dict[str, list[WebResult]] | None = None):
        self._canned = canned or {}

    async def search(self, query: str, *, max_results: int = 10,
                     open_web: bool = False, recency_days: int | None = None) -> list[WebResult]:
        return self._canned.get(query, [])[:max_results]


class CassetteWebSearch:
    """Wrap an inner WebSearchClient with replay/record/live — free eval/CI."""

    def __init__(self, inner: WebSearchClient | None, *, cassette_root: Path,
                 namespace: str = "web", mode: ProviderMode | str | None = None):
        self._inner = inner
        self._mode = resolve_mode(mode)
        self._cassette = Cassette(root=cassette_root, namespace=namespace)

    async def search(self, query: str, *, max_results: int = 10,
                     open_web: bool = False, recency_days: int | None = None) -> list[WebResult]:
        # cassette KEY stays (query, max_results) so REPLAY tests are unaffected by the new live-only
        # web controls; the controls only shape live/record fetches (forwarded to the inner client).
        key = hash_request("web", query, max_results)
        if self._mode is ProviderMode.REPLAY:
            return [WebResult(**r) for r in self._cassette.replay(key, hint=query)]
        guard_live(self._mode)
        if self._inner is None:
            raise RuntimeError("CassetteWebSearch in record/live mode requires an inner client")
        results = await self._inner.search(query, max_results=max_results,
                                           open_web=open_web, recency_days=recency_days)
        if self._mode is ProviderMode.RECORD:
            self._cassette.record(key, [asdict(r) for r in results])
        return results
