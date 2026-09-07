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
               "publication": "AVC", "year": "2026", "published_at": "2026-09-03",
               "url": "https://avc.com/seed-pricing"},
}


def test_a_chapter_moment_carries_its_offset_and_is_not_quotable():
    m = search.moment(CHAPTER_ROW)
    assert m["kind"] == "podcast" and m["t_start"] == 780
    assert m["url"].endswith("?t=780")
    assert m["quotable"] is False                       # THE TRAP: never rendered as a quotation
    assert "listen from this point" in m["register"]
    assert m["text"] == "How the first product died"    # the link is stripped out of the words


def test_an_essay_moment_is_quotable_and_names_its_author_and_role():
    m = search.moment(ESSAY_ROW)
    assert m["kind"] == "essay" and m["quotable"] is True
    assert m["speaker"] == "Fred Wilson" and m["role"] == "investor"
    assert m["t_start"] == 0 and m["published"] == "2026-09-03" and m["year"] == "2026"
    assert m["url"] == "https://avc.com/seed-pricing"      # a card must be able to send you to read it


def test_search_sql_filters_to_the_voice_corpus_and_survives_an_empty_query():
    sql, params = search.build_query(q="pivot after a failed series a", limit=10)
    assert "source_key = ANY($1)" in sql and "to_tsquery" in sql and "ts_rank" in sql
    assert params[0] == list(search.VOICE_SOURCE_KEYS) and params[-1] == 10

    sql2, params2 = search.build_query(q="   ", limit=5)
    assert "tsquery" not in sql2 and "created_at DESC" in sql2           # newest, not an error


def test_search_can_be_scoped_to_one_company_or_one_kind():
    sql, params = search.build_query(q="layoffs", company_id="flexport.com", kinds=("chapter",))
    assert "facets->>'company_id'" in sql and "flexport.com" in params
    assert params[0] == ["show_notes", "youtube_chapters"]   # both chapter sources, podcast and video


def test_an_unknown_filter_narrows_to_nothing_rather_than_widening():
    sql, params = search.build_query(q="pivot", kinds=("chapter", "nonsense"))
    assert params[0] == ["show_notes", "youtube_chapters"]  # the good kind survives, the bad adds nothing
    sql2, params2 = search.build_query(q="pivot", kinds=("nonsense",))
    assert params2[0] == []                         # nothing matches, rather than everything


def test_the_company_strip_asks_for_one_moment_per_episode():
    sql, _ = search.build_query(q="", company_id="flexport.com", limit=4, per_document=True)
    assert "DISTINCT ON (document_id)" in sql


def test_dedupe_keeps_a_result_set_readable():
    ms = [{"id": "d1::a", "text": "The same sidebar of post titles"},
          {"id": "d2::a", "text": "the same   SIDEBAR of post titles"},   # same text, other document
          {"id": "d1::b", "text": "A real passage about pricing"},
          {"id": "d1::c", "text": "A third passage from the same essay"},
          {"id": "d3::a", "text": "Someone else entirely"}]
    out = search.dedupe(ms, per_document=2, limit=10)
    assert [m["id"] for m in out] == ["d1::a", "d1::b", "d3::a"]
    # the duplicate text is gone, and no single document holds more than two slots


def test_every_voice_query_excludes_boilerplate():
    sql, _ = search.build_query(q="pivot")
    assert "NOT (facets ? 'boilerplate')" in sql


def test_a_question_phrased_as_a_sentence_still_finds_things():
    # plainto_tsquery requires EVERY word, so "pivot after a failed round" matched one block in the
    # entire corpus. The terms are OR-ed and ranked instead, and the noise words are dropped.
    assert search.terms("How do I price a seed round after a failed pivot?") == \
        ["price", "seed", "round", "failed", "pivot"]
    sql, params = search.build_query(q="pivot after a failed round")
    assert "to_tsquery" in sql and "plainto_tsquery" not in sql
    assert "pivot | failed | round" in params


def test_an_all_stopword_query_degrades_to_newest_rather_than_erroring():
    assert search.terms("what about the and of") == []
    sql, _ = search.build_query(q="what about the and of")
    assert "tsquery" not in sql and "created_at DESC" in sql


def test_a_chapter_with_no_link_does_not_keep_the_dangling_separator():
    row = dict(CHAPTER_ROW, text="[00:04:29] Sales agent —",
               facets={"source_kind": "chapter_pointer", "publication": "The Startup Ideas"})
    m = search.moment(row)
    assert m["text"] == "Sales agent" and m["t_start"] == 269


