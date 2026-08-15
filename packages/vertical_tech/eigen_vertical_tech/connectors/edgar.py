"""SEC EDGAR connector — public-company filings (free full-text API, no key).

discover_entities → query EDGAR full-text search (efts.sec.gov) or use injected fixture
records; one EntityRef per filing. list_documents → one synthesized markdown filing-document
per accession. fetch_artifact → the assembled markdown bytes. Tests inject `filings` so they
run offline.

NOTE (P2): live section normalization is minimal here — the full-text hit's snippet is stored
as a single "Filing Text" section. Rich section splitting (Business / Risk Factors / MD&A) from
the primary document HTML + XBRL financial facts is the P2 hardening step. The FIXTURE path
already carries fully-sectioned records, which is what the offline pipeline is tested against.
"""
from __future__ import annotations

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import filing_doc
from ._http import HttpStrategy

FTS = "https://efts.sec.gov/LATEST/search-index?q="   # full-text search endpoint


class EdgarConnector:
    key = "edgar"

    def __init__(self, *, filings: list[dict] | None = None, page_size: int = 20):
        self.fetch_strategy = HttpStrategy()
        self._page_size = page_size
        self._by_acc: dict[str, dict] = {}
        for f in (filings or []):
            self._by_acc[filing_doc.accession(f)] = f

    async def _fts(self, query: str, limit: int) -> list[dict]:
        """Best-effort live full-text search → minimal normalized records (P2: full sectioning)."""
        import json
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{query.replace(' ', '%20')}%22&hits={limit}"
        try:
            raw = await self.fetch_strategy.fetch(url)
            data = json.loads(raw)
        except Exception:   # noqa: BLE001 — live search is best-effort; offline path uses fixtures
            return []
        recs: list[dict] = []
        for hit in (data.get("hits", {}).get("hits", []) or [])[:limit]:
            src = hit.get("_source", {}) or {}
            acc = (hit.get("_id", "") or "").split(":")[0]
            recs.append({
                "cik": (src.get("cik") or [""])[0] if isinstance(src.get("cik"), list) else src.get("cik", ""),
                "company": (src.get("display_names") or [""])[0],
                "form_type": src.get("file_type", src.get("root_form", "")),
                "filed": src.get("file_date", ""),
                "accession": acc,
                "sections": {"Filing Text": " ".join((src.get("text") or "").split())[:8000]},
            })
        return recs

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        if not (window or {}).get("query") and self._by_acc:
            filings = list(self._by_acc.values())
        else:
            q = (window or {}).get("query", "").strip()
            limit = int((window or {}).get("limit", self._page_size))
            filings = await self._fts(q, limit) if q else []
            for f in filings:
                self._by_acc[filing_doc.accession(f)] = f
        return [EntityRef(source_key=self.key, native_id=filing_doc.accession(f),
                          title=filing_doc.title(f), facets=filing_doc.facets(f))
                for f in filings if filing_doc.accession(f)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        f = self._by_acc.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=filing_doc.facets(f) if f else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        f = self._by_acc.get(doc.native_id) or {"accession": doc.native_id}
        return filing_doc.to_markdown(f).encode("utf-8")
