"""Run the voice connectors into the corpus, then bind guests to companies.

Two settings differ from the generic corpus ingest and both are load-bearing:

  target_chars=0   The generic path coalesces paragraphs into ~1,800-character blocks, which is right
                   for a paper and fatal here: it would weld twenty chapters into one block and every
                   chapter would lose its own timestamp.
  min_chars=1      A chapter title is short. The generic path drops anything under 40 characters as
                   metadata noise, which would delete most of this corpus.

`embedder=None` by default: both model accounts are empty, and a corpus that grows keyword-only today
beats one that does not exist. Vectors backfill later; `rs_block.tsv` is a generated column, so the
rows are searchable the moment they land.
"""
from __future__ import annotations

import logging

from eigen_kernel.runtime.ingest import ingest_connector_to_postgres

from .bind import bind_guest, facet_patch

log = logging.getLogger(__name__)

VOICE_CONNECTORS = ("founder_essay", "show_notes")


async def ingest_voices(manifest, pg_source, *, tenant_id: str, connectors=VOICE_CONNECTORS,
                        limit: int = 60, embedder=None) -> dict:
    """Ingest each voice connector. Returns {connector: blocks}, and never lets one bad feed stop
    the rest — a publisher changing their feed shape must not take the mode down."""
    out: dict[str, int] = {}
    for key in connectors:
        conn = manifest.connectors.get(key)
        if conn is None:
            out[key] = 0
            continue
        try:
            out[key] = await ingest_connector_to_postgres(
                conn, pg_source, tenant_id=tenant_id, embedder=embedder,
                window={"query": "", "limit": limit},
                min_chars=1,        # a chapter title is short; the generic 40-char floor deletes it
                target_chars=0,     # NEVER coalesce: one chapter must stay one block
            )
        except Exception as e:              # noqa: BLE001 — one connector's outage is not an outage
            log.warning("voices: connector %s failed: %s", key, e)
            out[key] = 0
    return out


async def bind_guests(pool, *, table: str = "rs_block", limit: int = 500) -> dict:
    """Stamp `person` / `company_id` onto episode blocks whose guest is a founder we index.

    Idempotent: re-running re-derives the same facets. Episodes that do not bind are left alone and
    stay searchable — being unattached to a company card is the normal case, not a failure.
    """
    async with pool.acquire() as conn:
        # A name shared by two founders is AMBIGUOUS, and the fail-safe for ambiguity is to bind
        # nothing. Keeping the first row would silently attach every "David Smith" episode to
        # whichever company the query happened to return first.
        seen: dict[str, set] = {}
        founders: dict[str, dict] = {}
        for r in await conn.fetch(
                "SELECT f.name, f.company_id, c.name AS company_name "
                "FROM su_founder f JOIN su_company c ON c.id = f.company_id"):
            nm = (r["name"] or "").strip().lower()
            if not nm:
                continue
            seen.setdefault(nm, set()).add(r["company_id"])
            founders[nm] = {"company_id": r["company_id"], "company_name": r["company_name"] or ""}
        for nm, companies in seen.items():
            if len(companies) > 1:
                founders.pop(nm, None)

        rows = await conn.fetch(
            f"SELECT DISTINCT document_id, document_title, facets->>'guest' AS guest "
            f"FROM {table} WHERE source_key = 'show_notes' AND facets->>'guest' IS NOT NULL "
            f"  AND facets->>'person' IS NULL LIMIT $1", int(limit))

        stats = {"episodes": len(rows), "guest_and_company": 0, "guest_only": 0, "unbound": 0}
        for r in rows:
            body = await conn.fetchval(
                f"SELECT string_agg(text, ' ') FROM {table} WHERE document_id = $1", r["document_id"])
            b = bind_guest(title=r["document_title"] or "", body=body or "",
                           guest=r["guest"] or "", founders=founders)
            if not b:
                stats["unbound"] += 1
                continue
            stats[b["basis"]] += 1
            patch = facet_patch(b)
            import json
            await conn.execute(
                f"UPDATE {table} SET facets = facets || $2::jsonb WHERE document_id = $1",
                r["document_id"], json.dumps(patch))
    return stats