def test_one_prolific_writer_cannot_own_the_whole_result_set():
    ms = [{"id": f"d{i}::a", "text": f"passage {i}", "speaker": "Elad Gil", "show": "Elad Blog"}
          for i in range(6)]
    ms.append({"id": "dx::a", "text": "someone else", "speaker": "Hunter Walk", "show": "hunterwalk"})
    out = search.dedupe(ms, per_source=3, limit=5)
    assert [m["speaker"] for m in out[:4]] == ["Elad Gil", "Elad Gil", "Elad Gil", "Hunter Walk"]
    assert len(out) == 5           # the held-back passages still fill the set rather than vanish


def test_a_moment_always_offers_somewhere_to_go():
    """A card with no link is a dead end. Essays carry `url`, episodes carry `episode_url`, and a
    chapter's own line carries the deep link — moment() must read whichever exists."""
    essay = search.moment({"document_id": "p", "block_id": "b", "document_title": "t",
                           "source_key": "founder_essay", "text": "words",
                           "facets": {"source_kind": "essay", "url": "https://x.com/post"}})
    assert essay["url"] == "https://x.com/post"
    ep = search.moment({"document_id": "e", "block_id": "b", "document_title": "t",
                        "source_key": "show_notes", "text": "[00:15:35] A lesson",
                        "facets": {"source_kind": "chapter_pointer",
                                   "episode_url": "https://cdn.fm/ep.mp3"}})
    # an audio enclosure takes a media fragment, so the player opens at the moment itself
    assert ep["url"] == "https://cdn.fm/ep.mp3#t=935" and ep["t_start"] == 935


def test_a_moment_nobody_can_open_ranks_below_one_they_can():
    sql, _ = search.build_query(q="fundraising")
    assert "facets ? 'url' OR facets ? 'episode_url'" in sql and "0.7" in sql


def test_a_moment_says_how_it_can_be_played():
    yt = search.moment({"document_id": "y", "block_id": "b", "document_title": "t",
                        "source_key": "youtube_chapters", "text": "[00:04:27] Building it by accident",
                        "facets": {"source_kind": "chapter_pointer", "video_id": "abc123",
                                   "episode_url": "https://www.youtube.com/watch?v=abc123",
                                   "image": "https://i.ytimg.com/vi/abc123/mqdefault.jpg"}})
    assert yt["media"] == {"kind": "youtube", "id": "abc123", "t": 267}
    assert yt["image"].endswith("mqdefault.jpg")

    pod = search.moment({"document_id": "p", "block_id": "b", "document_title": "t",
                         "source_key": "show_notes", "text": "[00:13:00] The pivot",
                         "facets": {"source_kind": "chapter_pointer",
                                    "audio_url": "https://cdn.fm/ep.mp3"}})
    assert pod["media"] == {"kind": "audio", "url": "https://cdn.fm/ep.mp3", "t": 780}

    essay = search.moment({"document_id": "e", "block_id": "b", "document_title": "t",
                           "source_key": "founder_essay", "text": "words",
                           "facets": {"source_kind": "essay", "url": "https://x.com/p"}})
    assert essay["media"] == {}          # an essay is read, not played


def test_a_favourite_stores_only_what_a_card_renders():
    from api.voices import favorites
    m = {"id": "d::b", "kind": "chapter", "text": "The pivot", "show": "20VC", "t_start": 780,
         "image": "https://a/b.jpg", "media": {"kind": "audio", "url": "u", "t": 780},
         "score": 0.42, "facets": {"internal": "x"}}
    snap = favorites.snapshot_of(m)
    assert snap["id"] == "d::b" and snap["t_start"] == 780 and snap["media"]["kind"] == "audio"
    assert "score" not in snap and "facets" not in snap   # never freeze what we may re-derive


