"""Postgres-safety sanitizer for materialized block text/facets — strips NUL bytes and invalid
UTF-8 so one bad-byte doc can't fail the whole ingest batch ('invalid byte sequence for encoding
UTF8'), which is how an arXiv job lost all 25 of its docs."""
from eigen_kernel.retrieval.materialize import _pg_safe, _safe_facets


def test_strips_null_bytes():
    assert _pg_safe("a\x00b\x00c") == "abc"


def test_drops_invalid_utf8_surrogates():
    assert _pg_safe("x\udc80y") == "xy"


def test_clean_text_unchanged():
    assert _pg_safe("Quantum error correction — 99.9% fidelity") == "Quantum error correction — 99.9% fidelity"


def test_non_strings_pass_through():
    assert _pg_safe(None) is None
    assert _pg_safe(42) == 42


def test_facets_keys_and_values_sanitized():
    assert _safe_facets({"sector": "quantum", "bad\x00key": "bad\x00val"}) == {
        "sector": "quantum", "badkey": "badval"}


def test_never_return_is_merged_with_a_requests_own_exclusions():
    """A source-level exclusion cannot be forgotten by a caller: content a vertical declares to be
    non-evidence must be unreachable from the research path, whatever the request asks for."""
    from eigen_kernel.contract.dto import RetrievalRequest
    from eigen_kernel.retrieval.postgres import PostgresRetrievalSource

    src = PostgresRetrievalSource("postgresql://x/y", never_return={"source_kind": ("chapter_pointer",)})
    req = RetrievalRequest(tenant_id="t", query="pivot", facets={})
    where, params = src._filter_sql(req)
    assert "source_kind" in params and "chapter_pointer" in [v for p in params if isinstance(p, list) for v in p]

    req2 = RetrievalRequest(tenant_id="t", query="pivot", facets={},
                            exclude_facets={"source_kind": ["sentiment"]})
    where2, params2 = src._filter_sql(req2)
    banned = [v for p in params2 if isinstance(p, list) for v in p]
    assert "chapter_pointer" in banned and "sentiment" in banned      # merged, not replaced
