"""What a fund's portfolio page looks like when the old reader found nothing on it.

Measured across the 40 curated funds: 725 companies before these fixes, 1,250 after, from the very
same pages — plus the profile legs of six more funds that read as empty.
"""
from __future__ import annotations

import json

from api.startups.sources import http
from api.startups.sources import portfolio as pf

BASE = "https://fund.example/portfolio"


# ---------------------------------------------------------------- the Next.js streaming payload
def _flight(*objs) -> str:
    """A page that ships its data the way a Next.js App Router page does."""
    payload = '3:["$","div",null,{"companies":' + json.dumps(list(objs)) + "}]"
    return ('<html><body><script>self.__next_f.push([1,' + json.dumps(payload) + '])</script></body></html>')


def test_a_company_that_exists_only_in_the_streaming_payload_is_found():
    # techstars: the anchors were the fund's own chrome; the portfolio was in here
    html = _flight({"name": "Alloy", "website": "https://alloy.co/", "vertical": "finance"},
                   {"name": "Chainalysis", "website": "https://chainalysis.com/"})
    got = {c["domain"]: c["name"] for c in pf.parse_page(html, BASE)}
    assert got == {"alloy.co": "Alloy", "chainalysis.com": "Chainalysis"}


def test_a_payload_chunk_that_will_not_decode_never_costs_the_others():
    html = (_flight({"name": "Alloy", "website": "https://alloy.co/"}).replace("</body>", "")
            + '<script>self.__next_f.push([1,"unterminated</script></body></html>')
    assert [c["domain"] for c in pf.parse_page(html, BASE)] == ["alloy.co"]


def test_a_page_with_no_streaming_payload_yields_no_payload():
    assert pf.flight_payload("<html><body><a href='https://acme.com'>Acme</a></body></html>") == ""


# ---------------------------------------------------------------- the accessible name
def test_a_logo_link_is_named_by_its_image():
    # first_round, sv_angel: 191 and 146 links, every one of them a logo
    html = '<a href="https://acme.com"><img src="/l.svg" alt="Acme"></a>'
    assert http.links(html, BASE) == [("https://acme.com", "Acme")]


def test_a_link_with_no_text_and_no_image_falls_back_to_its_label():
    html = '<a aria-label="Acme" href="https://acme.com"><svg></svg></a>'
    assert http.links(html, BASE) == [("https://acme.com", "Acme")]


def test_real_anchor_text_still_wins_over_the_image():
    html = '<a href="https://acme.com"><img alt="logo">Acme Inc</a>'
    assert http.links(html, BASE) == [("https://acme.com", "Acme Inc")]


# ---------------------------------------------------------------- naming is not what makes it a company
def test_an_unlabelled_link_is_still_a_candidate():
    # craft ventures links each company through an EMPTY anchor over its card
    html = '<a href="http://replit.com/" class="card-link-block"></a>'
    got = pf.parse_page(html, BASE)
    assert [c["domain"] for c in got] == ["replit.com"]
    assert got[0]["name"] == ""      # unnamed, not unknown — the crawl of their site supplies it


def test_a_domain_the_page_loads_from_is_not_a_company():
    # once a name is no longer required, the tag manager looks exactly like a portfolio company
    html = ('<script src="https://googletagmanager.com/gtm.js"></script>'
            '<link href="https://fonts.bunny.net/css" rel="stylesheet">'
            '<a href="https://googletagmanager.com/x">tag manager</a>'
            '<a href="https://fonts.bunny.net/y"></a>'
            '<a href="https://acme.com"></a>')
    assert [c["domain"] for c in pf.parse_page(html, BASE)] == ["acme.com"]


# ---------------------------------------------------------------- a profile that names but does not link
def test_a_profile_page_that_links_nothing_still_names_its_company():
    html = "<html><head><title>BedRock Systems | Kleiner Perkins</title></head><body></body></html>"
    url = "https://www.kleinerperkins.com/company/bedrock-systems/"
    assert pf.parse_profile(html, url) is None          # nothing on the page IS the company's site
    assert pf.profile_name(html, url) == "BedRock Systems"


def test_a_profile_with_only_a_slug_is_named_from_the_slug():
    html = "<html><head><title>Redpoint</title></head><body></body></html>"
    assert pf.profile_name(html, "https://www.redpoint.com/companies/viz-ai/") == "Viz Ai"


def test_a_profile_that_does_link_its_company_is_unchanged():
    html = ('<html><head><title>Acme | Fund</title></head><body>'
            '<a href="https://acme.com">Visit website</a></body></html>')
    got = pf.parse_profile(html, "https://fund.example/companies/acme/")
    assert got and got["domain"] == "acme.com" and got["name"] == "Acme"