def test_a_named_person_links_to_their_profile_or_to_an_honest_search():
    from api.voices import people
    ms = [{"speaker": "Ryan Petersen", "show": "20VC", "bind_basis": "guest_and_company"},
          {"speaker": "Someone Unknown", "show": "20VC"},
          {"speaker": "", "show": "20VC"}]
    people.decorate(ms, {"Ryan Petersen": {"linkedin": "https://linkedin.com/in/typeryan", "basis": "index"}})
    assert ms[0]["person"]["linkedin"].endswith("typeryan") and ms[0]["person"]["basis"] == "index"
    # nobody we hold → a LABELLED search on each network's PEOPLE directory, never a guessed URL
    sr = ms[1]["person"]["search"]
    assert ms[1]["person"]["basis"] == "search"
    assert "linkedin.com/search/results/people" in sr["linkedin"]
    assert "x.com/search?f=user" in sr["twitter"]
    assert "linkedin.com/in/" not in sr["linkedin"]                  # never a guessed profile path
    assert "person" not in ms[2]                     # no name, no link


def test_podcasts_and_videos_are_separate_kinds():
    assert search.kind_of("chapter_pointer", "youtube_chapters") == "video"
    assert search.kind_of("chapter_pointer", "show_notes") == "podcast"
    assert search.is_pointer("video") and search.is_pointer("podcast")
    assert not search.is_pointer("essay")
    sql, params = search.build_query(q="pivot", kinds=("video",))
    assert params[0] == ["youtube_chapters"]
    sql2, params2 = search.build_query(q="pivot", kinds=("podcast",))
    assert params2[0] == ["show_notes"]


def test_a_common_name_alone_never_earns_a_profile_link():
    """The index holds one Matthew Smith; the world holds thousands. Without this episode also
    naming his company, a direct link would send the reader to a stranger."""
    from api.voices import people
    ms = [{"speaker": "Matthew Smith", "show": "Invest Like the Best"}]      # no bind_basis
    people.decorate(ms, {"Matthew Smith": {"linkedin": "https://linkedin.com/in/matthew-smith250",
                                           "basis": "index"}})
    assert ms[0]["person"]["basis"] == "search"
    assert "matthew-smith250" not in json_dumps(ms[0])
    assert "does not confirm" in ms[0]["person"]["why"]


def json_dumps(o):
    import json
    return json.dumps(o)


def test_a_profile_search_looks_for_the_person_not_the_show():
    """Searching the name plus the show found the episode — the one thing the reader already has."""
    from api.voices import people
    ms = [{"speaker": "Dara Khosrowshahi", "show": "Invest Like the Best"}]
    people.decorate(ms, {})
    sr = ms[0]["person"]["search"]
    assert "Khosrowshahi" in sr["linkedin"] and "Invest" not in sr["linkedin"]
    assert "Khosrowshahi" in sr["twitter"] and "Invest" not in sr["twitter"]


def test_a_browse_orders_by_the_pieces_own_date_not_by_when_we_ingested_it():
    """With no query the feed used to order by created_at — when OUR job touched the row, which
    means nothing to a reader and put whatever ran last on top."""
    sql, params = search.build_query(q="", limit=10)
    order = sql.split("ORDER BY")[-1]
    assert "facets->>'published_at' DESC" in order
    assert order.index("published_at") < order.index("created_at")  # ingest time only breaks ties


def test_a_window_filters_by_publication_date():
    sql, params = search.build_query(q="", since="2026-09-01", limit=10)
    assert "(facets->>'published_at') >= " in sql and "2026-09-01" in params


def test_most_watched_only_considers_rows_that_carry_a_view_count():
    sql, params = search.build_query(q="", order="watched", limit=10)
    assert "(facets->>'views')::bigint DESC" in sql
    assert any(p == r"^\d+$" for p in params)      # rows with no number are excluded, not treated as 0


def test_a_moment_carries_the_platforms_view_count_when_there_is_one():
    m = search.moment({"document_id": "y", "block_id": "b", "document_title": "t",
                       "source_key": "youtube_chapters", "text": "[00:04:27] A lesson",
                       "facets": {"source_kind": "chapter_pointer", "views": "39103",
                                  "published_at": "2026-09-07", "video_id": "abc"}})
    assert m["views"] == 39103 and m["published_at"] == "2026-09-07"
    podcast = search.moment({"document_id": "p", "block_id": "b", "document_title": "t",
                             "source_key": "show_notes", "text": "[00:13:00] A lesson",
                             "facets": {"source_kind": "chapter_pointer"}})
    assert podcast["views"] == 0                    # podcasts publish none; we invent none


def test_document_furniture_never_surfaces_as_a_moment():
    """A document's byline and URL lines are paragraphs too, and they surfaced as moments reading
    '20VC, 2026-09-07T13:59:48'. A pointer's real content always opens with its timestamp."""
    sql, _ = search.build_query(q="", limit=5)
    assert "text NOT LIKE 'URL: %'" in sql
    assert "OR text LIKE '[%'" in sql


