"""Unit tests for canonical citation URLs (`eigen_vertical_tech.links.source_url`).

Focus: EDGAR accession → a RESOLVABLE filing-index URL. Regression for the dead-link
bug where an accession dropped into `filenum=` made EDGAR soft-error ("No matching file
number.") — the accession's leading digits are the filer CIK, so the Archives index URL
is derivable with no facet.

    /Users/sgupta/eigen/.venv/bin/python -m pytest \
        packages/vertical_tech/eigen_vertical_tech/test_links.py -q
"""
from __future__ import annotations

from eigen_vertical_tech.links import source_url


# --------------------------------------------------------------------------- #
# EDGAR — the reported dead-link bug                                           #
# --------------------------------------------------------------------------- #
def test_edgar_accession_without_facet_builds_archives_index_not_filenum() -> None:
    # the exact accession the user hit; no facets (the common call path)
    url = source_url("edgar:0001373715-23-000035")
    # CIK derived from the accession's leading digits (1373715), Archives index page
    assert url == ("https://www.sec.gov/Archives/edgar/data/1373715/"
                   "000137371523000035/0001373715-23-000035-index.html")
    # never the soft-erroring filenum= form
    assert "filenum=" not in url


def test_edgar_accession_derives_cik_even_when_facet_absent_or_wrong() -> None:
    # facet cik is IGNORED when the accession is parseable — the accession self-identifies
    # its filer directory (authoritative), so a stale/subject facet cannot break the link.
    url = source_url("edgar:0001373715-23-000035", facets={"cik": "9999999"})
    assert "/data/1373715/" in url
    assert "filenum=" not in url


def test_edgar_bare_cik_lists_company_filings() -> None:
    url = source_url("edgar:1373715")
    assert url == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1373715"


def test_edgar_facet_cik_fallback_when_accession_unparseable() -> None:
    # a non-accession-shaped native (no leading digits) falls back to the facet cik
    url = source_url("edgar:weird-token", facets={"cik": "0000320193"})
    assert url == ("https://www.sec.gov/Archives/edgar/data/320193/"
                   "weirdtoken/weird-token-index.html")


def test_edgar_no_facet_and_unparseable_returns_none_not_broken_link() -> None:
    # honest gap (no clean page) beats a known-broken filenum= URL
    assert source_url("edgar:weird-token") is None


def test_sec_alias_behaves_like_edgar() -> None:
    assert "/Archives/edgar/data/1373715/" in source_url("sec:0001373715-23-000035")


# --------------------------------------------------------------------------- #
# other sources — light coverage that the switch still routes correctly        #
# --------------------------------------------------------------------------- #
def test_web_document_id_is_the_link_with_text_fragment() -> None:
    url = source_url("https://example.com/post", quote="a grounded quote")
    assert url.startswith("https://example.com/post#:~:text=")


def test_arxiv_openalex_doi_github() -> None:
    assert source_url("arxiv:2401.00001").startswith("https://arxiv.org/abs/2401.00001")
    assert source_url("openalex:W123") == "https://openalex.org/W123"
    assert source_url("crossref:10.1/x") == "https://doi.org/10.1/x"
    assert source_url("github:owner/repo") == "https://github.com/owner/repo"


def test_unknown_source_and_empty_native_return_none() -> None:
    assert source_url("mystery:123") is None
    assert source_url("edgar:") is None
