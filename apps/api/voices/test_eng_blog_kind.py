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


# ── the link, and whose account it is ─────────────────────────────────────────────────────────────
from eigen_vertical_tech import eng_blog_doc
from eigen_vertical_tech import expert_feed_doc
from apps.api.voices.search import moment

_REC = {"link": "https://stripe.com/blog/ledger", "title": "Ledger", "author": "Jane Doe",
        "publication": "Stripe Engineering", "published": "Mon, 01 Sep 2026 00:00:00 GMT",
        "content": '<p>text</p><img src="https://stripe.com/img/lead.png">'}


def test_the_permalink_reaches_the_card():
    # It used to live only in the document body as a "URL: …" line — which build_query filters out
    # as furniture — so the card rendered a summary above "No link published". A summary the reader
    # cannot check is the one thing this product must never ship.
    assert eng_blog_doc.facets(_REC)["url"] == "https://stripe.com/blog/ledger"


def test_the_card_exposes_the_publisher_site():
    assert eng_blog_doc.facets(_REC)["site"] == "https://stripe.com"


def test_a_post_with_no_link_yields_no_url_rather_than_a_broken_one():
    f = eng_blog_doc.facets({**_REC, "link": ""})
    assert "url" not in f and "site" not in f, "never invent a link"


def test_the_lead_image_is_carried_like_an_essay_s():
    assert eng_blog_doc.facets(_REC)["image"] == "https://stripe.com/img/lead.png"


def test_every_voices_builder_puts_its_link_in_facets():
    # The guarantee, not the instance: a card renders from facets, so any voices builder that keeps
    # its link only in prose ships an uncheckable summary.
    for mod in (eng_blog_doc, expert_feed_doc):
        f = mod.facets(_REC)
        assert f.get("url"), f"{mod.__name__} must put its permalink in facets"


def test_moment_passes_url_and_site_through_to_the_card():
    row = {"text": "We rebuilt the ledger.", "source_key": "eng_blog", "document_title": "Ledger",
           "facets": {"source_kind": "corp_eng", "url": "https://stripe.com/blog/ledger",
                      "site": "https://stripe.com", "publication": "Stripe Engineering"}}
    card = moment(row)
    assert card["kind"] == "blog"
    assert card["url"] == "https://stripe.com/blog/ledger"
    assert card["site"] == "https://stripe.com"
    assert card["show"] == "Stripe Engineering"


def test_entities_are_decoded_not_shown_as_markup():
    # The UI escapes what it renders, so an undecoded entity reaches the reader as literal markup:
    # a card read "the web&rsquo;s most popular home pages" in prod.
    out = eng_blog_doc._strip_html("<p>the web&rsquo;s pages &amp;#8212; alt text</p>")
    assert "&rsquo;" not in out and "&#8212;" not in out and "&amp;" not in out
    assert "web’s" in out and "—" in out


def test_a_stub_block_is_not_offered_as_a_moment():
    # A body that survives stripping as "…" renders a card with a link and nothing to read.
    sql, _ = build_query(q="anything")
    assert "length(btrim(text)) >= 30" in sql
    assert "show_notes" in sql, "chapter pointers are legitimately short and must be spared"


def test_a_blog_carries_a_sortable_publication_date():
    # Without published_at a post is invisible under "Everything": the default browse window is
    # "this week" and the filter is (facets->>'published_at') >= $since, which NULL never satisfies.
    # The blog-only filter passes no window, so the category looked fine while the main view was empty.
    f = eng_blog_doc.facets({**_REC, "published": "Mon, 08 Sep 2026 10:00:00 GMT"})
    assert f["published_at"] == "2026-09-08"
    assert f["published"].startswith("Mon, 08 Sep 2026")


def test_the_voices_builders_agree_on_the_facets_a_card_needs():
    # These two builders do nearly the same job and have now diverged four times — permalink, lead
    # image, entity decoding and publication date — each found in production rather than in a test.
    rec = {**_REC, "published": "Mon, 08 Sep 2026 10:00:00 GMT"}
    for key in ("url", "image", "published_at", "publication"):
        for mod in (eng_blog_doc, expert_feed_doc):
            assert mod.facets(rec).get(key), f"{mod.__name__} is missing {key!r}"
