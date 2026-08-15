"""WebRetrievalSource — the web as just another pluggable RetrievalSource.

Turns web-search results into citable, grounded blocks: each result becomes a
block whose text is the fetched body, with a locator so the SAME span-check gate
verifies a cited quote actually exists in the retrieved page (no fabrication) —
identical provenance to corpus/workspace sources. This is the platform pattern:
every knowledge source (corpus, workspace, web, and later expert transcripts,
surveys, proprietary datasets) implements one port and the agent stays
source-agnostic.

Quality layers (all mechanism — the KNOWLEDGE lives in the vertical, Rule 18):
- DEDUP: the same paper mirrored across PubMed/PMC/journal collapses to one
  result (canonical DOI/PMC/PMID id from the URL, else near-identical titles),
  keeping the copy from the most authoritative domain.
- DOMAIN FACETS: a vertical-supplied domain→facets map stamps venue authority
  (e.g. a guideline body's pages carry pub_type "practice guideline") and the
  publish year onto every block, so the SAME evidence classifier / authority
  pyramid / recency reader that grade corpus evidence also grade web evidence.
- RERANK: chunks are re-scored against the query with the corpus embedder
  (cosine), with a per-page cap so one page can't crowd out the rest; provider
  rank remains the tiebreak and the fallback when embedding is unavailable.
"""
from __future__ import annotations

import dataclasses
import re
from difflib import SequenceMatcher

from eigen_kernel.contract.dto import BlockHit, Capability, FacetFilter, Locator, RetrievalRequest
from eigen_kernel.ingestion.storage import content_key
from eigen_kernel.providers.websearch import WebResult, WebSearchClient

# canonical scholarly ids readable straight off a URL (structural identity, not semantics)
_CANON_ID_RE = re.compile(r"(10\.\d{4,9}/[^\s?#]+?|PMC\d{4,9}|pubmed\.ncbi\.nlm\.nih\.gov/(\d{6,9}))(?=[/?#]|$)", re.I)
_MAX_CHUNKS_PER_PAGE = 3          # rerank cap: no single page dominates the final k


