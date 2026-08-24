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

from pydantic import BaseModel

# HUMAN-READABLE research only — papers, preprints, articles/news, essays & engineering blogs.
# Deliberately EXCLUDES SEC filings (10-K/10-Q forms), patents, code, benchmarks, raw datasets:
# those are records/forms, not something a person reads as "related research".
RESEARCH_KINDS: tuple[str, ...] = ("paper", "preprint", "news", "essay", "corp_eng")

# Kinds that carry comparable CITATION metrics (peer-review + cited_by_count). Everything else
# (preprints, news, essays, blogs) ranks by recency + relevance — citations don't compare across.
_CITED_KINDS: frozenset[str] = frozenset({"paper"})


def _int(v: Any) -> int:
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


# Answer-preamble prefixes that mark a MIS-INGESTED doc (an LLM answer stored as a "paper" with a
# sentence for a title) — display hygiene until corpus cleanup removes such rows. A real paper/filing
# title never starts this way. Structural guard, not a semantic judgment.
_BAD_TITLE_PREFIXES = ("based on ", "here ", "here's ", "i have ", "i've ", "to answer ",
                       "the following ", "in summary", "sure,", "certainly")


def _ok_title(title: str | None) -> bool:
    """A plausible document title for display: non-empty, not absurdly long, and not an answer-like
    sentence from a mis-ingested doc."""
    t = (title or "").strip()
    if not t or len(t) > 180:
        return False
    return not t.lower().startswith(_BAD_TITLE_PREFIXES)


def _rank_within_kind(kind: str, hit) -> tuple:
    """The per-kind quality key (descending). Citation counts / peer-review only compare WITHIN a kind."""
    f = hit.facets or {}
    if kind in _CITED_KINDS:
        return (1 if f.get("is_peer_reviewed") == "true" else 0, _int(f.get("cited_by_count")),
                _int(f.get("year")), hit.score)
    # preprints / news / essays / blogs: no comparable citation metric → recency, then relevance
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
    docs = [h for h in docs if h.score >= floor and _ok_title(h.document_title)]
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
            "_snippet": (h.text or "")[:500],   # for the rationale LLM; stripped before returning
        })
    # RELEVANCE GATE (Rule 18 — relevance is a semantic judgment the embedding-distance floor can't
    # make): the LLM judges each candidate against the question and DROPS off-topic ones. For a
    # subject-specific question with no genuinely relevant research, this correctly empties the section
    # (honest omit) instead of showing the 'best of a bad lot' the relative floor let through. If the
    # judge is unavailable, we keep the structurally-floored items (prior behavior).
    judged = await _judge_relevance(service, q, out)
    for it in out:
        it.pop("_snippet", None)
    return judged


class _Rationale(BaseModel):
    i: int
    relevant: bool = True
    why: str = ""


class _Rationales(BaseModel):
    items: list[_Rationale] = []


_RATIONALE_SYSTEM = (
    "You curate a 'related research' list for a user's QUESTION. For each numbered item, decide if it "
    "is GENUINELY relevant — it must meaningfully relate to the question's SUBJECT or TOPIC and help "
    "inform it. Set relevant=false for tangential or off-topic items (e.g. a general-AI blog when the "
    "question is about a specific company, or an unrelated domain). Be strict: it is better to drop a "
    "weak item than to show something off-topic. For each item return {i, relevant, why}: `why` is ONE "
    "short sentence (<=20 words) — when relevant, HOW it connects to the question; when not, why it "
    "does not. Base it ONLY on the given title/snippet; never claim findings you cannot see.")


async def _judge_relevance(service, question: str, items: list[dict]) -> list[dict]:
    """LLM-judge each item's relevance to `question` (one batch call): attach a `why` line and DROP
    the off-topic ones. Returns the kept items (may be empty → the section is omitted). Best-effort:
    if the judge is unavailable/errors, return the items unchanged (structural floor still applied)."""
    llm = getattr(service, "llm", None)
    if not items or llm is None:
        return items
    lines = []
    for idx, it in enumerate(items):
        meta = " · ".join(x for x in [it.get("kind"), str(it.get("year") or "")] if x)
        lines.append(f"[{idx}] {it.get('title','')} ({meta})\n    {(it.get('_snippet') or '')[:300]}")
    user = f"QUESTION: {question[:500]}\n\nRESEARCH ITEMS:\n" + "\n".join(lines)
    try:
        comp = await llm.complete(system=_RATIONALE_SYSTEM,
                                  messages=[{"role": "user", "content": user}],
                                  response_format=_Rationales, max_tokens=600)
    except Exception:  # noqa: BLE001 — judge is best-effort; keep the structurally-floored items
        return items
    verdicts: dict[int, tuple[bool, str]] = {}
    for r in getattr(comp.parsed, "items", []) or []:
        if isinstance(getattr(r, "i", None), int) and 0 <= r.i < len(items):
            verdicts[r.i] = (bool(getattr(r, "relevant", True)), (getattr(r, "why", "") or "").strip())
    kept: list[dict] = []
    for idx, it in enumerate(items):
        rel, why = verdicts.get(idx, (True, ""))   # unjudged → keep (don't silently drop)
        if not rel:
            continue
        if why:
            it["why"] = why
        kept.append(it)
    return kept
