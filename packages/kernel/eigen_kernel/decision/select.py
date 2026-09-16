"""Precision: relevance scoring + de-duplication as SELECTION, never hard filters. Domain-free.

The panel (2026-09-16) rejected a binary relevance GATE: a false negative deletes a question, and the
gate is absent exactly when the frame is weak (the worst drift case). Instead:

  • relevance_score(q, frame) ranks a question by how tightly its target/text binds to the frame's
    load-bearing assumptions/risks — the decision's actual substance. Used to ORDER within a dimension.
  • select_for_aspect(...) keeps the top questions up to the aspect's soft budget, preferring the
    required lenses and higher relevance, dropping a near-duplicate of one already kept. It NEVER returns
    fewer than `floor` (default 1) — a dimension is never emptied by precision, only trimmed.

Similarity is lexical (token Jaccard) by default; when an `embed(texts)->vectors` seam is supplied it is
cosine over embeddings — sharper on paraphrase, cheap next to the evidence runs it prevents. Either way
the kernel stays domain-free: it compares strings, it does not read them.
"""
from __future__ import annotations

import re
from typing import Callable, Sequence

from .types import Question, REQUIRED_KINDS

Embed = Callable[[list[str]], list[list[float]]]

# tiny English stoplist — enough to stop boilerplate ("is the company able to…") from dominating overlap
_STOP = frozenset("a an the is are was were be been being do does did of to in on for and or vs "
                  "this that these those it its with as at by from will would can could should have "
                  "has had not no than then so if whether does can enough real actually".split())
_DUP_THRESHOLD = 0.82     # at/above this similarity, two targets are the same question


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
                     if t not in _STOP and len(t) > 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def _frame_texts(frame: dict | None) -> list[str]:
    out: list[str] = []
    for section in ("assumptions", "risks"):
        for item in (frame or {}).get(section, []) or []:
            t = (item.get("text") if isinstance(item, dict) else str(item)) or ""
            if t.strip():
                out.append(t)
    return out


def _q_text(q: Question) -> str:
    return f"{q.target} {q.text}".strip()


def relevance_scores(questions: list[Question], frame: dict | None, *, embed: Embed | None = None
                     ) -> list[float]:
    """A relevance score in [0,1] per question: the strongest binding of its target/text to any of the
    frame's assumptions/risks. With no frame (or no items) every score is a neutral 0.5 — nothing to bind
    to, so selection falls back to lens priority + order, never dropping for 'irrelevance'."""
    anchors = _frame_texts(frame)
    if not questions:
        return []
    if not anchors:
        return [0.5] * len(questions)
    q_texts = [_q_text(q) for q in questions]
    if embed is not None:
        try:
            vecs = embed(q_texts + anchors)
            qv, av = vecs[:len(q_texts)], vecs[len(q_texts):]
            return [max((_cosine(qv[i], a) for a in av), default=0.0) for i in range(len(q_texts))]
        except Exception:      # noqa: BLE001 — a flaky embedder falls back to lexical, never blocks
            pass
    a_tok = [_tokens(a) for a in anchors]
    return [max((_jaccard(_tokens(qt), at) for at in a_tok), default=0.0) for qt in q_texts]


def score_questions(questions: list[Question], frame: dict | None, *, embed: Embed | None = None
                    ) -> tuple[list[float], dict[int, list[float]] | None]:
    """Score every question AND return reusable per-index embedding vectors in ONE embed batch, so
    relevance ranking and de-dup share the same vectors. `embed_vecs` is keyed by the question's position
    in `questions` (the caller's global index) or None when running lexically. Never raises."""
    if not questions:
        return [], None
    anchors = _frame_texts(frame)
    q_texts = [_q_text(q) for q in questions]
    if embed is not None:
        try:
            vecs = embed(q_texts + anchors)
            qv = [list(v) for v in vecs[:len(q_texts)]]
            av = [list(v) for v in vecs[len(q_texts):]]
            embed_vecs = {i: qv[i] for i in range(len(qv))}
            scores = ([0.5] * len(q_texts) if not av
                      else [max((_cosine(qv[i], a) for a in av), default=0.0) for i in range(len(qv))])
            return scores, embed_vecs
        except Exception:      # noqa: BLE001 — a flaky embedder falls back to lexical, never blocks
            pass
    if not anchors:
        return [0.5] * len(q_texts), None
    a_tok = [_tokens(a) for a in anchors]
    return [max((_jaccard(_tokens(qt), at) for at in a_tok), default=0.0) for qt in q_texts], None


def _is_dup(q: Question, kept: list[Question], *, embed_vecs: dict[int, list[float]] | None,
            idx: int, kept_idx: list[int]) -> bool:
    if embed_vecs is not None:
        v = embed_vecs.get(idx)
        return any(v is not None and embed_vecs.get(j) is not None
                   and _cosine(v, embed_vecs[j]) >= _DUP_THRESHOLD for j in kept_idx)
    qt = _tokens(_q_text(q))
    return any(_jaccard(qt, _tokens(_q_text(k))) >= _DUP_THRESHOLD for k in kept)


def select_for_aspect(questions: list[Question], scores: list[float], *, budget: int, floor: int = 1,
                      embed_vecs: dict[int, list[float]] | None = None,
                      indices: list[int] | None = None) -> list[Question]:
    """Keep the best `budget` questions for one aspect: required lenses first, then by relevance, dropping
    a near-duplicate of one already kept — but never returning fewer than `floor` (coverage wins over
    de-dup). `embed_vecs`/`indices` let a caller reuse one batch of embeddings for dup-detection."""
    if not questions:
        return []
    order = sorted(range(len(questions)),
                   key=lambda i: (0 if questions[i].kind in REQUIRED_KINDS else 1, -scores[i]))
    kept: list[Question] = []
    kept_idx: list[int] = []
    for pos in order:
        if len(kept) >= max(budget, floor):
            break
        gi = indices[pos] if indices is not None else pos
        if len(kept) >= floor and _is_dup(questions[pos], kept, embed_vecs=embed_vecs,
                                          idx=gi, kept_idx=kept_idx):
            continue      # a duplicate is only skipped once the floor is met — never empties a dimension
        kept.append(questions[pos])
        kept_idx.append(gi)
    return kept
