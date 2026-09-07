"""Chapter pointers: what they are, and — more importantly — what they must never become.

Three of the spec's eval traps live here: a chapter must never read as a quotation, a guest must
never be inferred from body copy, and a stray time in prose must never masquerade as a chapter.
"""
from __future__ import annotations

import asyncio

from eigen_vertical_tech import show_notes_doc as D
from eigen_vertical_tech.authority import TechAuthorityPolicy
from eigen_vertical_tech.connectors.show_notes import ShowNotesConnector
from eigen_vertical_tech.evidence_kind import classify

NOTES = ("<p>(00:00) Welcome to the show<br/>"
         "(02:25) How the first product died<br/>"
         "13:00 Is Series A the hardest stage to raise<br/>"
         "(01:02:33) Lightning round</p>")


def test_chapters_carry_offsets_in_order():
    chs = D.chapters(NOTES)
    assert [c["t_start"] for c in chs] == [0, 145, 780, 3753]
    assert chs[2]["title"] == "Is Series A the hardest stage to raise"
    assert chs[3]["stamp"] == "01:02:33"


def test_a_stray_time_in_prose_is_not_a_chapter_list():
    # Backwards or lone timestamps are prose ("we shipped at 9:00, rewrote it by 3:00"), not chapters.
    assert D.chapters("We shipped at 9:00 in the morning and rewrote it by 3:00 the next day.") == []
    assert D.chapters("(00:30) Intro only") == []                 # below MIN_CHAPTERS


def test_deep_link_points_at_the_moment_on_the_publishers_site():
    assert D.deep_link("https://show.fm/ep/7", 780) == "https://show.fm/ep/7?t=780"
    assert D.deep_link("https://show.fm/ep/7?utm=1", 780) == "https://show.fm/ep/7?utm=1&t=780"
    assert D.deep_link("", 780) == ""                              # no link → no invented one


def test_guest_comes_from_the_title_never_the_body():
    # TRAP: the body names a different founder and their company. Binding it would put a quote in
    # the wrong person's mouth — the failure measured on a real Invest Like the Best episode.
    rec = {"title": "20VC: Why Remote Work is White Collar Fraud with Ryan Petersen, CEO @ Flexport",
           "summary": NOTES + "<p>We also discuss Tony Xu and what DoorDash did in 2020.</p>",
           "link": "https://show.fm/ep/7", "guid": "ep7", "publication": "20VC"}
    assert D.facets(rec)["guest"] == "Ryan Petersen"
    assert "Tony Xu" not in D.to_markdown(rec)
    assert D.guest_from_title("A show about nothing in particular") == ""


def test_a_chapter_is_a_pointer_and_is_never_evidence():
    # TRAP: "(02:25) How the first product died" must never be citable as "the founder said the
    # product died". The tier is the structural bar, not a prompt asking nicely.
    kind = classify("show_notes", D.facets({"title": "x", "publication": "20VC"}))
    pol = TechAuthorityPolicy()
    assert kind == "pointer"
    assert pol.is_evidence(kind) is False
    assert pol.is_controlling(kind) is False
    assert pol.rank(kind) == 0
    assert pol.is_evidence("sentiment_signal") is True             # only pointers are barred


def test_markdown_is_one_paragraph_per_chapter_and_says_it_is_not_speech():
    rec = {"title": "Lenny: the pivot with Jane Doe", "summary": NOTES, "link": "https://s.fm/1",
           "guid": "1", "publication": "Lenny's Podcast", "published": "Tue, 02 Sep 2026 10:00:00 GMT"}
    md = D.to_markdown(rec)
    assert "Nothing here is a quotation" in md
    bodies = [p for p in md.split("\n\n") if p.startswith("[")]
    assert len(bodies) == 4                                        # one paragraph → one block
    assert all("?t=" in p for p in bodies[1:])                     # every chapter deep-links


def test_connector_skips_episodes_with_no_chapter_list():
    good = {"guid": "a", "title": "Show with Jane Doe", "summary": NOTES, "link": "https://s.fm/a",
            "publication": "Show"}
    bare = {"guid": "b", "title": "Show with John Roe", "summary": "<p>A great chat.</p>",
            "link": "https://s.fm/b", "publication": "Show"}
    c = ShowNotesConnector(episodes=[good, bare])
    ents = asyncio.run(c.discover_entities({}))
    assert [e.native_id for e in ents] == ["a"]                    # the chapter-less episode is gone
    assert ents[0].facets["guest"] == "Jane Doe"


# Real episode titles taken from the prod corpus on 2026-09-07, with the guest a human would name.
# The first version of the extractor got 9 of these 16 right and produced "Netic Founder Me",
# "Chasing Trillion" and "Arm CEO Rene" — a name that is really a company, a sentence, and a role.
REAL_TITLES = [
    ("20VC: How to Build Your Own Data Center | How ElevenLabs Leapfrogged with Cliff Weitzman", "Cliff Weitzman"),
    ("Building an Autonomous Enterprise for Real-World Services with Netic Founder Melisa Tokmak", "Melisa Tokmak"),
    ("Chasing Trillion-Dollar Companies, Founder Ambition, Token Budgets, and Regulatory Capture with Sam Altman", "Sam Altman"),
    ("Redefining Chip Architecture with Arm CEO Rene Haas", "Rene Haas"),
    ("Rethinking Legacy Data Infrastructure with Eon Co-Founders Ofir Ehrlich and Gonen Stein", "Ofir Ehrlich"),
    ("Sam Altman - How to Make an Abundant Future - [Invest Like the Best, EP.484]", "Sam Altman"),
    ("Ben Thompson on Big Tech, China, and the AI Boom Running Out of Money", "Ben Thompson"),
    ("Brex\u2019s 1st Employee On Thinking Like a Founder | Michael Tannenbaum, CEO of Figure", "Michael Tannenbaum"),
    ("AI\u2019s third era: the rise of persistent AI coworkers | Tara Seshan (Product Lead ChatGPT Work)", "Tara Seshan"),
    ("How to close $100K+ enterprise deals, step by step | Jen Abel", "Jen Abel"),
    ("Re-founding a Company for the AI Era | Shensi Ding, Merge", "Shensi Ding"),
    ("Building an Autonomous Delivery Experience with DoorDash Co-Founders Andy Fang and Stanley Tang", "Andy Fang"),
    # …and the ones with no guest at all, which must stay empty rather than invent someone.
    ("Are AI Agents forming \"civilizations\" or is this just a psy op? | 2332", ""),
    ("China wants you to cheer for the robots taking your job | E2329", ""),
    ("How to Build an AI-Native Company in 2026", ""),
    ("20VC: NVIDIA Bonanza: Buys Poolside & Invests in Mercor and Perplexity", ""),
]


def test_guest_extraction_against_real_episode_titles():
    wrong = [(t, want, D.guest_from_title(t)) for t, want in REAL_TITLES if D.guest_from_title(t) != want]
    assert not wrong, wrong


def test_a_role_or_company_is_never_returned_as_a_person():
    for bad in ("with Arm CEO", "with Netic Founder", "with Sequoia Partners", "with the Founders"):
        assert D.guest_from_title("Episode " + bad) == "", bad
