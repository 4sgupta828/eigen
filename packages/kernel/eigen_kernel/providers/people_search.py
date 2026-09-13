"""People-search provider port + deterministic fake.

Mechanism only — the kernel discovers PEOPLE matching a natural-language expertise query and returns
normalized results. It names no domain noun: what an "expert", a "buyer", or a "role" is, how to phrase
the query, and how to rank credibility are all the vertical's concern, supplied through the manifest.

Mirrors `websearch.py` exactly (DTO, Protocol, Composite, Fake, Cassette) so a people leg gets the same
replay/record/live discipline and free CI. Results are PUBLIC professional signal (profile URLs), never
re-hosted scraped content — the legal posture lives in how the vertical/app use these, not here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .base import ProviderMode, guard_live, resolve_mode
from .cassette import Cassette, hash_request


@dataclass
class PersonResult:
    name: str
    profile_url: str                       # the public profile the reader can open (source, not re-host)
    headline: str = ""                     # the one-line role/description the provider returned
    org: str = ""                          # current organization, when known
    roles: tuple[str, ...] = ()            # current/past titles, when the provider exposes them
    expertise: tuple[str, ...] = ()        # skills/topics, when exposed
    location: str = ""
    relevance: float = 0.0                 # provider-reported match score (0..1), when given
    provider: str = ""                     # which engine surfaced this (exa/pdl/…)
    providers: tuple[str, ...] = ()        # ALL engines that returned this person (set by the composite)


@runtime_checkable
class PeopleSearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]: ...


def _norm_url(u: str) -> str:
    """Normalize a profile URL for cross-provider dedup: drop scheme, trailing slash, '#…', lowercase."""
    import re
    u = (u or "").strip()
    u = re.sub(r"^https?://", "", u, flags=re.I).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return u.lower()


class CompositePeopleSearch:
    """Fan out to several people providers CONCURRENTLY and merge, deduping by profile URL. Each provider
    is best-effort (a failure/empty contributes nothing). Provider-major interleave so every provider
    gets representation; a person returned by MULTIPLE engines bubbles up (cross-engine agreement)."""

    def __init__(self, clients: list, *, prominence_sort: bool = True):
        self._clients = [c for c in clients if c is not None]
        self._prominence_sort = bool(prominence_sort)

    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]:
        import asyncio
        lists = await asyncio.gather(
            *(c.search(query, max_results=max_results, filters=filters) for c in self._clients),
            return_exceptions=True)
        lists = [r for r in lists if isinstance(r, list)]
        prov_by_url: dict[str, set] = {}
        for lst in lists:
            for hit in lst:
                k = _norm_url(hit.profile_url) or hit.name.lower()
                if k and getattr(hit, "provider", ""):
                    prov_by_url.setdefault(k, set()).add(hit.provider)
        out: list[PersonResult] = []
        seen: set[str] = set()
        for rank in range(max((len(r) for r in lists), default=0)):
            for r in lists:
                if rank < len(r):
                    hit = r[rank]
                    key = _norm_url(hit.profile_url) or hit.name.lower()
                    if key and key not in seen:
                        seen.add(key)
                        provs = prov_by_url.get(key) or ({hit.provider} if hit.provider else set())
                        hit.providers = tuple(sorted(provs))
                        out.append(hit)
        if self._prominence_sort:
            out.sort(key=lambda h: len(getattr(h, "providers", ()) or ()), reverse=True)
        return out


class FakePeopleSearch:
    """Offline people search returning canned results per query (tests)."""

    def __init__(self, canned: dict[str, list[PersonResult]] | None = None):
        self._canned = canned or {}

    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]:
        return self._canned.get(query, [])[:max_results]


class CassettePeopleSearch:
    """Wrap an inner PeopleSearchClient with replay/record/live — free eval/CI, no live spend on replay."""

    def __init__(self, inner: PeopleSearchClient | None, *, cassette_root: Path,
                 namespace: str = "people", mode: ProviderMode | str | None = None):
        self._inner = inner
        self._mode = resolve_mode(mode)
        self._cassette = Cassette(root=cassette_root, namespace=namespace)

    async def search(self, query: str, *, max_results: int = 8,
                     filters: dict | None = None) -> list[PersonResult]:
        key = hash_request("people", query, max_results)
        if self._mode is ProviderMode.REPLAY:
            return [PersonResult(**r) for r in self._cassette.replay(key, hint=query)]
        guard_live(self._mode)
        if self._inner is None:
            raise RuntimeError("CassettePeopleSearch in record/live mode requires an inner client")
        results = await self._inner.search(query, max_results=max_results, filters=filters)
        if self._mode is ProviderMode.RECORD:
            self._cassette.record(key, [asdict(r) for r in results])
        return results
