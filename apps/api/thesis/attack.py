"""The attack — retrieve FOR, then genuinely retrieve AGAINST, then say which.

The disconfirming leg is not a by-product here, it is the point. It is authored by the kernel's
existing red-team refuter (`eigen_kernel/research/refuter.py`), which exists precisely because a
model writing its own disconfirming query is "grading its own homework" — so the against-queries come
from a DIFFERENT model family than anything else in this mode.

And when that leg comes back empty, the claim is UNDER-TESTED, not proven. Disconfirmation attempted
is not disconfirmation found. That distinction is the whole reason this is a stress test.
"""
from __future__ import annotations

import re

from .schema import (
    CALL_ONLY, CONTRADICTED, OPEN, SIDE_AGAINST, SIDE_FOR, SUPPORTED, UNDER_TESTED, UNSETTLEABLE,
    is_signal_only, register_of,
)

MAX_PER_SIDE = 6
MAX_PER_QUERY = 8
MIN_CHARS = 60
MAX_QUOTE = 400
N_AGAINST_QUERIES = 3

_COLS = """SELECT document_id, block_id, text, document_title, source_key, facets,
                  facets->>'published_at' AS published_at
             FROM rs_block"""

# Words that carry no subject. A claim is mostly these, and binding on them binds everything.
_STOP = frozenset("""a an the and or but if then than that this these those of for to in on at by with
from as is are was were be been being will would can could should may might do does did not no nor so
such own same too very already exist exists existing enough real really actually pay pays paid buy buys
buying sell sells selling market markets company companies firm firms team teams people person use uses
using used need needs needed want wants make makes made have has had them they their there here it its
who what when where why how much many more most other another each both all any some""".split())


def _terms(claim: str) -> list[str]:
    """The words that actually pick this claim out. Deliberately narrow — the `Clay` lesson: matching
    on generic words binds half the corpus and calls it evidence."""
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9+.\-]{2,}", claim or ""):
        lw = w.lower()
        if lw in _STOP or lw in seen or len(lw) < 4:
            continue
        seen.add(lw)
        out.append(w)
    return out[:8]


def binds(text: str, terms: list[str], *, need: int = 2) -> bool:
    """Does this passage actually concern the claim? At least `need` distinct claim terms, each as a
    whole word. One shared noun is a coincidence, not congruence."""
    if not terms:
        return False
    low = (text or "").lower()
    hits = 0
    for t in terms:
        if re.search(r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])", low):
            hits += 1
            if hits >= need:
                return True
    return hits >= need


async def _search(conn, tenant: str, query: str, limit: int) -> list:
    return await conn.fetch(
        _COLS + """ WHERE tenant_id = $1 AND tsv @@ websearch_to_tsquery('english', $2)
                 ORDER BY ts_rank(tsv, websearch_to_tsquery('english', $2), 1) DESC
                    LIMIT $3""", tenant, query, limit)


def _row(r, side: str, ui=None) -> dict:
    import json as _json
    sk = (r["source_key"] or "").lower()
    facets = r["facets"]
    if isinstance(facets, str):
        try:
            facets = _json.loads(facets)
        except Exception:      # noqa: BLE001
            facets = {}
    facets = facets or {}
    url = ""
    if ui is not None:
        try:
            url = ui.source_url(r["document_id"], (r["text"] or "")[:120], facets) or ""
        except Exception:      # noqa: BLE001
            url = ""
    url = url or facets.get("url") or facets.get("source_url") or facets.get("link") or ""
    return {"side": side, "register": register_of(sk), "source_key": sk,
            "signal_only": is_signal_only(sk), "title": (r["document_title"] or "")[:300],
            "quote": (r["text"] or "").strip()[:MAX_QUOTE], "source_url": url,
            "as_of": (r["published_at"] or "")[:10], "basis": "corpus"}


