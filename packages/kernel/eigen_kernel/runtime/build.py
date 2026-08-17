"""Build providers by mode, and discover the active vertical.

Providers are always cassette-wrapped: `replay` (default) runs offline for free;
`record`/`live` use the real Anthropic/OpenAI/Tavily backends. So the same code
path serves dev/CI/eval and production — credits are opt-in via EIGEN_PROVIDER_MODE.
"""
from __future__ import annotations

import os
from pathlib import Path

from eigen_kernel.providers.anthropic_llm import AnthropicLLM
from eigen_kernel.providers.base import ProviderMode, resolve_mode
from eigen_kernel.providers.embeddings import (
    OPENAI_EMBED_DIM,
    CassetteEmbedder,
    Embedder,
    OpenAIEmbedder,
)
from eigen_kernel.providers.llm import CassetteLLM, LLMClient
from eigen_kernel.providers.web_tavily import TavilyWebSearch
from eigen_kernel.providers.websearch import CassetteWebSearch, CompositeWebSearch, WebSearchClient


def default_cassette_root() -> Path:
    return Path(os.environ.get("EIGEN_CASSETTE_ROOT", "evals/cassettes"))


def build_llm(*, mode: ProviderMode | str | None = None, cassette_root: Path | None = None,
              model: str | None = None) -> LLMClient:
    m = resolve_mode(mode)
    inner = None if m is ProviderMode.REPLAY else AnthropicLLM(model=model) if model \
        else AnthropicLLM()
    return CassetteLLM(inner, cassette_root=cassette_root or default_cassette_root(),
                       namespace="llm", mode=m)


def build_embedder(*, mode: ProviderMode | str | None = None, cassette_root: Path | None = None,
                   dim: int = OPENAI_EMBED_DIM) -> Embedder:
    m = resolve_mode(mode)
    inner = None if m is ProviderMode.REPLAY else OpenAIEmbedder(dim=dim)
    return CassetteEmbedder(inner, cassette_root=cassette_root or default_cassette_root(),
                            namespace="embed", dim=dim, mode=m)


def build_web(*, mode: ProviderMode | str | None = None,
              cassette_root: Path | None = None,
              domains: tuple[str, ...] | list[str] | None = None,
              recent: bool = False) -> WebSearchClient:
    m = resolve_mode(mode)
    # Prefer Exa (neural search) when its key is set; else Tavily. Same WebSearchClient port.
    # `domains` (from the vertical) restricts Exa to a trusted-sources whitelist. `recent` (freshness
    # flag) biases the web leg to the last ~2 years so "latest state of the world" questions get
    # current news/pages, not the most-linked 2024-era write-ups (the corpus still holds the history).
    inner = None
    if m is not ProviderMode.REPLAY:
        def _exa():
            from eigen_kernel.providers.exa_web import ExaWebSearch
            _floor = ""
            if recent:
                import datetime
                # ~4-month floor: tight enough that Exa's candidate set is THIS quarter's releases,
                # so newest-first sorting surfaces the very latest models (not last spring's overview);
                # the corpus still holds the full history for non-"latest" questions.
                _floor = (datetime.date.today() - datetime.timedelta(days=120)).isoformat() + "T00:00:00.000Z"
            return ExaWebSearch(include_domains=list(domains or []), start_published_date=_floor)

        def _ddg():
            from eigen_kernel.providers.ddg_web import DuckDuckGoWebSearch
            return DuckDuckGoWebSearch()

        _has_exa, _has_tav = bool(os.environ.get("EXA_API_KEY")), bool(os.environ.get("TAVILY_API_KEY"))
        provider = os.environ.get("EIGEN_WEB_PROVIDER", "").strip().lower()
        if provider == "ddg":                                   # forced single provider (override)
            inner = _ddg()
        elif provider == "exa" and _has_exa:
            inner = _exa()
        elif provider == "tavily" and _has_tav:
            inner = TavilyWebSearch(time_range="year" if recent else "")
        else:
            # DEFAULT = ADDITIVE: the best keyed provider (credible, whitelisted) PLUS the keyless
            # DuckDuckGo (open-web breadth), fanned out concurrently + merged. Downstream tier-grading
            # + span-verification decide what's actually cited, so credible sources still lead while
            # DDG adds reach. With NO paid key, DDG alone runs the web leg (free).
            clients = []
            if _has_exa:
                clients.append(_exa())
            elif _has_tav:
                clients.append(TavilyWebSearch(time_range="year" if recent else ""))
            clients.append(_ddg())
            inner = clients[0] if len(clients) == 1 else CompositeWebSearch(clients)
    return CassetteWebSearch(inner, cassette_root=cassette_root or default_cassette_root(),
                             namespace="web", mode=m)


def load_active_vertical(name: str | None = None):
    """Discover installed verticals via the `eigen.verticals` entry point and
    return the one named by EIGEN_ACTIVE_VERTICAL (single-vertical-per-deployment)."""
    from importlib.metadata import entry_points

    want = name or os.environ.get("EIGEN_ACTIVE_VERTICAL")
    eps = list(entry_points(group="eigen.verticals"))
    if not eps:
        raise RuntimeError("no eigen.verticals installed")
    ep = next((e for e in eps if e.name == want), None) if want else eps[0]
    if ep is None:
        raise RuntimeError(f"active vertical {want!r} not found (have: {[e.name for e in eps]})")
    return ep.load()
