"""The corpus leg — the source DeepDive was built on and never queried.

These are free tests: no database, no model. They pin the two things that decide whether a corpus hit
is evidence about THIS company or noise attached to its name, and the split between a document that
is THEIRS and a document that merely NAMES them. The second is not cosmetic: Amazon's 10-K discussing
its Anthropic stake, filed under "What Anthropic has filed", is wrong-company attribution.
"""
from api.deepdive.corpus import (
    MAX_PER_SOURCE,
    acts_like_a_company,
    MAX_TOTAL,
    _terms,
    _uses_as_person,
    _uses_as_word,
    name_is_ambiguous,
    as_sections,
    clean_passage,
    headline,
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


# ── a quote must be the page's words, not its furniture ───────────────────────────────────────────

_PAGE = """# Patterns and problems in multiagent systems \\ Anthropic

Published: 2026-08-13T01:21:29+00:00
Source: anthropic.com (anthropic.com)
Language: en

## Story

Patterns and problems in multiagent systems \\ Anthropic

Skip to main contentSkip to footer

[Home](https://www.anthropic.com/)

- [Research](https://www.anthropic.com/research)

Multi-agent systems fail in ways single agents do not."""


def test_the_quote_is_the_page_not_its_chrome():
    """An ingested page carries a header the ingest wrote and a nav bar the site wrote. Quoted as-is,
    the reader got "Published: … Source: … Language: en … Skip to main contentSkip to footer [Home]"
    where the evidence should be."""
    out = clean_passage(_PAGE, headline(_PAGE, "Anthropic"))
    assert out == "Multi-agent systems fail in ways single agents do not."


def test_the_headline_is_the_page_not_the_site():
    """Every page on anthropic.com is stored with the title "Anthropic", so a list of them said the
    same word eleven times. The page's own H1 says which page it is."""
    assert headline(_PAGE, "Anthropic") == "Patterns and problems in multiagent systems — Anthropic"


def test_a_stored_title_that_is_not_the_site_is_kept():
    assert headline("# Something else", "Zoom Communications, Inc. — 10-Q") == \
        "Zoom Communications, Inc. — 10-Q"


def test_a_terse_first_sentence_is_not_eaten_as_navigation():
    """The nav trim stops the moment a line reads like prose."""
    assert clean_passage("We raised $450M.\nLed by Spark.", "Funding") == \
        "We raised $450M. Led by Spark."


def test_html_entities_are_unescaped():
    """Feed ingests store the escaped source. A Hacker News comment reached the reader as
    `&quot;using Claude&quot; here: https:&#x2F;&#x2F;www.mozilla.org`."""
    out = clean_passage("&quot;using Claude from Anthropic&quot; at https:&#x2F;&#x2F;mozilla.org "
                        "and I&#8217;m told it works.", "")
    assert "&quot;" not in out and "&#x2F;" not in out and "&#8217;" not in out
    assert '"using Claude from Anthropic"' in out and "https://mozilla.org" in out


# ── a name is not always an identifier ────────────────────────────────────────────────────────────
#
# This is the bug the Clay dossier was: a whole-word search for "Clay" returned William Clay Ford in
# Ford's proxy statement, Ms. Clay in Jones Lang LaSalle's, a clay cap in a geothermal paper, and
# Clay Regazzoni winning the 1979 British Grand Prix — all of it filed as evidence about a sales
# automation startup.

_CLAY = [
    "Board of Directors also determined that Mr. Bagué and Ms. Clay, who are not standing",
    "Non-PEO Named Executives for 2021 were John T. Lawler, William Clay Ford, Jr., Michael Amend",
    "A clay cap develops together with a surface fumarolic activity along a corridor",
    "Clay Regazzoni won Williams's first race at the 1979 British Grand Prix",
    "Thanks to Clay from gpus.llm-utils.org!",
    "Clay raises $115M at $7.1B valuation, doubling its worth in a year",
    "Centralize your first and third party data sources in Clay",
    "the clay tablets of Babylonian mathematics",
    "Clay is a sales automation platform",
    "We have verified emails 4x cheaper than Clay, Apollo, and ZoomInfo",
    "experiments use materials from the Cascadia subduction zone",
    "Clay valued at $7.1 billion in latest funding round",
]
_ANTHROPIC = [
    "Anthropic raises $65 billion, nears $1T valuation",
    "Anthropic was founded in January 2021",
    "Our experiments are conducted on Anthropic's Helpful and Harmless dataset",
    "Anthropic passes OpenAI to become the biggest AI startup",
    "switch to direct LLM providers like OpenAI, Anthropic, Cohere",
    "Anthropic partnered with Palantir and Amazon Web Services",
    "Anthropic joined Palantir's FedStart program",
    "the bugs are the ones that say using Claude from Anthropic here",
    "Anthropic publicly disagreed with the administration",
    "Anthropic CEO Dario Amodei said",
    "Patterns and problems in multiagent systems \\ Anthropic",
    "Anthropic Claude Sonnet 4.6 is a hybrid reasoning model",
]


def test_a_common_word_name_is_recognised_as_ambiguous():
    ambiguous, uses = name_is_ambiguous("Clay", _CLAY)
    assert ambiguous and uses >= 3


def test_a_distinctive_name_is_not_called_ambiguous():
    """The cost of a false positive here is a company's own corpus section going nearly empty."""
    assert name_is_ambiguous("Anthropic", _ANTHROPIC) == (False, 0)


def test_a_capitalised_word_AFTER_the_name_is_not_a_person():
    """"Anthropic CEO Dario Amodei" and "Anthropic Claude Sonnet" are not people. Reading them as
    people is what called a perfectly distinctive name ambiguous."""
    assert not _uses_as_person("Anthropic CEO Dario Amodei said", "Anthropic")
    assert not _uses_as_person("Anthropic Claude Sonnet 4.6", "Anthropic")


def test_an_honorific_or_a_leading_given_name_is_a_person():
    assert _uses_as_person("and Ms. Clay, who are not standing", "Clay")
    assert _uses_as_person("were John T. Lawler, William Clay Ford, Jr.", "Clay")


def test_the_lowercase_use_is_what_gives_a_common_word_away():
    assert _uses_as_word("A clay cap develops together with fumarolic activity", "Clay")
    assert not _uses_as_word("Clay raises $115M at $7.1B valuation", "Clay")


def test_a_multi_word_mark_is_specific_enough_on_its_own():
    """"Scale AI" is not the word "scale"."""
    assert name_is_ambiguous("Scale AI", ["we scaled the cluster", "scale up the model"]) == (False, 0)


def test_a_short_sample_never_condemns_a_name():
    """Three passages are not evidence about a word's ordinary use."""
    assert name_is_ambiguous("Clay", _CLAY[:3])[0] is False


# ── a common-word name can still earn a passage back ──────────────────────────────────────────────
#
# Dropping every passage for an ambiguous name is as wrong as admitting Ford's proxy statement: the
# press almost never prints a URL, so "Clay raises $115M" would be lost with the junk. What separates
# them is whether the name is used the way only a COMPANY is used.

_CLAY_REAL = [
    "Clay raises $115M at $7.1B valuation, doubling its worth in a year",
    "Clay valued at $7.1 billion in latest funding round as AI agent startups run hot",
    "Sales automation startup Clay has raised a $100 million Series C",
    "Customers of Clay include Anthropic, Intercom and Verkada",
    "Founded in 2017, Clay was valued at $3.1 billion in August 2025",
    "Clay's top competitors include Scalestack, Cognism, and Artisan AI",
]
_CLAY_JUNK = [
    "Board of Directors also determined that Mr. Bagué and Ms. Clay, who are not standing for "
    "re-election at the Annual Meeting",
    "Non-PEO Named Executives for 2021 were John T. Lawler, William Clay Ford, Jr., Michael Amend",
    "A clay cap develops together with a surface fumarolic activity along a corridor",
    "Clay Regazzoni won Williams's first race at the 1979 British Grand Prix",
    "Thanks to Clay from gpus.llm-utils.org!",
    "the clay tablets of Babylonian mathematics around 2500 BC",
    "The tone depends on the material used, the exact alloy, and whether a solid clay cylinder is used",
]


def test_a_company_verb_rescues_a_real_passage():
    assert all(acts_like_a_company(t, "Clay") for t in _CLAY_REAL)


def test_no_junk_passage_acts_like_a_company():
    """Every one of these reached a real reader's screen as evidence about a sales automation
    startup. Not one of them may come back."""
    for t in _CLAY_JUNK:
        assert not acts_like_a_company(t, "Clay"), t


def test_a_person_is_never_the_subject_even_beside_company_words():
    """"Ms. Clay … re-election at the Annual Meeting" has corporate vocabulary all around it. The
    honorific settles it first."""
    assert not acts_like_a_company("Mr. Bagué and Ms. Clay, who are not standing for re-election "
                                   "at the Annual Meeting of the company", "Clay")


# ── the ambiguity test must not condemn a distinctive name ────────────────────────────────────────
#
# The first version did, in prod, on real corpus text: 107 of 320 Anthropic passages were read as
# "ordinary word or person" and the dossier halved. Both signals were too loose, in ways that only
# real text shows.

def test_a_domain_is_not_the_lowercase_word():
    """`anthropic.com`, `https://anthropic.com/news` and `press@anthropic.com` are all lowercase and
    none of them is the word "anthropic"."""
    for t in ["Source: anthropic.com (anthropic.com) Language: en",
              "see https://www.anthropic.com/news/x",
              "write to press@anthropic.com",
              "hosted at api.anthropic.com/v1"]:
        assert not _uses_as_word(t, "Anthropic"), t


def test_a_sentence_opener_is_not_somebody_s_middle_name():
    """Every sentence starts capitalised. "About Anthropic We are an AI safety company" and
    "Introducing Anthropic Claude" were both read as a person named Anthropic."""
    for t in ["About Anthropic We are an AI safety company",
              "Introducing Anthropic Claude",
              "Google Anthropic and OpenAI compete",
              "At Anthropic we build reliable systems"]:
        assert not _uses_as_person(t, "Anthropic"), t


def test_a_name_between_two_names_is_a_person():
    assert _uses_as_person("were John T. Lawler, William Clay Ford, Michael Amend", "Clay")


def test_a_generational_suffix_is_a_person():
    assert _uses_as_person("signed by Clay, Jr. on behalf of the board", "Clay")


def test_the_real_anthropic_sample_is_not_ambiguous():
    assert name_is_ambiguous("Anthropic", [
        "Source: anthropic.com (anthropic.com) Language: en",
        "see https://www.anthropic.com/news/x",
        "Google Anthropic and OpenAI compete",
        "About Anthropic We are an AI safety company",
        "Introducing Anthropic Claude",
        "At Anthropic we build",
        "write to press@anthropic.com",
        "Anthropic CEO Dario Amodei said",
        "the Anthropic Claude Sonnet model",
        "Anthropic raises $65 billion",
        "switch to providers like OpenAI, Anthropic, Cohere",
        "Patterns and problems in multiagent systems \\ Anthropic",
    ]) == (False, 0)