def _chunk_text(text: str, *, max_chars: int = 900) -> list[str]:
    """Split a (possibly break-less HTML→text) body into length-bounded chunks, preferring a
    sentence/newline boundary near the budget so a verbatim span stays intact within one chunk."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + max_chars, len(text))
        if end < len(text):
            window = text[i:end]
            cut = max(window.rfind(". "), window.rfind("\n"), window.rfind("; "))
            if cut > max_chars * 0.5:            # only honor a boundary past the halfway point
                end = i + cut + 1
        piece = text[i:end].strip()
        if piece:
            chunks.append(piece)
        i = end
    return chunks


def _host_of(url: str) -> str:
    m = re.match(r"https?://([^/:]+)", url or "")
    return m.group(1).lower() if m else ""


def _canon_id(url: str) -> str:
    m = _CANON_ID_RE.search(url or "")
    return m.group(0).lower() if m else ""


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).strip()


def _year_of(published: str | None) -> str:
    s = (published or "").strip()[:4]
    return s if s.isdigit() else ""


class WebRetrievalSource:
    def __init__(self, client: WebSearchClient, *, key: str = "web", max_results: int = 8,
                 domain_facets: dict[str, dict] | None = None, embedder=None):
        self.key = key
        self._client = client
        self._max = max_results
        # domain (suffix-matched against the URL host) → facets stamped on every block from it.
        # Supplied by the VERTICAL (venue authority is domain knowledge); empty → no stamping.
        self._domain_facets = dict(domain_facets or {})
        # optional embedder (the corpus one) for query-relevance reranking of chunks
        self._embedder = embedder
        self._cache: dict[tuple[str, str], str] = {}   # (url, block_id) -> body (loader)

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.RETRIEVAL})

    def covers(self) -> FacetFilter:
        return {}          # web is unscoped (public); no facet limit

    def make_block_loader(self, tenant_id: str, workspace_id: str | None = None):
        # Web content is public; the loader is scoped to what THIS search fetched
        # (fail-closed on anything not retrieved this request).
        def _load(document_id: str, block_id: str) -> str | None:
            return self._cache.get((document_id, block_id))
        return _load

    def _facets_for(self, url: str) -> dict:
        host = _host_of(url)
        for d, f in self._domain_facets.items():
            if host == d or host.endswith("." + d):
                return dict(f)
        return {}

    def _authority(self, url: str) -> int:
        # duplicate preference only: a domain the vertical marked as a normative venue wins the
        # mirror contest (e.g. keep the guideline body's copy over an aggregator's)
        return 1 if self._facets_for(url).get("pub_type") else 0

    def _dedup(self, results: list[WebResult]) -> list[WebResult]:
        kept: list[tuple[str, str, WebResult]] = []   # (canon_id, norm_title, result)
        for r in results:
            cid, nt = _canon_id(r.url), _norm_title(r.title)
            dup_at = -1
            for i, (kcid, knt, _kr) in enumerate(kept):
                if (cid and cid == kcid) or (nt and knt and len(nt) > 20
                                             and SequenceMatcher(None, nt, knt).ratio() > 0.92):
                    dup_at = i
                    break
            if dup_at < 0:
                kept.append((cid, nt, r))
            elif self._authority(r.url) > self._authority(kept[dup_at][2].url):
                kept[dup_at] = (cid, nt, r)       # same work, more authoritative venue → swap
        return [r for _, _, r in kept]

    async def search(self, req: RetrievalRequest) -> list[BlockHit]:
        results = self._dedup(await self._client.search(req.query, max_results=self._max))
        # Chunk each fetched page body into length-bounded blocks so a verbatim span is findable
        # (a 4000-char blob is nearly unquotable). Provider HIGHLIGHTS (query-aware extracts from
        # anywhere in the page) come FIRST — they can carry a discriminator the truncated body
        # misses. Interleave breadth-first, gathering up to 3×k candidates for the reranker.
        per_result = []
        for r in results:
            chunks = [h.strip() for h in (getattr(r, "highlights", ()) or ()) if h and h.strip()]
            chunks += _chunk_text(r.body or r.snippet or "")
            per_result.append((r, chunks))
        candidates: list[BlockHit] = []
        budget = max(req.k * 3, req.k)
        ci = 0
        while len(candidates) < budget and any(ci < len(ch) for _, ch in per_result):
            for ri, (r, chunks) in enumerate(per_result):
                if ci >= len(chunks) or len(candidates) >= budget:
                    continue
                text = chunks[ci]
                bid = content_key(f"{r.url}|{ci}|{text}".encode())
                self._cache[(r.url, bid)] = text
                year = _year_of(getattr(r, "published", None))
                facets = self._facets_for(r.url)
                facets["source_domain"] = _host_of(r.url)
                if year:
                    facets.setdefault("year", year)
                candidates.append(BlockHit(
                    document_id=r.url, block_id=bid, text=text,
                    score=float(1000 - ri * 10 - ci),      # provider rank primary, chunk index secondary
                    # block_span locator: web grounding is "quote exists in the fetched chunk", the
                    # same check as a doc span — one uniform provenance gate. url rides in ref.
                    facets=facets, locator=Locator("block_span", r.url, {"block_id": bid, "url": r.url}),
                    # the year in the title keeps currency visible to the composer AND the reader
                    document_title=(f"{r.title} ({year})" if year and r.title else r.title),
                    content_type="text/html", source_key=self.key,
                    legs=("web",),
                ))
            ci += 1
        return self._rerank(req, candidates)[: req.k]

    def _rerank(self, req: RetrievalRequest, hits: list[BlockHit]) -> list[BlockHit]:
        """Query-relevance rerank (cosine via the corpus embedder), provider rank as tiebreak,
        capped per page. Any embedding failure (replay cassette miss, provider error) falls back
        to the provider order — reranking must never break retrieval."""
        if not hits:
            return hits
        order = sorted(range(len(hits)), key=lambda i: -hits[i].score)
        if self._embedder is not None and len(hits) > 1:
            try:
                vecs = self._embedder.embed([req.query] + [h.text for h in hits])
                q = vecs[0]

                def _cos(v):
                    num = sum(a * b for a, b in zip(q, v))
                    dq = sum(a * a for a in q) ** 0.5
                    dv = sum(b * b for b in v) ** 0.5
                    return num / (dq * dv) if dq and dv else 0.0

                sims = [_cos(v) for v in vecs[1:]]
                order = sorted(range(len(hits)), key=lambda i: (-sims[i], -hits[i].score))
            except Exception:   # noqa: BLE001 — rerank is an enhancer, never a gate
                pass
        picked: list[BlockHit] = []
        per_doc: dict[str, int] = {}
        for i in order:
            h = hits[i]
            if per_doc.get(h.document_id, 0) >= _MAX_CHUNKS_PER_PAGE:
                continue
            per_doc[h.document_id] = per_doc.get(h.document_id, 0) + 1
            picked.append(h)
        # rewrite scores to the final order so downstream rank consumers stay consistent
        # (BlockHit is frozen — build replacements, don't mutate)
        return [dataclasses.replace(h, score=float(1000 - pos)) for pos, h in enumerate(picked)]
