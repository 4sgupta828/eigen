"""S2c — LIVE 2nd-source fetchers (Exa news + EDGAR Form D) + the enrichment runner.

Wires the injected-fetcher pipeline (`multisource_enrich.enrich_company`, S2b) to the REAL
sources: Exa neural web search for funding/traction NEWS (attaches to the targeted company),
and EDGAR full-text Form D for private-raise FILINGS (whose issuer is run through the S2a
entity resolver — a real match attaches at the `primary_filing` tier, an SPV/namesake is
rejected). This is the only module that touches the live web/EDGAR; the pipeline + resolver
stay source-agnostic and offline-tested.
"""
from __future__ import annotations

import hashlib


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


async def news_fetcher(company_name: str, *, web, max_results: int = 3) -> list[dict]:
    """Exa web search for funding/traction news about `company_name` → candidate NEWS docs
    (source_key='news' → `analysis` tier). Each doc carries the page body as grounding text.
    Fail-safe → []. NEWS is not a filing, so the pipeline attaches it to the targeted company."""
    try:
        results = await web.search(
            f"{company_name} startup funding round raised investors traction", max_results=max_results)
    except Exception:   # noqa: BLE001
        return []
    docs: list[dict] = []
    for r in (results or []):
        body = (getattr(r, "body", None) or getattr(r, "snippet", "") or "").strip()
        url = getattr(r, "url", "") or ""
        if not body:
            continue
        docs.append({
            "source_key": "news", "document_id": "news:" + _sha(url or body),
            "text": body[:4000], "facets": {"source_kind": "news", "url": url},
        })
    return docs


async def formd_fetcher(company_name: str, *, edgar, max_hits: int = 3) -> list[dict]:
    """EDGAR full-text Form D for `company_name` → candidate FILING docs (source_key='edgar' →
    `primary_filing`, controlling). Carries `issuer_name` so the pipeline's ER can accept a real
    match or REJECT an SPV/namesake. Fail-safe → []."""
    try:
        refs = await edgar._fts_formd(company_name, max_hits)
    except Exception:   # noqa: BLE001
        return []
    docs: list[dict] = []
    for ref in (refs or []):
        try:
            for dref in await edgar.list_documents(ref):
                raw = await edgar.fetch_artifact(dref)
                text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
                if not text.strip():
                    continue
                docs.append({
                    "source_key": "edgar", "document_id": "edgar:" + (ref.native_id or _sha(text)),
                    "text": text[:4000], "facets": {"source_kind": "filing"},
                    "issuer_name": ref.title or company_name, "strong_ids": {},
                })
        except Exception:   # noqa: BLE001
            continue
    return docs


async def enrich_one(company_id: str, company_name: str, dsn: str, *,
                     sources: tuple[str, ...] = ("news", "formd"),
                     dry_run: bool = True, tenant_id: str = "demo",
                     object_policy: str = "create") -> dict:
    """Run the live multi-source enrichment on ONE canonical company. Builds the tech-configured
    store + Exa web + EDGAR + tech authority policy, then calls the S2b pipeline with the S2a
    resolver. dry_run (default) plans + costs without spending. Returns the pipeline summary."""
    from api.claimgraph_tech import make_tech_claim_store
    from api.canonicalize import resolve_entity, resolve_conflicts
    from api.multisource_enrich import enrich_company
    from eigen_kernel.runtime.build import build_web
    from eigen_vertical_tech.connectors.edgar import EdgarConnector
    from eigen_vertical_tech.authority import TechAuthorityPolicy
    from eigen_vertical_tech.claim_extract import extract_typed_claims

    store = make_tech_claim_store(dsn)
    web = build_web(mode="live", domains=(), recent=True)
    edgar = EdgarConnector()
    fetchers = []
    if "news" in sources:
        fetchers.append(lambda n: news_fetcher(n, web=web))
    if "formd" in sources:
        fetchers.append(lambda n: formd_fetcher(n, edgar=edgar))
    try:
        return await enrich_company(
            store=store, dsn=dsn, company_id=company_id, company_name=company_name,
            fetchers=fetchers, extract_fn=extract_typed_claims,
            resolve_entity_fn=resolve_entity, resolve_conflicts_fn=resolve_conflicts,
            authority_policy=TechAuthorityPolicy(), llm=None,
            tenant_id=tenant_id, dry_run=dry_run, object_policy=object_policy)
    finally:
        try:
            await store.close()
        except Exception:   # noqa: BLE001
            pass
