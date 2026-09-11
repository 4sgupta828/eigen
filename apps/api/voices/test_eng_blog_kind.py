"""A company's own engineering blog is first-person startup content — and an interested party.

It belongs in Voices (the same act: the people who built the thing, writing about it), but NOT as an
essay. `kind_of` used to fall through to "essay" for anything it did not recognise, which would have
filed a company describing its own architecture beside an independent investor essay and erased the
tier difference the corpus already encodes (`corp_eng` → technical_signal, strictly below
`expert_analysis`). These tests pin the separation.
"""
from apps.api.voices.search import (
    VOICE_SOURCE_KEYS, build_query, kind_of, is_quotable,
)
from apps.api.voices.ingest import VOICE_CONNECTORS


def test_eng_blog_is_ingested_into_the_voices_tenant():
    # corp_eng existed in the research corpus but never reached the Voices tenant, so the category
    # would have rendered empty no matter what the UI offered.
    assert "eng_blog" in VOICE_CONNECTORS
    assert "eng_blog" in VOICE_SOURCE_KEYS


def test_a_company_blog_is_its_own_kind_not_an_essay():
    assert kind_of("corp_eng", "eng_blog") == "blog"
    # either signal alone is enough — the facet or the source key
    assert kind_of("corp_eng", "") == "blog"
    assert kind_of("", "eng_blog") == "blog"


def test_a_founder_essay_is_still_an_essay():
    assert kind_of("essay", "founder_essay") == "essay"
    assert kind_of("essay", "expert_feed") == "essay"


def test_the_chapter_kinds_are_untouched():
    assert kind_of("chapter_pointer", "show_notes") == "podcast"
    assert kind_of("chapter_pointer", "youtube_chapters") == "video"


def test_a_blog_is_quotable():
    # Unlike a chapter pointer (a publisher's own contents list), a blog post is the writing itself.
    assert is_quotable("corp_eng") is True


def test_the_blog_filter_selects_only_engineering_blogs():
    sql, params = build_query(q="inference latency", kinds=("blog",))
    keys = [p for p in params if isinstance(p, list)]
    assert keys and "eng_blog" in keys[-1], "the blog filter must reach eng_blog"
    assert "founder_essay" not in keys[-1], "a blog filter must not widen back into essays"


def test_the_essay_filter_does_not_pull_in_company_blogs():
    sql, params = build_query(q="pivot", kinds=("essay",))
    keys = [p for p in params if isinstance(p, list)]
    assert "eng_blog" not in keys[-1], "an essay filter must stay independent writing"


def test_an_unrecognised_kind_still_narrows_to_nothing():
    # The standing rule from the voices panel review: a typo'd filter must never widen the search.
    sql, params = build_query(q="x", kinds=("blogs",))   # note the typo
    keys = [p for p in params if isinstance(p, list)]
    assert keys[-1] == [], "an unknown kind must match nothing, not everything"


def test_the_engineering_blog_byline_is_excluded():
    # eng_blog_doc writes a byline carrying its register in parentheses; the splitter indexes it like
    # any paragraph, so without this a card would open with "Stripe — Jane Doe, 2026-09-01".
    sql, _ = build_query(q="anything")
    assert "company engineering blog" in sql
