"""The corpus leg — the source DeepDive was built on and never queried.

These are free tests: no database, no model. They pin the two things that decide whether a corpus hit
is a claim about THIS company or noise attached to its name.
"""
from api.deepdive.corpus import MAX_PER_SOURCE, MAX_TOTAL, _terms, as_sections, names_subject


def test_terms_are_the_name_the_domain_and_the_stem():
    assert _terms("Anthropic", "anthropic.com") == ["Anthropic", "anthropic.com"]
    assert _terms("Scale AI", "scale.com") == ["Scale AI", "scale.com", "scale"]


def test_a_short_or_missing_name_is_not_searched_for():
    """A two-letter name matches everything. Better no corpus section than a wrong one."""
    assert _terms("AI", "") == []
    assert _terms("", "") == []


def test_a_generic_name_does_not_match_inside_another_word():
    """`tsv` matches stems, so a block about "scaled training" ranks for a company called Scale.
    The passage has to NAME them."""
    assert not names_subject("we scaled training to 10k GPUs", "", ["Scale"])
    assert names_subject("Scale labels the data", "", ["Scale"])
    assert names_subject("", "Scale AI raises a round", ["Scale"])


def test_a_domain_matches_as_a_substring():
    """A URL in running text has no word boundary around it."""
    assert names_subject("see https://anthropic.com/research for details", "", ["anthropic.com"])


def test_matching_is_case_insensitive():
    assert names_subject("ANTHROPIC filed a brief", "", ["Anthropic"])


def test_sections_come_back_in_authority_order():
    """Filings before press. The dossier's order is an authority statement, not an accident."""
    hits = [{"section": "Press", "register": "stated"},
            {"section": "Regulatory filings", "register": "filed"},
            {"section": "Research", "register": "stated"}]
    assert [s["title"] for s in as_sections(hits)] == ["Regulatory filings", "Research", "Press"]


def test_an_unmapped_section_is_kept_rather_than_dropped():
    hits = [{"section": "Something new", "register": "stated"}]
    assert [s["title"] for s in as_sections(hits)] == ["Something new"]


def test_no_single_source_can_fill_the_dossier():
    """40 news blocks about one company would bury the one filing that matters."""
    assert MAX_PER_SOURCE * 4 < MAX_TOTAL