def _dedupe(rows: list[dict], cap: int) -> list[dict]:
    """One document may not fill a side, and a register may not be represented by one loud source."""
    seen_q, per_source, out = set(), {}, []
    for r in rows:
        k = r["quote"][:120]
        if k in seen_q:
            continue
        sk = r["source_key"]
        if per_source.get(sk, 0) >= 2:
            continue
        seen_q.add(k)
        per_source[sk] = per_source.get(sk, 0) + 1
        out.append(r)
        if len(out) >= cap:
            break
    return out


def verdict_for(*, settleable: str, n_for: int, n_against: int) -> tuple[str, str]:
    """(verdict, note). The one place the outcome of a claim is decided.

    `call_only` short-circuits: no count of documents can settle willingness to pay or switching
    cost, so no amount of encouraging retrieval is allowed to move them.
    """
    if settleable == CALL_ONLY:
        return UNSETTLEABLE, "No document can settle this. It needs a person."
    if n_against and not n_for:
        return CONTRADICTED, "The record argues against this and offers nothing for it."
    if n_against and n_for:
        return OPEN, f"Evidence both ways — {n_for} for, {n_against} against. Read both."
    if n_for and not n_against:
        return SUPPORTED, ("The record supports this, and the disconfirming search found nothing — "
                           "which is not the same as there being nothing to find.")
    return UNDER_TESTED, ("Nothing either way. We searched for support and ran a red-team search for "
                          "counter-evidence; neither returned anything congruent.")


async def attack_claim(dsn: str, *, claim: str, settleable: str, judge_llm=None, ui=None,
                       tenant: str = "demo", extra_context: str = "") -> dict:
    """-> {evidence: [...], verdict, note, against_queries, searched}.

    Never raises: a corpus we cannot reach yields an honest `under_tested`, reported as an attempt.
    """
    terms = _terms(claim + " " + extra_context)
    from eigen_kernel.research.refuter import refute_hypothesis

    # The red team writes the against-queries. A different family, and fail-closed: with no
    # cross-family judge we say so rather than quietly writing our own and calling it adversarial.
    try:
        against_qs = await refute_hypothesis(claim, judge_llm, budget=None, n=N_AGAINST_QUERIES)
    except Exception:      # noqa: BLE001
        against_qs = []

    ev_for: list[dict] = []
    ev_against: list[dict] = []
    searched = 0
    if dsn and settleable != CALL_ONLY:
        try:
            import asyncpg
            conn = await asyncpg.connect(dsn)
            try:
                for r in await _search(conn, tenant, claim, MAX_PER_QUERY * 2):
                    if len((r["text"] or "")) >= MIN_CHARS and binds(r["text"], terms):
                        ev_for.append(_row(r, SIDE_FOR, ui))
                searched += 1
                for q in against_qs:
                    for r in await _search(conn, tenant, q, MAX_PER_QUERY):
                        if len((r["text"] or "")) >= MIN_CHARS and binds(r["text"], terms):
                            ev_against.append(_row(r, SIDE_AGAINST, ui))
                    searched += 1
            finally:
                await conn.close()
        except Exception:      # noqa: BLE001 — a corpus we cannot read is under-tested, not supported
            pass

    ev_for = _dedupe(ev_for, MAX_PER_SIDE)
    ev_against = _dedupe(ev_against, MAX_PER_SIDE)
    # SENTIMENT IS NOT SUPPORT. An enthusiastic forum thread reads exactly like demand and is not, so
    # it is carried, labelled, and excluded from the count that decides the verdict.
    n_for = sum(1 for e in ev_for if not e["signal_only"])
    n_against = sum(1 for e in ev_against if not e["signal_only"])
    v, note = verdict_for(settleable=settleable, n_for=n_for, n_against=n_against)
    if not against_qs and settleable != CALL_ONLY:
        note += " (No red-team model was available, so the attack was not run.)"
    return {"evidence": ev_for + ev_against, "verdict": v, "note": note,
            "against_queries": against_qs, "searched": searched,
            "counts": {"for": n_for, "against": n_against,
                       "signal": len(ev_for) + len(ev_against) - n_for - n_against}}
