"""The careers-page reader's gates. A page that is not hiring must not produce roles."""
from __future__ import annotations

from api.startups.sources.careers import validate

PAGE = ("Careers at Acme. We are a small team building inference infrastructure.\n"
        "Open roles\n"
        "Senior Platform Engineer — San Francisco — Engineering\n"
        "Account Executive, Enterprise — Remote — Sales\n"
        "Benefits: health, dental, equity.")


def test_only_titles_the_page_carries_survive():
    out = {"roles": [{"title": "Senior Platform Engineer", "location": "San Francisco", "department": "Engineering"},
                     {"title": "Account Executive, Enterprise", "location": "Remote", "department": "Sales"},
                     {"title": "Staff Machine Learning Engineer", "location": "", "department": ""}]}
    got = validate(out, PAGE)
    assert [r["title"] for r in got] == ["Senior Platform Engineer", "Account Executive, Enterprise"]
    assert got[0]["location"] == "San Francisco"


def test_a_page_that_is_not_hiring_yields_nothing():
    """The failure this exists to stop: asked for open roles, a model produces plausible ones."""
    page = "Careers. We are not hiring right now, but we are always happy to hear from great people."
    out = {"roles": [{"title": "Software Engineer", "location": "Remote", "department": "Engineering"}]}
    assert validate(out, page) == []


def test_team_and_benefit_headings_are_not_roles():
    page = "Our team. Benefits. Life at Acme. Engineering."
    out = {"roles": [{"title": "Our team"}, {"title": "Benefits"}, {"title": "Life at Acme"}]}
    assert validate(out, page) == []


def test_the_same_role_twice_is_one_role():
    out = {"roles": [{"title": "Senior Platform Engineer"}, {"title": "senior  platform engineer"}]}
    assert len(validate(out, PAGE)) == 1
