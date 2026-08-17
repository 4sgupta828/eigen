"""arXiv connector — preprint metadata (public API, Atom XML).

discover_entities → query the arXiv API (or use injected fixture records); one EntityRef per
paper. list_documents → one synthesized markdown paper-document per arXiv id. fetch_artifact →
the assembled markdown bytes. Tests inject `papers` so they run offline.
"""
from __future__ import annotations

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import paper_doc
from ._http import HttpStrategy

API = "https://export.arxiv.org/api/query"


class ArxivConnector:
    key = "arxiv"

    def __init__(self, *, papers: list[dict] | None = None, page_size: int = 25):
        # arXiv rate-limits aggressively (429) and asks for ~3s between requests — use a patient
        # backoff so a burst of ingest jobs retries rather than dying.
        self.fetch_strategy = HttpStrategy(base_delay=3.0, max_retries=5)
        self._page_size = page_size
        self._by_id: dict[str, dict] = {}
        for p in (papers or []):
            self._by_id[paper_doc.arxiv_id(p)] = p

    @staticmethod
    def _parse_atom(raw: bytes) -> list[dict]:
        """Minimal Atom→record parse (stdlib only). Full-text ingest hardening is P2."""
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        out: list[dict] = []
        root = ET.fromstring(raw)
        for e in root.findall("a:entry", ns):
            raw_id = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
            arxiv_id = raw_id.split("v")[0]
            cats = [c.get("term", "") for c in e.findall("a:category", ns)]
            prim = e.find("arxiv:primary_category", ns)
            out.append({
                "id": arxiv_id,
                "title": " ".join((e.findtext("a:title", default="", namespaces=ns) or "").split()),
                "authors": [a.findtext("a:name", default="", namespaces=ns) for a in e.findall("a:author", ns)],
                "categories": cats,
                "primary_category": prim.get("term", "") if prim is not None else (cats[0] if cats else ""),
                "published": (e.findtext("a:published", default="", namespaces=ns) or "")[:10],
                "summary": " ".join((e.findtext("a:summary", default="", namespaces=ns) or "").split()),
            })
        return out

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        if not (window or {}).get("query") and self._by_id:
            papers = list(self._by_id.values())
        else:
            q = (window or {}).get("query", "").strip() or "large language models"
            limit = int((window or {}).get("limit", self._page_size))
            url = f"{API}?search_query=all:{q.replace(' ', '+')}&start=0&max_results={limit}"
            # freshness ingest lane: sort newest-first so the corpus gets RECENT preprints, not just the
            # most-cited older ones (default stays relevance). window {"sort":"recent"} opts in.
            if str((window or {}).get("sort", "")).lower() == "recent":
                url += "&sortBy=submittedDate&sortOrder=descending"
            papers = self._parse_atom(await self.fetch_strategy.fetch(url))
            for p in papers:
                self._by_id[paper_doc.arxiv_id(p)] = p
        return [EntityRef(source_key=self.key, native_id=paper_doc.arxiv_id(p),
                          title=paper_doc.title(p), facets=paper_doc.facets(p))
                for p in papers if paper_doc.arxiv_id(p)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        p = self._by_id.get(entity.native_id)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown",
                            facets=paper_doc.facets(p) if p else dict(entity.facets),
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        p = self._by_id.get(doc.native_id)
        if p is None:
            url = f"{API}?id_list={doc.native_id}"
            recs = self._parse_atom(await self.fetch_strategy.fetch(url))
            p = recs[0] if recs else {"id": doc.native_id}
            self._by_id[doc.native_id] = p
        return paper_doc.to_markdown(p).encode("utf-8")
