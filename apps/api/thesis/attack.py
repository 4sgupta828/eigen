"""The attack — retrieve FOR, then genuinely retrieve AGAINST, then say which.

The disconfirming leg is not a by-product here, it is the point. It is authored by the kernel's
existing red-team refuter (`eigen_kernel/research/refuter.py`), which exists precisely because a
model writing its own disconfirming query is "grading its own homework" — so the against-queries come
from a DIFFERENT model family than anything else in this mode.

And when that leg comes back empty, the claim is UNDER-TESTED, not proven. Disconfirmation attempted
is not disconfirmation found. That distinction is the whole reason this is a stress test.
"""
from __future__ import annotations

import os
import re
import hashlib

from eigen_kernel.research.evidence_binding import EvidenceCandidate, bind_candidates

from .schema import (
    CALL_ONLY, CONTRADICTED, OPEN, SIDE_AGAINST, SIDE_FOR, STATED, SUPPORTED, UNDER_TESTED,
    UNSETTLEABLE, is_signal_only, register_of,
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
    quote = (r["text"] or "").strip()[:MAX_QUOTE]
    document_id = str(r["document_id"] or "")
    block_id = str(r["block_id"] or "")
    candidate_id = hashlib.sha256(
        f"{document_id}\0{block_id}\0{quote}".encode("utf-8")
    ).hexdigest()[:24]
    subject = next((str(facets.get(k) or "").strip() for k in
                    ("subject", "subject_id", "entity_name", "entity_id", "issuer")
                    if facets.get(k)), "")
    period = (r["published_at"] or "")[:10]
    return {"id": candidate_id, "side": side, "discovery_side": side,
            "register": register_of(sk), "source_key": sk,
            "signal_only": is_signal_only(sk), "title": (r["document_title"] or "")[:300],
            "quote": quote, "block_text": r["text"] or "", "source_url": url,
            "as_of": period, "period": period, "basis": "corpus",
            "document_id": document_id, "block_id": block_id,
            "source_subject": subject,
            "evidence_kind": str(facets.get("evidence_kind") or facets.get("source_kind") or ""),
            "independence_key": document_id or f"{sk}:{subject}", "facets": facets}


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


WEB_USD_PER_QUERY = float(os.environ.get("EIGEN_THESIS_WEB_USD", "0.006"))
WEB_MAX_RESULTS = 8
WEB_MIN_CHARS = 80


def _web_client(manifest=None):
    """The kernel's web leg, unscoped. Never raises — no keys means no web, reported as such."""
    try:
        from eigen_kernel.runtime.build import build_web
        return build_web(mode=os.environ.get("EIGEN_PROVIDER_MODE") or "live",
                         domains=getattr(manifest, "web_domains", ()), recent=False)
    except Exception:      # noqa: BLE001
        return None


async def _web(client, query: str, side: str, terms: list[str]) -> list[dict]:
    """Web rows for one query, bound to the claim the same way corpus rows are.

    Everything from here is `stated` and SIGNAL — an article is somebody writing, never a filed
    number. The standing directive holds: coverage can colour a case and can never carry it.
    """
    if client is None or not query.strip():
        return []
    try:
        res = await client.search(query, max_results=WEB_MAX_RESULTS, open_web=True)
    except Exception:      # noqa: BLE001 — a web leg we cannot reach thins the table, never fails it
        return []
    out = []
    for r in res or []:
        # Exa returns query-aware highlights (the discriminating passages) PLUS a full-text body. Keep
        # the highlights first (they lead the shown quote), then a generous slice of the body so the
        # synthesis has real depth to draw on — not just a 300-char snippet. block_text carries all of
        # it; the shown/verifiable quote is still capped at MAX_QUOTE below.
        text = " ".join(filter(None, [*(getattr(r, "highlights", ()) or ()),
                                      getattr(r, "snippet", "") or "",
                                      (getattr(r, "body", "") or "")[:3000]])).strip()
        if len(text) < WEB_MIN_CHARS or not binds(text, terms):
            continue
        host = ""
        try:
            from urllib.parse import urlparse
            host = (urlparse(r.url).hostname or "").replace("www.", "")
        except Exception:      # noqa: BLE001
            pass
        out.append({"side": side, "register": STATED, "source_key": "web",
                    "signal_only": True,            # coverage, never a fact
                    "title": (getattr(r, "title", "") or host or "web")[:300],
                    "quote": text[:MAX_QUOTE], "source_url": r.url or "",
                    "block_text": text, "document_id": "", "block_id": "",
                    "source_subject": "", "evidence_kind": "coverage",
                    "period": (getattr(r, "published", "") or "")[:10],
                    "as_of": (getattr(r, "published", "") or "")[:10], "basis": "web coverage",
                    "discovery_side": side, "facets": {},
                    "id": hashlib.sha256(f"{r.url}\0{text[:MAX_QUOTE]}".encode()).hexdigest()[:24],
                    "independence_key": host or (r.url or "")})
    return out


async def attack_claim(dsn: str, *, claim: str, settleable: str, judge_llm=None, ui=None,
                       tenant: str = "demo", extra_context: str = "", web_client=None,
                       relation_llm=None, evidence_policy=None, always_retrieve: bool = False) -> dict:
    """-> {evidence: [...], verdict, note, against_queries, searched}.

    Never raises: a corpus we cannot reach yields an honest `under_tested`, reported as an attempt.

    `always_retrieve`: gather corpus + web even for a `call_only` aspect. The claims model skips
    retrieval for call_only rungs (only a person can SETTLE them) — but the inquiry model runs the
    user's OWN question and should always show what the record does say (as signal/proxy), never a bare
    "nothing found". Authority policy still keeps low-tier coverage from CARRYING such an aspect.
    """
    retrieve = always_retrieve or settleable != CALL_ONLY
    terms = _terms(claim + " " + extra_context)
    from eigen_kernel.research.refuter import refute_hypothesis

    # The red team writes the against-queries. A different family, and fail-closed: with no
    # cross-family judge we say so rather than quietly writing our own and calling it adversarial.
    try:
        against_qs = await refute_hypothesis(claim, judge_llm, budget=None, n=N_AGAINST_QUERIES)
    except Exception:      # noqa: BLE001
        against_qs = []

    attack_attempted = bool(against_qs)
    ev_for: list[dict] = []
    ev_against: list[dict] = []
    searched = 0
    corpus_failed = False
    if dsn and retrieve:
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
        except Exception:      # noqa: BLE001 — surfaced below; never mislabeled as completed research
            corpus_failed = True

    # CORPUS FIRST, WEB WHERE IT IS SILENT — the standing directive, and also the cheap order. Our
    # own Postgres costs nothing and is tier-classified; a paid web query is worth spending only on a
    # claim the record could not speak to at all. A demand thesis about a market segment is exactly
    # the case the corpus is thin on and the open web is not.
    web_qs = 0
    if web_client is not None and retrieve:
        if not ev_for:
            got = await _web(web_client, claim, SIDE_FOR, terms)
            web_qs += 1
            ev_for.extend(got)
        if not ev_against and against_qs:
            got = await _web(web_client, against_qs[0], SIDE_AGAINST, terms)
            web_qs += 1
            ev_against.extend(got)

    ev_for = _dedupe(ev_for, MAX_PER_SIDE)
    ev_against = _dedupe(ev_against, MAX_PER_SIDE)
    raw = ev_for + ev_against
    candidates = [EvidenceCandidate(
        id=e["id"], quote=e["quote"], block_text=e.get("block_text") or e["quote"],
        document_id=e.get("document_id") or "", block_id=e.get("block_id") or "",
        source_subject=e.get("source_subject") or "", evidence_kind=e.get("evidence_kind") or "",
        period=e.get("period") or "", facets=e.get("facets") or {},
        signal_only=bool(e.get("signal_only")), discovery_side=e.get("discovery_side") or e["side"],
    ) for e in raw]
    bound = await bind_candidates(claim, candidates, relation_llm)
    original = {e["id"]: e for e in raw}
    evidence = []
    for row in bound:
        merged = {**original[row["id"]], **row}
        # Keep block_text on the in-memory row: the synthesis reads it for depth (the full passage the
        # row was drawn from, e.g. Exa highlights + body). add_evidence persists only its own columns
        # (block_text is not one), so this never bloats the ledger or the client response.
        # `side` remains a display grouping only. Relationship is the semantic judgment.
        if row["relation"] == "supports":
            merged["side"] = SIDE_FOR
        elif row["relation"] == "contradicts":
            merged["side"] = SIDE_AGAINST
        evidence.append(merged)

    counts = {k: sum(1 for e in evidence if e.get("relation") == k)
              for k in ("supports", "contradicts", "context", "signal")}
    if settleable == CALL_ONLY:
        research_status, note = UNSETTLEABLE, "No document can settle this. It needs a person."
    elif not attack_attempted:
        research_status, note = ("attack_unavailable",
                                 "No red-team model was available, so the attack was not run.")
    elif corpus_failed:
        research_status, note = "failed", "The corpus search failed; retry before drawing a conclusion."
    elif evidence_policy is not None:
        research_status, note = evidence_policy.qualify(evidence, settleable=settleable)
    else:
        # Safe fallback for a vertical without a decision policy: only the absence of decisive rows
        # can be stated; no application-level threshold is invented here.
        research_status, note = UNDER_TESTED, "The attack completed without a configured evidence policy."

    return {"evidence": evidence, "verdict": research_status, "research_status": research_status,
            "attack_attempted": attack_attempted, "note": note,
            "against_queries": against_qs, "searched": searched, "web_queries": web_qs,
            "counts": {"for": counts["supports"], "against": counts["contradicts"],
                       "context": counts["context"], "signal": counts["signal"]}}
