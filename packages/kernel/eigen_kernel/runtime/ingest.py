"""Ingest a vertical's connector into a Postgres corpus.

Runs the full pipeline — discover → fetch → store → parse → block → embed — into
a scratch in-memory corpus repo, then materializes the embedded blocks into a
PostgresRetrievalSource (the searchable index). The embedder used here MUST match
the query embedder + the pg vector dimension (align both to OpenAI 1536 in prod).
"""
from __future__ import annotations

from eigen_kernel.contract.protocols import Connector
from eigen_kernel.corpus.parsers import ParserRegistry, default_registry
from eigen_kernel.corpus.repository import InMemoryCorpusRepository
from eigen_kernel.ingestion.pipeline import embed_pending, index_document, ingest_source
from eigen_kernel.ingestion.storage import InMemoryObjectStore, ObjectStore
from eigen_kernel.providers.embeddings import Embedder
from eigen_kernel.retrieval.materialize import materialize_to_postgres


async def ingest_connector_to_postgres(
    connector: Connector,
    pg_source,
    *,
    tenant_id: str,
    embedder: Embedder,
    workspace_id: str | None = None,
    parsers: ParserRegistry | None = None,
    window: dict | None = None,
    object_store: ObjectStore | None = None,
    embed_batch_size: int = 256,
    facet_overrides: dict | None = None,   # stamped onto every block (e.g. {"source_country": "IN"})
) -> int:
    """Ingest one connector into the pg corpus. Returns blocks materialized.

    Raw fetched artifacts land in `object_store` (pass an S3ObjectStore to persist
    them to R2/S3; defaults to in-memory). The searchable index goes to `pg_source`.
    """
    store = object_store or InMemoryObjectStore()
    repo = InMemoryCorpusRepository()
    parsers = parsers or default_registry()

    await ingest_source(connector, store, repo, tenant_id=tenant_id,
                        workspace_id=workspace_id, window=window)
    # parse + block every doc (defer embedding), then embed the whole corpus in
    # ONE batched pass — O(blocks/batch) API calls instead of one per document.
    for doc in repo.iter_documents():
        index_document(doc, store.get(doc.sha256), parsers=parsers, repo=repo)
    embed_pending(repo, embedder, batch_size=embed_batch_size)

    await pg_source.ensure_schema()
    return await materialize_to_postgres(repo, pg_source, facet_overrides=facet_overrides)
