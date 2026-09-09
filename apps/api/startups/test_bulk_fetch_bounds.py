"""A bulk fact pass must not pull whole pages into memory to read the top of them.

Job 72 (`business_model`, limit 30000) died on prod with no progress and no spend: its row fetch asked
for two full `su_page.text` columns per company. A stored page runs to 20,000 characters
(`sources/site.py`), so 30,000 rows is on the order of a gigabyte in one buffer — the job thread was
gone before the first model call. Both readers only ever look at the first few thousand characters, so
the truncation belongs in the query, where the bytes never cross the wire.
"""
from __future__ import annotations

import inspect

from api.startups import pipeline
from api.startups.sources import business_model as bm
from api.startups.sources import careers


def _sql(fn) -> str:
    return inspect.getsource(fn)


def test_the_business_model_fetch_asks_the_database_to_truncate():
    src = _sql(pipeline.run_business_model)
    assert "left(p.text, 1800)" in src and "left(p.text, 1500)" in src, \
        "the pricing/home fetch must be bounded in SQL, not after the whole column is in memory"
    assert "SELECT p.text FROM su_page" not in src


def test_the_careers_fetch_asks_the_database_to_truncate():
    src = _sql(pipeline.run_careers_roles)
    assert "left(p.text," in src, "the careers fetch must be bounded in SQL"
    assert "SELECT c.id, c.name, p.url, p.text" not in src


def test_what_the_query_keeps_is_at_least_what_the_reader_reads():
    # A bound that cuts below what the extractor sends the model would silently change answers.
    assert 1800 + 1500 >= bm.MAX_TEXT
    # the careers bound is the constant itself, interpolated — not a copy of its value that can drift
    assert "left(p.text, {careers.MAX_PAGE_CHARS})" in _sql(pipeline.run_careers_roles)
    assert careers.MAX_PAGE_CHARS >= 1000


# ---------------------------------------------------------------- the one-liner that outlived its truth
def test_finding_a_website_retires_the_note_that_says_there_is_none():
    """A filing-only card read "Other Energy company in Marlborough, MA (from SEC Form D filings; no
    website on record yet)" while the row carried https://xl-batteries.com. 6,714 companies gained a
    website from the lookup pass and every one of them kept the sentence denying it."""
    created = f"Other Energy company in Marlborough, MA {pipeline.FORMD_NOTE_NO_SITE}"
    assert pipeline.FORMD_NOTE_NO_SITE in created
    repaired = created.replace(pipeline.FORMD_NOTE_NO_SITE, pipeline.FORMD_NOTE)
    assert "no website" not in repaired
    assert repaired.endswith(pipeline.FORMD_NOTE)
    # the repair runs on every pass, so it must be a no-op the second time
    assert repaired.replace(pipeline.FORMD_NOTE_NO_SITE, pipeline.FORMD_NOTE) == repaired


def test_the_lookup_pass_repairs_rows_it_wrote_before_this_code_existed():
    src = _sql(pipeline.run_discover_sites)
    assert "replace(one_liner" in src
    assert "WHERE website <> ''" in src, "the backfill must reach rows an earlier pass already gave a website"
