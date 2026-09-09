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
