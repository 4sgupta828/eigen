"""Corpus → claim-graph EXTRACTION JOB — Task 2b of the claim-graph build.

Source-agnostic, app-level (asyncpg) orchestrator that walks `rs_block` for a set of
`source_key`s, hands each block to the vertical's GROUNDED typed-claim extractor
(`eigen_vertical_tech.claim_extract.extract_typed_claims` — Task 2a), resolves the
subject/object entities, and upserts grounded claims + evidence into the claim graph
(`api.claimgraph.ClaimGraphStore` — Task 2a's store). It reuses BOTH landed pieces and
duplicates neither the extractor's three gates nor the store's write ethos.

DIVISION OF LABOR (Rule 18): the LLM owns every semantic call (it lives entirely inside
`extract_typed_claims`). This job owns only STRUCTURAL/COMPUTABLE work — block selection,
strong-id entity resolution, deterministic upserts, the run ledger, and cost caps. There is
NO keyword relevance heuristic here: for slice 1 the `source_key` filter (`yc`) IS the
structural relevance gate, and there is NO fuzzy ER — subjects resolve by strong id
(`document_id == f"{source_key}:{native_id}" == "yc:<slug>"`), objects by exact
normalized-name alias or a soft `__unresolved:<norm>` node (never a fuzzy merge).

CREDIT DISCIPLINE ([[noesis-credit-discipline]]): `dry_run` defaults TRUE, so nothing
spends unless a caller explicitly passes `dry_run=False`. Cost is projected up front and
the caps (`max_blocks` / `max_llm_calls` / `max_usd`) ABORT the run BEFORE any LLM call —
a request that would exceed a cap is refused outright, never partially run.

NOT wired into the worker auto-loop or app startup — the only trigger surface is the
explicit CLI `scripts/run_claim_extract.py` (dry-run by default). Default OFF = nothing
calls this automatically.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from api.claimgraph import ClaimGraphStore, normalize_name

# The extractor is imported as a MODULE (not the bound function) so a test can monkeypatch
# `eigen_vertical_tech.claim_extract.extract_typed_claims` and this job picks up the patched
# attribute — keeping every test offline (no network / no live LLM call).
from eigen_vertical_tech import claim_extract
from eigen_vertical_tech.authority import TechAuthorityPolicy
from eigen_vertical_tech.claim_predicates import SLICE1_PREDICATES
from eigen_vertical_tech.evidence_kind import classify as classify_evidence_kind

# Stamped on every claim this job writes so a re-extraction under a newer extractor is
# distinguishable in the ledger / claim rows.
EXTRACTOR_VERSION = "tech-slice1-claim-extract-v1"

# Confidence assigned to a claim that already survived the extractor's three gates
# (predicate-in-active-set, verbatim span-verify, entailment). The extractor emits no
# score of its own; a survivor is a high-confidence grounded claim by construction.
GATED_CLAIM_CONFIDENCE = 0.9

# Entity predicates whose OBJECT is a market CATEGORY (a soft category node), vs. a company
# (resolved / soft-noded). Declared as data (part of the slice-1 vocabulary), not inferred —
# a structural per-predicate mapping, not a semantic heuristic (Rule 18).
_CATEGORY_OBJECT_PREDICATES = frozenset({"operates_in_category"})

_AUTHORITY = TechAuthorityPolicy()


# --------------------------------------------------------------------------- #
# Pure helpers (NO DB / NO network — unit-tested directly)                     #
# --------------------------------------------------------------------------- #
def _parse_facets(f: Any) -> dict:
    """asyncpg may hand back a jsonb column as a dict OR a JSON string — normalize to dict
    (mirrors `app.py::_parse_facets`). Fail-safe → {}."""
    if isinstance(f, dict):
        return f
    try:
        return json.loads(f) if f else {}
    except Exception:  # noqa: BLE001
        return {}


def _slug_of(document_id: str) -> str:
    """The connector's `native_id` = the part after the `source_key:` prefix (structural
    string split, not a heuristic). For a YC block `yc:acme` → `acme`."""
    return document_id.split(":", 1)[1] if ":" in document_id else document_id


def _first_heading(text: str) -> str:
    """First `# ` markdown H1 in the block, or '' — a fallback subject name when the block
    carries no `document_title`."""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _subject_name(document_title: str, text: str, slug: str) -> str:
    """Subject display name: the block's `document_title`, else its first H1 heading, else
    the slug. Never empty (the slug is always present)."""
    return (document_title or "").strip() or _first_heading(text) or slug


def project_cost(
    blocks_considered: int,
    *,
    max_blocks: int,
    max_llm_calls: int,
    max_usd: float,
    price_per_call_usd: float,
) -> dict:
    """Project the LLM cost of extracting `blocks_considered` blocks and evaluate the caps —
    PURE, no side effects, so the cap math is unit-testable with no DB.

    This extractor is ONE call PER BLOCK (it is not the 10-atom batcher), so
    projected_calls == blocks_considered exactly (ceil(n/1)). `est_usd` counts only the
    outer extract calls; the entailment gate's internal calls happen inside the extractor
    and are not separately projected here. Returns the projection plus a list of cap
    violations (`over_caps`) — non-empty means the run must ABORT before any spend.
    """
    projected_calls = blocks_considered  # one extract call per block
    est_usd = round(projected_calls * price_per_call_usd, 6)
    over: list[str] = []
    if blocks_considered > max_blocks:
        over.append(f"blocks_considered {blocks_considered} > max_blocks {max_blocks}")
    if projected_calls > max_llm_calls:
        over.append(f"projected_calls {projected_calls} > max_llm_calls {max_llm_calls}")
    if est_usd > max_usd:
        over.append(f"est_usd {est_usd} > max_usd {max_usd}")
    return {
        "blocks_considered": blocks_considered,
        "projected_calls": projected_calls,
        "est_usd": est_usd,
        "over_caps": over,
        "caps": {"max_blocks": max_blocks, "max_llm_calls": max_llm_calls, "max_usd": max_usd},
    }


def _active_predicates(predicates: list[dict] | None) -> list[dict]:
    """The predicates to constrain extraction to — the caller's list, else the vertical's
    slice-1 registry filtered to status='active'."""
    src = predicates if predicates is not None else SLICE1_PREDICATES
    return [p for p in src if p.get("status", "active") == "active"]


# --------------------------------------------------------------------------- #
# Block selection (read-only, its own short-lived connection)                 #
# --------------------------------------------------------------------------- #
async def _select_blocks(dsn: str, *, source_keys: list[str], tenant_id: str,
                         limit: int | None) -> list[dict]:
    """Select non-empty `rs_block` rows for the given `source_key`s (the structural relevance
    filter). Returns dicts with parsed facets; blocks with empty text are skipped."""
    import asyncpg

    sql = (
        "SELECT document_id, block_id, text, facets, document_title, source_key "
        "FROM rs_block WHERE tenant_id = $1 AND source_key = ANY($2) "
        "ORDER BY document_id, block_id"
    )
    args: list[Any] = [tenant_id, list(source_keys)]
    if limit is not None:
        args.append(int(limit))
        sql += f" LIMIT ${len(args)}"
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(sql, *args)
    finally:
        await conn.close()
    out: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        if not text.strip():  # skip empty blocks (nothing groundable)
            continue
        out.append({
            "document_id": r["document_id"],
            "block_id": r["block_id"],
            "text": text,
            "facets": _parse_facets(r["facets"]),
            "document_title": r["document_title"] or "",
            "source_key": r["source_key"] or "",
        })
    return out


# --------------------------------------------------------------------------- #
# The job                                                                      #
# --------------------------------------------------------------------------- #
async def run_claim_extraction(
    *,
    dsn: str,
    source_keys: list[str],
    tenant_id: str = "demo",
    limit: int | None = None,
    dry_run: bool = True,
    max_blocks: int = 500,
    max_llm_calls: int = 200,
    max_usd: float = 5.0,
    price_per_call_usd: float = 0.01,
    client=None,
    model: str | None = None,
    predicates: list[dict] | None = None,
) -> dict:
    """Scan `rs_block` for `source_keys`, extract typed grounded claims PER BLOCK, resolve
    entities by strong id, and upsert them into the claim graph. Returns a run-summary dict.

    DEFAULT `dry_run=True` — the credit-safe default (shared prod credits). A dry run does
    the full selection + cost projection and records the run, but makes NO LLM call and
    writes NO entities/claims/evidence. Caps ABORT before any spend (see `project_cost`).
    """
    store = ClaimGraphStore(dsn)
    run_id = "run:" + uuid.uuid4().hex
    source_keys_str = ",".join(source_keys)
    active = _active_predicates(predicates)
    try:
        await store.ensure_schema()

        # 1) Select eligible (non-empty) blocks — source_key IS the relevance gate (slice 1).
        blocks = await _select_blocks(dsn, source_keys=source_keys, tenant_id=tenant_id, limit=limit)
        blocks_considered = len(blocks)

        # 2) Cost projection + cap enforcement — BEFORE any LLM call, in BOTH modes.
        proj = project_cost(
            blocks_considered,
            max_blocks=max_blocks, max_llm_calls=max_llm_calls, max_usd=max_usd,
            price_per_call_usd=price_per_call_usd,
        )
        base_params = {
            "source_keys": source_keys, "tenant_id": tenant_id, "limit": limit,
            "dry_run": dry_run, "price_per_call_usd": price_per_call_usd,
            "projected_calls": proj["projected_calls"], "est_usd": proj["est_usd"],
            "caps": proj["caps"],
        }

        if proj["over_caps"]:
            # ABORT: a request over any cap is refused outright — nothing is written.
            await store.record_run(run_id, source_keys=source_keys_str, status="aborted",
                                   params={**base_params, "abort_reason": proj["over_caps"]},
                                   tenant_id=tenant_id)
            await store.finish_run(run_id, status="aborted",
                                   blocks_considered=blocks_considered)
            return {
                "run_id": run_id, "status": "aborted", "dry_run": dry_run,
                "blocks_considered": blocks_considered,
                "projected_calls": proj["projected_calls"],
                "extract_calls": 0, "claims_emitted": 0,
                "est_cost_usd": proj["est_usd"], "abort_reason": proj["over_caps"],
            }

        # 3) DRY RUN (default): record the projection, spend nothing, write nothing.
        if dry_run:
            await store.record_run(run_id, source_keys=source_keys_str, status="dry_run",
                                   params=base_params, tenant_id=tenant_id)
            await store.finish_run(run_id, status="dry_run",
                                   blocks_considered=blocks_considered,
                                   est_cost_usd=proj["est_usd"])
            return {
                "run_id": run_id, "status": "dry_run", "dry_run": True,
                "blocks_considered": blocks_considered,
                "projected_calls": proj["projected_calls"],
                "extract_calls": 0, "claims_emitted": 0,
                "est_cost_usd": proj["est_usd"],
            }

        # 4) LIVE: one extract call per block; resolve + upsert grounded claims.
        await store.record_run(run_id, source_keys=source_keys_str, status="running",
                               params=base_params, tenant_id=tenant_id)
        extract_calls = 0
        claims_emitted = 0
        for b in blocks:
            document_id = b["document_id"]
            source_key = b["source_key"]
            facets = b["facets"]
            slug = _slug_of(document_id)
            subject_id = document_id  # STRONG id: `yc:<slug>` — no fuzzy ER
            subject_name = _subject_name(b["document_title"], b["text"], slug)

            await store.upsert_entity(subject_id, kind="company", name=subject_name,
                                      facets=facets, first_run_id=run_id, tenant_id=tenant_id)
            await store.add_alias(subject_name, subject_id, source=source_key)

            claims = await claim_extract.extract_typed_claims(
                block_text=b["text"], subject_name=subject_name,
                predicates=active, client=client, model=model)
            extract_calls += 1  # ONE call per block, counted whether or not claims came back

            kind = classify_evidence_kind(source_key, facets)
            tier = _AUTHORITY.rank(kind)

            for c in claims:
                predicate = c["predicate"]
                object_kind = c["object_kind"]
                quote = c["quote"]

                if object_kind == "value":
                    object_value = c["object_value"]
                    object_entity_id = ""
                    object_norm = normalize_name(object_value)
                else:  # entity object
                    obj_name = c["object_entity_name"]
                    object_value = ""
                    object_norm = normalize_name(obj_name)
                    if predicate in _CATEGORY_OBJECT_PREDICATES:
                        # object is a market CATEGORY → deterministic soft category node.
                        object_entity_id = "category:" + object_norm
                        await store.upsert_entity(object_entity_id, kind="category",
                                                  name=obj_name, tenant_id=tenant_id)
                    else:
                        # object is a COMPANY → exact-alias resolve, else a soft
                        # `__unresolved:` node (NO fuzzy merge — slice-1 ER policy).
                        resolved = await store.resolve_alias(obj_name)
                        if resolved:
                            object_entity_id = resolved
                        else:
                            object_entity_id = "__unresolved:" + object_norm
                            await store.upsert_entity(object_entity_id, kind="company",
                                                      name=obj_name, tenant_id=tenant_id)

                claim_id = await store.upsert_claim(
                    subject_id=subject_id, predicate=predicate, object_kind=object_kind,
                    object_value=object_value, object_entity_id=object_entity_id,
                    object_norm=object_norm, confidence=GATED_CLAIM_CONFIDENCE,
                    extractor_version=EXTRACTOR_VERSION, tenant_id=tenant_id)
                await store.add_evidence(
                    claim_id, document_id, b["block_id"], quote, source_key=source_key,
                    authority_tier=tier, evidence_kind=kind, tenant_id=tenant_id)
                claims_emitted += 1

        est_cost_usd = round(extract_calls * price_per_call_usd, 6)
        await store.finish_run(
            run_id, status="done",
            blocks_considered=blocks_considered, blocks_relevant=blocks_considered,
            extract_calls=extract_calls, claims_emitted=claims_emitted,
            est_cost_usd=est_cost_usd)
        return {
            "run_id": run_id, "status": "done", "dry_run": False,
            "blocks_considered": blocks_considered,
            "projected_calls": proj["projected_calls"],
            "extract_calls": extract_calls, "claims_emitted": claims_emitted,
            "est_cost_usd": est_cost_usd,
        }
    finally:
        await store.close()
