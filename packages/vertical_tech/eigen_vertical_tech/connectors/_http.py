"""Shared fetch strategy for tech connectors: plain datacenter HTTP, no proxy.

All Tier-1 tech sources (SEC EDGAR, arXiv, OpenAlex, GitHub, …) are public APIs served over
ordinary HTTPS with a fair-use User-Agent requirement — no anti-bot choreography needed.
"""
from __future__ import annotations

# SEC and several APIs require a descriptive User-Agent; keep one canonical string.
USER_AGENT = "eigen-research/0.0 (contact: research@eigen.example)"


class HttpStrategy:
    egress_class = "datacenter"
    engine = "http"
    proxy_enabled = False

    async def fetch(self, url: str, **opts) -> bytes:  # noqa: ANN003
        import httpx
        headers = {"User-Agent": USER_AGENT, **(opts.get("headers") or {})}
        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content
