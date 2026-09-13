import asyncio
import pytest

from eigen_kernel.providers.people_search import (
    PersonResult, FakePeopleSearch, CompositePeopleSearch)
from eigen_kernel.providers.exa_people import _split_title


def _run(c): return asyncio.run(c)


def test_composite_dedupes_by_profile_url_and_marks_cross_engine_agreement():
    a = FakePeopleSearch({"q": [PersonResult(name="Dana", profile_url="https://linkedin.com/in/dana", provider="exa"),
                                PersonResult(name="Lee", profile_url="https://linkedin.com/in/lee", provider="exa")]})
    b = FakePeopleSearch({"q": [PersonResult(name="Dana", profile_url="https://linkedin.com/in/dana/", provider="pdl")]})
    out = _run(CompositePeopleSearch([a, b]).search("q"))
    urls = [_p.name for _p in out]
    assert "Dana" in urls and "Lee" in urls and len(out) == 2      # deduped despite trailing slash
    dana = next(p for p in out if p.name == "Dana")
    assert set(dana.providers) == {"exa", "pdl"}                    # both engines credited
    assert out[0].name == "Dana"                                   # cross-engine agreement bubbles up


def test_fake_respects_max_results():
    f = FakePeopleSearch({"q": [PersonResult(name=str(i), profile_url=f"u{i}") for i in range(10)]})
    assert len(_run(f.search("q", max_results=3))) == 3


@pytest.mark.parametrize("title,url,name,head", [
    ("Dana Ops - VP Operations at Acme 3PL | LinkedIn", "https://linkedin.com/in/dana",
     "Dana Ops", "VP Operations at Acme 3PL"),
    ("Lee Kim | Head of Warehouse Systems", "https://linkedin.com/in/lee", "Lee Kim", "Head of Warehouse Systems"),
    ("", "https://linkedin.com/in/jordan-vp", "Jordan Vp", ""),   # falls back to the URL slug
])
def test_split_title_pulls_name_and_headline(title, url, name, head):
    n, h = _split_title(title, url)
    assert n == name and h == head


def test_split_title_tidies_lowercase_names_and_dangling_headlines():
    n, h = _split_title("clifford peter albertson - Lead daily operations for a 3PL", "https://linkedin.com/in/x")
    assert n == "Clifford Peter Albertson"           # lowercased index → title case
    assert h == "Lead daily operations for a 3PL"     # leading "- " dropped
    n2, h2 = _split_title("Mike Anton | , cut costs structurally", "u")
    assert n2 == "Mike Anton" and h2 == "cut costs structurally"


def test_clean_md_strips_markdown_noise_from_headlines():
    from eigen_kernel.providers.exa_people import _clean_md
    assert _clean_md("### [Port Jersey Logistics](https://x.com) #### WMS Implementation Manager") \
        == "Port Jersey Logistics WMS Implementation Manager"
    assert _clean_md("- Director of Warehouse Operations") == "Director of Warehouse Operations"


def test_pdl_parse_maps_records_and_prefixes_linkedin():
    from eigen_kernel.providers.pdl_people import _parse
    data = {"data": [
        {"full_name": "dana ops", "job_title": "VP Operations", "job_company_name": "Acme 3PL",
         "linkedin_url": "linkedin.com/in/dana", "skills": ["wms", "logistics"], "location_name": "Chicago, IL"},
        {"full_name": "", "linkedin_url": "https://linkedin.com/in/jordan-vp"},   # name from slug
        {"job_title": "orphan record, no name, no url"}]}                          # dropped
    out = _parse(data)
    assert len(out) == 2
    assert out[0].name == "Dana Ops" and out[0].provider == "pdl"
    assert out[0].profile_url == "https://linkedin.com/in/dana"                    # scheme added
    assert out[0].headline == "VP Operations · Acme 3PL" and "wms" in out[0].expertise
    assert out[1].name == "Jordan Vp"                                             # slug fallback


def test_pdl_no_key_returns_empty():
    import asyncio
    from eigen_kernel.providers.pdl_people import PdlPeopleSearch
    assert asyncio.run(PdlPeopleSearch(api_key="").search("anything")) == []
