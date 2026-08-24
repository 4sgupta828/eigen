"""Open-web page-quality screen — domain-free, LLM-owned, fail-closed.

When a retrieval leg reaches past the vertical's trusted-domain whitelist into the
open web, its hits carry no venue-authority guarantee — the tier grader ranks an
unknown domain 0, it does not REJECT it, so SEO junk would enter the evidence pool
unscreened. This module is the explicit defense: ONE batched LLM judgment (Rule 18 —
the keep/drop decision is the model's, never a keyword matcher) that keeps usable,
relevant pages and drops junk/irrelevant ones. All domain vocabulary lives in the
injected `prompt`; this file names no domain concept.

Return contract (the caller distinguishes can't-judge from judged-all-drop):
  - `None`  → COULD NOT JUDGE (no judge / blank prompt / exhausted budget / ANY
              error). The screen never ran; the caller MUST fail safe (e.g. to the
              authoritative subset), NOT treat this as "everything dropped".
  - `[]`    → JUDGED, nothing kept — OR nothing to judge (empty input legitimately
              yields empty output). Either way the judge's result is respected.
  - `list`  → JUDGED, the kept hits.
The code does only structural work (build the candidate list, parse the verdicts,
filter by index); the meaning is entirely the LLM's.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

_log = logging.getLogger(__name__)

# Cap each candidate's body excerpt so the batched judge call stays small (Rule: credit
# discipline — this is one bounded call, not a per-hit fan-out).
_EXCERPT_CAP = 600


class _Verdict(BaseModel):
    index: int
    keep: bool
    reason: str = ""


class _Verdicts(BaseModel):
    verdicts: list[_Verdict] = []


def _excerpt(text: str) -> str:
    t = (text or "").strip()
    return t[:_EXCERPT_CAP]


async def screen_open_web_hits(hits, *, question, llm, prompt, budget) -> list | None:
    """Screen open-web `hits` with an LLM judge, distinguishing can't-judge from judged-drop.

    `hits` are BlockHit-like items (document_id/document_title/text). `prompt` is the
    vertical-supplied judging system prompt (opaque; carries all domain vocabulary).

    Returns:
      - `None`  → could NOT judge (llm is None / blank prompt / exhausted budget / ANY
                  error). The caller should FAIL SAFE (e.g. authoritative subset), not
                  treat it as an all-drop.
      - `[]`    → judged and nothing kept, OR nothing to judge (empty input).
      - `list`  → the kept hits.
    """
    if llm is None or not (prompt or "").strip():
        return None
    if getattr(budget, "exhausted", False):
        return None
    if not hits:
        return []

    # Build a compact, indexed candidate list. Dedup obviously identical URLs cheaply
    # (keep the first occurrence); index is the position in the RETURNED candidate list
    # and maps back to `kept_hits`.
    kept_hits: list = []
    seen_urls: set[str] = set()
    lines: list[str] = []
    for h in hits:
        url = getattr(h, "document_id", "") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        idx = len(kept_hits)
        kept_hits.append(h)
        title = getattr(h, "document_title", "") or ""
        body = _excerpt(getattr(h, "text", ""))
        lines.append(
            f"[{idx}] url: {url}\n    title: {title}\n    body: {body}"
        )

    if not kept_hits:
        return []

    user_content = (
        "QUESTION:\n" + (question or "").strip()
        + "\n\nCANDIDATES (one per numbered block):\n"
        + "\n\n".join(lines)
        + "\n\nFor EACH candidate index, return a verdict {index, keep, reason}. "
        "keep=true to include the page, keep=false to drop it."
    )

    try:
        res = await llm.complete(
            system=prompt,
            messages=[{"role": "user", "content": user_content}],
            response_format=_Verdicts,
            max_tokens=1024,
        )
        budget.charge(calls=1, tokens=res.output_tokens)
        parsed = res.parsed
        kept_idxs = {
            v.index
            for v in getattr(parsed, "verdicts", [])
            if getattr(v, "keep", False) and 0 <= getattr(v, "index", -1) < len(kept_hits)
        }
        return [kept_hits[i] for i in range(len(kept_hits)) if i in kept_idxs]
    except Exception as e:  # noqa: BLE001 — could not judge → None so the caller fails safe
        _log.warning("open-web quality screen failed: %r", e)
        return None
