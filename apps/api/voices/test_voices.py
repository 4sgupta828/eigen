"""The Voices gates. Every test here is a way the feature could lie, written before it can."""
from __future__ import annotations

from eigen_vertical_tech import show_notes_doc

from api.voices import bind, search

FOUNDERS = {
    "ryan petersen": {"company_id": "flexport.com", "company_name": "Flexport"},
    "tony xu": {"company_id": "doordash.com", "company_name": "DoorDash"},
    "jane roe": {"company_id": "inside.com", "company_name": "Inside"},
}


# ── binding ──────────────────────────────────────────────────────────────────────────────────────
def test_a_guest_named_in_the_title_with_their_company_binds():
    b = bind.bind_guest(title="20VC: Why Remote Work is Fraud with Ryan Petersen, CEO @ Flexport",
                        body="Ryan runs Flexport.", guest="Ryan Petersen", founders=FOUNDERS)
    assert b["basis"] == "guest_and_company" and b["company_id"] == "flexport.com"
    assert bind.facet_patch(b)["company_id"] == "flexport.com"


def test_a_mention_in_the_body_never_binds():
    # THE TRAP, measured on a real episode: the guest is one person, the body names another founder
    # and their company. A body mention must not put words in that person's mouth.
    # The guest is derived the way the pipeline derives it, so the test cannot bypass the extractor.
    title = "Gokul Rajaram - Lessons from Investing in 700 Startups"
    body = "We also discuss what Tony Xu did at DoorDash in 2020."
    guest = show_notes_doc.guest_from_title(title)
    assert guest == "Gokul Rajaram"                 # the extractor names the guest, not the mention
    assert bind.bind_guest(title=title, body=body, guest=guest, founders=FOUNDERS) == {}
    # and even if something upstream handed us the mentioned person, the title gate still refuses
    assert bind.bind_guest(title=title, body=body, guest="Tony Xu", founders=FOUNDERS) == {}


def test_a_collective_is_not_a_person():
    b = bind.bind_guest(title="Founders on the hard years", body="", guest="Founders",
                        founders={"founders": {"company_id": "x.com", "company_name": "Xco"}})
    assert b == {}


def test_a_common_word_company_never_attaches_to_a_card():
    # 'Inside' is a real company in the index and also an ordinary English word. The guest binds;
    # the company does not, so the episode stays off the company card.
    b = bind.bind_guest(title="Building in public with Jane Roe", body="She works inside a big team.",
                        guest="Jane Roe", founders=FOUNDERS)
    assert b["basis"] == "guest_only" and b["company_id"] == ""
    assert "company_id" not in bind.facet_patch(b)


def test_token_matching_does_not_match_inside_a_longer_word():
    assert bind.name_in("ray", "Ray Kurzweil") is True
    assert bind.name_in("ray", "Murray Hill") is False


# ── moments ──────────────────────────────────────────────────────────────────────────────────────
CHAPTER_ROW = {
    "document_id": "ep7", "block_id": "b1", "document_title": "20VC — the pivot", "source_key": "show_notes",
    "text": "[00:13:00] How the first product died — https://show.fm/ep/7?t=780",
    "facets": {"source_kind": "chapter_pointer", "publication": "20VC", "guest": "Ryan Petersen",
               "episode_url": "https://show.fm/ep/7"},
}
ESSAY_ROW = {
    "document_id": "p1", "block_id": "b2", "document_title": "What I got wrong about seed pricing",
    "source_key": "founder_essay", "text": "We priced our seed round too high and it cost a year.",
    "facets": {"source_kind": "essay", "author": "Fred Wilson", "voice_role": "investor",
               "publication": "AVC", "year": "2026"},
}


def test_a_chapter_moment_carries_its_offset_and_is_not_quotable():
    m = search.moment(CHAPTER_ROW)
    assert m["kind"] == "chapter" and m["t_start"] == 780
    assert m["url"].endswith("?t=780")
    assert m["quotable"] is False                       # THE TRAP: never rendered as a quotation
    assert "listen from this point" in m["register"]
    assert m["text"] == "How the first product died"    # the link is stripped out of the words


def test_an_essay_moment_is_quotable_and_names_its_author_and_role():
    m = search.moment(ESSAY_ROW)
    assert m["kind"] == "essay" and m["quotable"] is True
    assert m["speaker"] == "Fred Wilson" and m["role"] == "investor"
    assert m["t_start"] == 0 and m["published"] == "2026"


def test_search_sql_filters_to_the_voice_corpus_and_survives_an_empty_query():
    sql, params = search.build_query(q="pivot after a failed series a", limit=10)
    assert "source_key = ANY($1)" in sql and "plainto_tsquery" in sql and "ts_rank" in sql
    assert params[0] == list(search.VOICE_SOURCE_KEYS) and params[-1] == 10

    sql2, params2 = search.build_query(q="   ", limit=5)
    assert "plainto_tsquery" not in sql2 and "created_at DESC" in sql2   # newest, not an error


def test_search_can_be_scoped_to_one_company_or_one_kind():
    sql, params = search.build_query(q="layoffs", company_id="flexport.com", kinds=("chapter",))
    assert "facets->>'company_id'" in sql and "flexport.com" in params
    assert params[0] == ["show_notes"]


def test_an_unknown_filter_narrows_to_nothing_rather_than_widening():
    sql, params = search.build_query(q="pivot", kinds=("chapter", "nonsense"))
    assert params[0] == ["show_notes"]              # the good kind survives, the bad one adds nothing
    sql2, params2 = search.build_query(q="pivot", kinds=("nonsense",))
    assert params2[0] == []                         # nothing matches, rather than everything


def test_the_company_strip_asks_for_one_moment_per_episode():
    sql, _ = search.build_query(q="", company_id="flexport.com", limit=4, per_document=True)
    assert "DISTINCT ON (document_id)" in sql
