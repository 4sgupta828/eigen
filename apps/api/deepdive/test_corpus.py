"""The corpus leg — the source DeepDive was built on and never queried.

These are free tests: no database, no model. They pin the two things that decide whether a corpus hit
is evidence about THIS company or noise attached to its name, and the split between a document that
is THEIRS and a document that merely NAMES them. The second is not cosmetic: Amazon's 10-K discussing
its Anthropic stake, filed under "What Anthropic has filed", is wrong-company attribution.
"""
from api.deepdive.corpus import (
    MAX_PER_SOURCE,
    MAX_TOTAL,
    _terms,
    as_sections,
    is_theirs,
    looks_like_bibliography,
    names_subject,
)


# ── who are we even looking for ───────────────────────────────────────────────────────────────────

def test_terms_are_the_name_the_domain_and_the_stem():
    assert _terms("Anthropic", "anthropic.com") == ["Anthropic", "anthropic.com"]
    assert _terms("Scale AI", "scale.com") == ["Scale AI", "scale.com", "scale"]


def test_a_short_or_missing_name_is_not_searched_for():
    """A two-letter name matches everything. Better no corpus section than a wrong one."""
    assert _terms("AI", "") == []
    assert _terms("", "") == []


# ── does the passage actually name them ───────────────────────────────────────────────────────────

def test_a_generic_name_does_not_match_inside_another_word():
    """`tsv` matches stems, so a block about "scaled training" ranks for a company called Scale."""
    assert not names_subject("we scaled training to 10k GPUs", "", ["Scale"])
    assert names_subject("Scale labels the data", "", ["Scale"])


def test_a_domain_matches_as_a_substring():
    """A URL in running text has no word boundary around it."""
    assert names_subject("see https://anthropic.com/research for details", "", ["anthropic.com"])


def test_matching_is_case_insensitive():
    assert names_subject("ANTHROPIC filed a brief", "", ["Anthropic"])


def test_a_bibliography_is_not_a_finding():
    """A paper's reference list ranks for every term it cites. It was arriving as claims about an AI
    lab: "Aboulkhair et al. (2016) — On the formation of…"."""
    refs = ("Aboulkhair et al. (2016) On the formation of. "
            "Agostini et al. (2018) GPUDirect async. Brown et al. (2020) Language models.")
    assert looks_like_bibliography(refs)
    assert looks_like_bibliography("References\n[1] Vaswani et al.")
    assert not looks_like_bibliography("Anthropic released Claude in 2023 (2023) to customers.")


# ── whose document is it ──────────────────────────────────────────────────────────────────────────

def test_a_filing_is_theirs_only_when_they_filed_it():
    """The accession's leading digits ARE the filer's CIK. Amazon's 10-K names Anthropic on the page
    that discloses its stake; that does not make it Anthropic's filing."""
    amazon = "edgar:0001018724-26-000004"           # CIK 1018724 = Amazon
    assert is_theirs(amazon, "edgar", "Amazon.com 10-K", "", name="Amazon", domain="amazon.com",
                     cik="1018724")
    assert not is_theirs(amazon, "edgar", "Amazon.com 10-K", "", name="Anthropic",
                         domain="anthropic.com", cik="")


def test_a_company_with_no_cik_owns_no_filing():
    """A private company is not an SEC filer. Every EDGAR hit naming them is somebody else's."""
    assert not is_theirs("edgar:0001018724-26-000004", "edgar", "", "", name="Anthropic",
                         domain="anthropic.com", cik="")


def test_a_repo_is_theirs_only_when_they_own_it():
    """A hundred READMEs list Anthropic among their providers. One org actually publishes the code."""
    assert is_theirs("github:anthropics/anthropic-sdk-python", "github", "", "",
                     name="Anthropic", domain="anthropic.com")
    assert not is_theirs("github:someone/llm-router", "github", "", "",
                         name="Anthropic", domain="anthropic.com")


def test_a_page_is_theirs_when_it_is_on_their_domain():
    assert is_theirs("web:https://www.anthropic.com/research/x", "web", "",
                     "https://www.anthropic.com/research/x", name="Anthropic", domain="anthropic.com")
    assert not is_theirs("web:https://techcrunch.com/anthropic-raises", "web", "",
                         "https://techcrunch.com/anthropic-raises", name="Anthropic",
                         domain="anthropic.com")


def test_a_subdomain_is_still_theirs():
    assert is_theirs("eng_blog:https://blog.stripe.com/ledger", "eng_blog", "",
                     "https://blog.stripe.com/ledger", name="Stripe", domain="stripe.com")


def test_a_reference_page_is_theirs_when_its_title_names_them():
    assert is_theirs("wikipedia:12345", "wikipedia", "Anthropic", "", name="Anthropic",
                     domain="anthropic.com")
    assert not is_theirs("wikipedia:999", "wikipedia", "Large language model", "",
                         name="Anthropic", domain="anthropic.com")


def test_research_is_never_claimed_as_theirs():
    """We hold no reliable affiliation or assignee, so we do not claim one. "Research that names
    them" is what we can actually show — saying less than we know beats saying more than we can."""
    for src in ("arxiv", "openalex", "semantic_scholar", "uspto", "patentsview", "nsf"):
        assert not is_theirs(f"{src}:2501.00001", src, "Constitutional AI", "",
                             name="Anthropic", domain="anthropic.com")


def test_an_unknown_shape_is_a_mention_not_an_ownership_claim():
    """Unsure must fail to `mention`. The other way round is the attribution error."""
    assert not is_theirs("mystery:abc", "mystery", "", "", name="Anthropic", domain="anthropic.com")


# ── how the sections come out ─────────────────────────────────────────────────────────────────────

def test_their_own_documents_come_before_documents_that_merely_name_them():
    hits = [{"section": "Named in others' filings"}, {"section": "Press"},
            {"section": "What they have filed"}]
    assert [s["title"] for s in as_sections(hits)] == [
        "What they have filed", "Press", "Named in others' filings"]


def test_a_mention_section_says_on_its_face_that_it_is_not_theirs():
    """A reader who skims headings must not come away thinking a peer's 10-K was this company's."""
    own, mention = as_sections([{"section": "What they have filed"},
                                {"section": "Named in others' filings"}])
    assert not own.get("note")
    assert "not theirs" in mention["note"]


def test_an_unmapped_section_is_kept_rather_than_dropped():
    assert [s["title"] for s in as_sections([{"section": "Something new"}])] == ["Something new"]


def test_no_single_source_can_fill_the_dossier():
    """40 news blocks about one company would bury the one filing that matters."""
    assert MAX_PER_SOURCE * 4 < MAX_TOTAL


# ── a company's site arrives in more than one shape ───────────────────────────────────────────────

def test_a_domain_with_a_scheme_still_matches_their_own_pages():
    """A company row carries `website` as "https://www.anthropic.com/" and `id` as a bare host, and
    both reach here. With the scheme still attached the host comparison could never match, so every
    page ON their own site was filed as a page that merely named them."""
    for d in ("anthropic.com", "www.anthropic.com", "https://www.anthropic.com",
              "https://www.anthropic.com/"):
        assert is_theirs("web:https://www.anthropic.com/news/x", "web", "",
                         "https://www.anthropic.com/news/x", name="Anthropic", domain=d), d


def test_the_search_terms_are_a_bare_host_too():
    assert _terms("Anthropic", "https://www.anthropic.com/") == ["Anthropic", "anthropic.com"]
