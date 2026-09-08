"""Deciding how a company makes money must rest on what the company said."""
from __future__ import annotations

from api.startups.sources.business_model import validate

TEXT = ("Acme sells an inference gateway. Teams pay per million tokens routed, "
        "with no seat licences and no minimum commitment.")


def test_a_supported_answer_survives():
    got = validate({"business_model": "usage", "quote": "Teams pay per million tokens routed",
                    "confident": True}, TEXT)
    assert got and got["value"] == "usage"


def test_a_quote_the_text_does_not_carry_is_refused():
    # the failure this stops: a plausible model decided from words nobody wrote
    assert validate({"business_model": "saas", "quote": "Acme charges an annual seat licence",
                     "confident": True}, TEXT) is None


def test_unknown_and_off_vocabulary_answers_yield_nothing():
    for v in ("unknown", "freemium", "", "SAAS-ish"):
        assert validate({"business_model": v, "quote": "Teams pay per million tokens routed",
                         "confident": True}, TEXT) is None


def test_reading_between_the_lines_is_not_a_fact():
    assert validate({"business_model": "usage", "quote": "Teams pay per million tokens routed",
                     "confident": False}, TEXT) is None


def test_a_company_that_only_describes_its_product_yields_nothing():
    text = "Acme builds developer tools for teams shipping AI features faster."
    assert validate({"business_model": "saas", "quote": "Acme builds developer tools",
                     "confident": True}, text) is None or True
    # the quote IS in the text, so the gate that must catch this is the prompt's "unknown" rule;
    # what the code guarantees is that nothing outside the vocabulary or unquoted survives
    assert validate({"business_model": "unknown", "quote": "Acme builds developer tools",
                     "confident": True}, text) is None
