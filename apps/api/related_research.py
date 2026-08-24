"""Feature 3: 'Top related public research' — a grounded, quality-gated section attached to an
answer (flag EIGEN_RELATED_RESEARCH). Panel-reviewed design (Codex + Gemini + code-grounded subagent):

- A SEPARATE facet-filtered semantic search over the corpus (source_kind ∈ paper/preprint/filing),
  NOT the answer's react-loop atoms (which are shaped to ANSWER the question and may never sweep the
  paper/filing space). One embedding + one retrieval, k~40.
- DEDUP by document_id — papers are split into section-blocks, so raw hits repeat the same paper.
- QUALITY is STRUCTURAL only (Rule 18 — no LLM relevance judgment): a relevance floor on the fused
  score, then per-KIND ranking lanes (citation counts / peer-review don't compare across kinds):
    * paper   → (is_peer_reviewed, cited_by_count, year)
    * preprint→ (year)  [arXiv carries no cited_by_count/venue — the recency lane is forced by the data]
    * filing  → (year)
  Candidates from each lane are merged and the final list is ordered by RELEVANCE (score) so the most
  on-topic item leads, capped at `max_items`.
- HONEST OMIT: if nothing clears the relevance floor, return [] and the section is not shown. This is
  labeled 'related research', never 'the answer's sources'.

Best-effort: any failure returns [] (never breaks the answer). No fabrication — every item is a real
corpus document with a resolvable source URL.
"""
from __future__ import annotations

from typing import Any

# authoritative research/report kinds (verified emitted: paper, preprint, filing). No "report" kind.
RESEARCH_KINDS: tuple[str, ...] = ("paper", "preprint", "filing")


def _int(v: Any) -> int:
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _rank_within_kind(kind: str, hit) -> tuple:
    """The per-kind quality key (descending). Citation counts / peer-review only compare WITHIN a kind."""
    f = hit.facets or {}
    if kind == "paper":
        return (1 if f.get("is_peer_reviewed") == "true" else 0, _int(f.get("cited_by_count")),
                _int(f.get("year")), hit.score)
    # preprint / filing: no comparable citation metric → recency, then relevance
    return (_int(f.get("year")), hit.score)


async def find_related_research(service, *, question: str, tenant_id: str,
                                workspace_id: str | None = None, ui=None,
                                max_items: int = 5, min_score: float = 0.0,
                                rel_floor: float = 0.55, per_kind_cap: int = 3,
                                k: int = 40) -> list[dict]:
    """Return up to `max_items` grounded related-research items, or [] (honest omit). Structural,
    best-effort, never raises. `min_score` = absolute fused-score floor; `rel_floor` = keep only hits
    scoring >= rel_floor * best_score (a relative floor is robust to score-scale drift across queries)."""
    q = (question or "").strip()
    if not q:
        return []
    try:
        hits = await service.search(question=q, tenant_id=tenant_id, workspace_id=workspace_id,
                                    k=k, facets={"source_kind": RESEARCH_KINDS})
    except Exception:  # noqa: BLE001 — best-effort; a retrieval hiccup must not break the answer
        return []
    if not hits:
        return []

    # dedup by document_id, keeping the best-scored block per document (papers are split into blocks)
    best: dict[str, Any] = {}
    for h in hits:
        cur = best.get(h.document_id)
        if cur is None or h.score > cur.score:
            best[h.document_id] = h
    docs = list(best.values())

    # relevance floor: absolute AND relative-to-best (drop plausible-but-off matches)
    top = max(h.score for h in docs)
    floor = max(min_score, rel_floor * top) if top > 0 else min_score
    docs = [h for h in docs if h.score >= floor]
    if not docs:
        return []

    # per-kind lanes → quality rank within kind → take the top few candidates per lane
    def kind_of(h) -> str:
        return str((h.facets or {}).get("source_kind", "")).strip()

    candidates: list = []
    for kind in RESEARCH_KINDS:
        lane = [h for h in docs if kind_of(h) == kind]
        lane.sort(key=lambda h: _rank_within_kind(kind, h), reverse=True)
        candidates.extend(lane[:per_kind_cap])

    # final order = relevance (so the most on-topic item leads), capped
    candidates.sort(key=lambda h: h.score, reverse=True)
    chosen = candidates[:max_items]

    def _url(h):
        if ui is None:
            return None
        fn = getattr(ui, "source_url", None)
        try:
            return fn(h.document_id) if fn and h.document_id else None
        except Exception:  # noqa: BLE001
            return None

    out: list[dict] = []
    for h in chosen:
        f = h.facets or {}
        out.append({
            "title": h.document_title or h.document_id,
            "url": _url(h),
            "source_key": h.source_key,
            "kind": kind_of(h),
            "venue": f.get("venue", ""),
            "year": f.get("year", ""),
            "citations": _int(f.get("cited_by_count")) or None,
            "peer_reviewed": f.get("is_peer_reviewed") == "true",
        })
    return out
