"""Bounded additive deep web retrieval for one resolved entity.

The kernel owns only mechanics here: resolve a canonical domain, expand caller-supplied
templates, run bounded web searches, and return normal BlockHits from the supplied
RetrievalSource. All vocabulary and attribution guidance lives in the vertical.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import replace
from typing import Any, Mapping
from urllib.parse import urlparse

from pydantic import BaseModel

from eigen_kernel.contract.dto import BlockHit, RetrievalRequest
from eigen_kernel.contract.protocols import RetrievalSource

_log = logging.getLogger(__name__)

_DEFAULT_MAX_QUERIES = 8
_DEFAULT_MAX_PAGES = 18
_DEFAULT_DEADLINE_S = 25.0
_DEFAULT_MAX_RESULTS_PER_QUERY = 3
_DEFAULT_MAX_CHARS = 12000
_DEFAULT_MAX_CHUNKS_PER_PAGE = 5
_DOMAIN_RESULTS = 5


class _DomainChoice(BaseModel):
    domain: str = ""


def _host(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _clean_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = _host(value)
    value = value.split("/", 1)[0].strip(".")
    if value.startswith("www."):
        value = value[4:]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", value):
        return ""
    return value


def _render(template: str, *, company: str, domain: str) -> str:
    try:
        return template.format(company=company, domain=domain)
    except Exception:
        return template.replace("<company>", company).replace("<domain>", domain)


def _template_items(templates: Mapping[str, Any], key: str) -> list[tuple[str, str]]:
    raw = templates.get(key) or {}
    if isinstance(raw, Mapping):
        return [(str(k), str(v)) for k, v in raw.items() if str(v).strip()]
    if isinstance(raw, (list, tuple)):
        return [(str(i), str(v)) for i, v in enumerate(raw) if str(v).strip()]
    return []


async def _choose_domain(
    company: str,
    hits: list[BlockHit],
    *,
    llm=None,
    prompt: str = "",
    budget=None,
) -> str:
    candidates = []
    seen: set[str] = set()
    for h in hits:
        d = _host(h.document_id)
        if d and d not in seen:
            seen.add(d)
            candidates.append((d, h.document_title or h.document_id))
    if not candidates:
        return ""
    if llm is not None and prompt.strip() and not getattr(budget, "exhausted", False):
        try:
            body = "\n".join(f"- {d}: {title}" for d, title in candidates[:_DOMAIN_RESULTS])
            res = await llm.complete(
                system=prompt,
                messages=[{"role": "user", "content": f"ENTITY: {company}\nCANDIDATES:\n{body}"}],
                response_format=_DomainChoice,
                max_tokens=200,
            )
            if budget is not None:
                budget.charge(calls=1, tokens=getattr(res, "output_tokens", 0))
            picked = _clean_domain(getattr(res.parsed, "domain", ""))
            if picked in {d for d, _ in candidates}:
                return picked
        except Exception as e:  # noqa: BLE001
            _log.warning("deep-company domain LLM resolution failed: %r", e)
    return candidates[0][0]


async def retrieve_deep_company(
    *,
    company: str,
    templates: Mapping[str, Any],
    source: RetrievalSource,
    tenant_id: str,
    workspace_id: str | None = None,
    llm=None,
    budget=None,
) -> list[BlockHit]:
    """Return additive, span-grounded web blocks for one entity.

    Any error or timeout returns [] so the normal answer path proceeds unchanged.
    """

    async def _run() -> list[BlockHit]:
        company_s = (company or "").strip()
        if not company_s or source is None or not templates:
            return []
        max_queries = max(1, int(templates.get("max_queries") or _DEFAULT_MAX_QUERIES))
        max_pages = max(1, int(templates.get("max_pages") or _DEFAULT_MAX_PAGES))
        max_results = max(
            1, int(templates.get("max_results_per_query") or _DEFAULT_MAX_RESULTS_PER_QUERY))
        max_chars = max(1000, int(templates.get("max_chars") or _DEFAULT_MAX_CHARS))
        max_chunks = max(
            1, int(templates.get("max_chunks_per_page") or _DEFAULT_MAX_CHUNKS_PER_PAGE))
        concurrency = max(1, int(templates.get("concurrency") or 3))

        domain_query_t = str(templates.get("domain_query_template") or "{company} official website")
        domain_query = _render(domain_query_t, company=company_s, domain="")
        domain_hits = await source.search(RetrievalRequest(
            query=domain_query, tenant_id=tenant_id, workspace_id=workspace_id,
            k=_DOMAIN_RESULTS, web_open=True, web_max_results=_DOMAIN_RESULTS,
            web_max_chars=2000, web_max_chunks_per_page=1,
            web_extra_facets={"source_kind": "corp_eng", "web_role": "official"}))
        domain = await _choose_domain(
            company_s, domain_hits, llm=llm,
            prompt=str(templates.get("domain_prompt") or ""),
            budget=budget)
        if not domain:
            return []

        query_specs: list[tuple[str, str, dict]] = []
        for facet, template in _template_items(templates, "internal"):
            q = "site:" + domain + " " + _render(template, company=company_s, domain=domain)
            query_specs.append((facet, q, {"source_kind": "corp_eng", "web_role": "official"}))
        for facet, template in _template_items(templates, "external"):
            q = _render(template, company=company_s, domain=domain)
            query_specs.append(
                (facet, q, {"source_kind": "news", "web_role": "independent_analysis"}))
        query_specs = query_specs[:max_queries]
        if not query_specs:
            return []

        sem = asyncio.Semaphore(concurrency)

        async def _fetch(facet: str, query: str, stamp: dict) -> list[BlockHit]:
            async with sem:
                req = RetrievalRequest(
                    query=query, tenant_id=tenant_id, workspace_id=workspace_id,
                    k=max_results * max_chunks, web_open=True,
                    web_max_results=max_results, web_max_chars=max_chars,
                    web_max_chunks_per_page=max_chunks,
                    web_extra_facets={**stamp, "deep_facet": facet},
                )
                return await source.search(req)

        batches = await asyncio.gather(*(_fetch(*spec) for spec in query_specs))
        out: list[BlockHit] = []
        seen_pages: set[str] = set()
        for batch in batches:
            for h in batch:
                if h.document_id not in seen_pages:
                    if len(seen_pages) >= max_pages:
                        continue
                    seen_pages.add(h.document_id)
                out.append(replace(h, legs=tuple([*(getattr(h, "legs", ()) or ()), "web:deep"])))
        return out

    try:
        deadline = float(templates.get("deadline_s") or _DEFAULT_DEADLINE_S)
        return await asyncio.wait_for(_run(), timeout=max(1.0, deadline))
    except Exception as e:  # noqa: BLE001
        _log.warning("deep-company retrieval failed: %r", e)
        return []