def test_a_byline_paragraph_never_surfaces_as_a_moment():
    sql, _ = search.build_query(q="", limit=5)
    assert "(expert analysis / opinion" in sql and "press report" in sql


def test_the_per_piece_feed_keeps_the_real_ordering():
    """Sorting the deduplicated set by score put every browse row at 0.0, so it fell through to
    document_id and 'founder_essay:…' beat 'show_notes:…' alphabetically — video never appeared."""
    sql, _ = search.build_query(q="", limit=5, per_document=True)
    outer = sql.rsplit(") s ", 1)[1]
    assert "published_at" in outer and "document_id LIMIT" not in outer

    # …and with a query it orders by the SELECTED alias: `tsv` is a generated column the inner
    # query never returns, so recomputing the rank outside it is invalid SQL.
    sql2, _ = search.build_query(q="pivot", limit=5, per_document=True)
    outer2 = sql2.rsplit(") s ", 1)[1]
    assert outer2.strip().startswith("ORDER BY score DESC") and "tsv" not in outer2


def test_a_card_never_shows_a_bare_year_as_a_date():
    """The reported contradiction: a card read "31 Dec 2025" inside a "published this month" feed.
    The essay had no `published` facet, so the moment fell back to the YEAR, "2026", and a browser
    west of UTC rendered that as 31 Dec 2025 — a wrong date arguing with a correct filter."""
    m = search.moment({"document_id": "e", "block_id": "b", "document_title": "t",
                       "source_key": "founder_essay", "text": "words",
                       "facets": {"source_kind": "essay", "year": "2026",
                                  "published_at": "2026-09-07",
                                  "published": "Sun, 07 Sep 2026 12:00:00 GMT"}})
    assert m["published"] == "2026-09-07"          # the exact date wins
    assert m["year"] == "2026"                     # the year is still available, separately

    # with no exact date, the feed's own string is shown — never the year dressed as a date
    m2 = search.moment({"document_id": "e", "block_id": "b", "document_title": "t",
                        "source_key": "founder_essay", "text": "words",
                        "facets": {"source_kind": "essay", "year": "2026"}})
    assert m2["published"] == "" and m2["year"] == "2026"


def test_podcasts_rank_by_having_a_named_guest_since_they_publish_no_view_count():
    """'Most watched' can never rank a podcast: no podcast feed publishes a view count, so that
    order returns an empty page. What is actually useful is the interviews rather than the weekly
    news round-ups, which is a property of the episode and not a popularity guess."""
    sql, params = search.build_query(q="", order="guest", kinds=("podcast",))
    assert "facets ? 'guest'" in sql
    assert "views" not in sql.split("WHERE")[1].split("ORDER BY")[0]
    assert params[0] == ["show_notes"]


def test_a_question_is_answered_strictly_before_it_is_relaxed():
    """'Physical AI startups building Robotic systems' OR-ed six words, four of which are generic in
    a startup corpus, and returned the longest essays containing 'building'."""
    t = search.terms("Physical AI startups building Robotic systems")
    assert t == ["physical", "ai", "robotic"]          # the generic words are dropped

    ladder = search.tsqueries(t)
    assert [label for label, _ in ladder] == ["all words", "most words", "any word"]
    assert ladder[0][1] == "physical & ai & robotic"   # strictest rung asks for all of them
    assert " | " in ladder[1][1] and " & " in ladder[1][1]   # then any two of them
    assert ladder[2][1] == "physical | ai | robotic"


def test_a_question_made_only_of_generic_words_still_searches():
    # dropping every word would leave nothing to search, so the generic ones are all we have
    assert search.terms("founders building companies") == ["founders", "building", "companies"]


def test_a_supplied_tsquery_is_what_gets_run():
    sql, params = search.build_query(q="physical ai robotic", tsquery="physical & robotic")
    assert "physical & robotic" in params and "physical | ai | robotic" not in params


def test_engineering_transcripts_are_not_this_modes_material():
    """The kernel's older podcast connector holds Changelog-network transcripts: practitioner talk,
    but not founders and investors on building companies. Their fragments rendered with no show and
    no speaker and diluted every result."""
    assert "podcast" not in search.VOICE_SOURCE_KEYS
    sql, params = search.build_query(q="robotics")
    assert "podcast" not in params[0]
