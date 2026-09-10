"""The team-page parser's gates, and the shapes real VC sites actually use (measured 2026-09-10)."""
from api.investors.sources.people import (bind_score, binds, firm_handle, looks_like_a_person, parse_team, role_of)


class TestNameGate:
    def test_a_person_looks_like_one(self):
        for n in ("Jane Okafor", "Marc Andreessen", "Jo Anne Ambrosino", "Bill de Blasio"):
            assert looks_like_a_person(n), n

    def test_page_furniture_is_not_a_person(self):
        for n in ("Portfolio Companies", "New York", "Series A", "Read More", "Privacy Policy", "SEQUOIA CAPITAL"):
            assert not looks_like_a_person(n), n

    def test_a_title_glued_to_a_name_is_not_a_person(self):
        """Craft prints "David Sacks" then "Partner"; a 4-token pattern reads "Mark Woolway President"."""
        for n in ("Mark Woolway President", "Van Linge Principal", "Erica Martinez Manager"):
            assert not looks_like_a_person(n), n


class TestBinding:
    def test_a_name_binds_its_own_slug(self):
        assert binds("David Sacks", "david-sacks")
        assert binds("Fred Wilson", "fred-wilson")
        assert binds("Byron Deeter", "team-byron-deeter-02")

    def test_a_name_does_not_bind_a_neighbours_slug(self):
        """The failure this module exists to prevent: attaching a link to whoever is nearest in the DOM."""
        assert not binds("Mark Woolway", "david-sacks")
        assert not binds("Sarah Chen", "john-smith-05a1")

    def test_one_shared_token_is_not_a_binding(self):
        assert not binds("Wei Chen", "chen-partners-fund")

    def test_the_best_covered_candidate_wins(self):
        """Both "Kindle Van Linge" and the fragment "Van Linge Principal" bind kindle-van-linge."""
        assert bind_score("Kindle Van Linge", "kindle-van-linge") > bind_score("Van Linge Extra", "kindle-van-linge")


class TestRoles:
    def test_seniority_is_not_flattened(self):
        assert role_of("Managing Partner")[0] == "managing_partner"
        assert role_of("General Partner")[0] == "general_partner"
        assert role_of("Venture Partner")[0] == "venture_partner"
        assert role_of("Partner")[0] == "partner"

    def test_a_title_is_kept_as_printed(self):
        role, title = role_of("Managing Director, Growth")
        assert role == "managing_partner" and "Managing Director" in title

    def test_no_role_words_means_no_role(self):
        assert role_of("Based in London")[0] == ""


class TestRealPageShapes:
    """One case per structure found on real VC team pages, so a template change fails loudly."""

    def test_profile_link_shape_craft(self):
        html = ('<div><a href="/team/david-sacks"><h4 class="team-member-name">David Sacks</h4>'
                '<p class="team-member-title">Partner</p></a></div>'
                '<div><a href="/team/mark-woolway"><h4 class="team-member-name">Mark Woolway</h4>'
                '<p class="team-member-title">President</p></a></div>')
        got = {p["name"]: p for p in parse_team(html, base_domain="craftventures.com")}
        assert set(got) == {"David Sacks", "Mark Woolway"}
        assert got["David Sacks"]["role"] == "partner"
        assert got["David Sacks"]["links"]["profile"].endswith("/team/david-sacks")

    def test_heading_and_role_shape_initialized(self):
        """A page that links nothing: <h3>Name</h3> then the role. The role does the binding."""
        html = ('<div class="team-member"><h3 class="rtext-headline1">Abdul Ly</h3>'
                '<svg viewBox="0 0 24 24"><path d="M16.34 12.42V10.95H12.40V7H10.93Z"></path></svg>'
                '<div class="rtext-p4">Partner</div></div>')
        got = parse_team(html)
        assert [p["name"] for p in got] == ["Abdul Ly"] and got[0]["role"] == "partner"

    def test_a_heading_without_a_role_is_not_a_person(self):
        assert parse_team('<h3>Portfolio Companies</h3><div>Our investments</div>') == []
        assert parse_team('<h2>Jane Okafor</h2><div>Based in London</div>') == []

    def test_data_name_shape_bessemer(self):
        html = '<a class="team-member" data-name="byron deeter"><div class="name">Byron Deeter</div></a>'
        assert [p["name"] for p in parse_team(html)] == ["Byron Deeter"]

    def test_names_do_not_span_two_people(self):
        """Flattened, this reads "David Sacks Partner Elyse Davis" — one invented person."""
        html = '<h4>David Sacks</h4><p>Partner</p><h4>Elyse Davis</h4><p>Partner</p><a href="/team/david-sacks">x</a>'
        assert "David Sacks Elyse Davis" not in [p["name"] for p in parse_team(html)]

    def test_a_linkedin_link_binds_only_its_owner(self):
        html = ('<div><span>Sarah Chen</span><a href="https://www.linkedin.com/in/john-smith-05a1">in</a></div>')
        assert parse_team(html) == [], "a link that binds nobody is dropped, not given to the nearest name"

    def test_the_firms_own_x_handle_is_not_a_person(self):
        html = '<div><span>Jane Okafor</span><a href="https://x.com/acmeventures">follow us</a></div>'
        assert not any(p["links"].get("x") for p in parse_team(html))
        assert firm_handle(html) == "https://x.com/acmeventures"
