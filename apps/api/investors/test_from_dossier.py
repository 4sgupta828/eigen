"""Reading a DeepDive dossier for what a fundraise needs.

The first version of the startup reader crawled four pages and made one model call, beside a DeepDive
module that already resolves a company, discovers it on the web when we do not hold it, extracts
claims with a model call per page, and puts every claim through congruence gates. This reuses that
instead of competing with it.
"""
from api.investors.from_dossier import (contract_from, evidenced_stage, existing_investors,
                                        fundraising_profile, milestones, rounds, team)


def dossier(*sections, company=None):
    return {"company": company or {"id": "acme.dev", "name": "Acme"}, "sections": list(sections)}


def sec(title, kind, claims):
    return {"title": title, "kind": kind, "claims": claims}


# ── the strongest signal we hold ───────────────────────────────────────────────────────────────
def test_existing_backers_become_the_co_investor_leg():
    """Firms that have co-invested with your backers have done a deal shaped like yours. Nothing else
    we hold is as direct, and before this the field was simply never populated."""
    d = dossier(sec("Investors", "investors",
                    [{"name": "Amplify Partners", "slug": "amplify", "lead": True, "source_url": "https://x"}]))
    assert [i["name"] for i in existing_investors(d)] == ["Amplify Partners"]
    assert contract_from(fundraising_profile(d))["co_investors"] == ["amplify"]


def test_an_investor_without_a_resolvable_slug_is_shown_but_not_searched():
    # A name we could not resolve is worth showing the founder and useless as a filter; guessing the
    # slug would quietly search for the wrong firm.
    d = dossier(sec("Investors", "investors", [{"name": "Some Angel", "slug": ""}]))
    p = fundraising_profile(d)
    assert [i["name"] for i in p["existing_investors"]] == ["Some Angel"]
    assert contract_from(p)["co_investors"] == []


# ── stage: evidenced beside claimed, never instead of it ───────────────────────────────────────
def test_the_latest_visible_round_sets_the_evidenced_stage():
    d = dossier(sec("Funding rounds", "financing",
                    [{"round_name": "Seed", "event_date": "2024-02-01"},
                     {"round_name": "Series A", "event_date": "2026-01-05"}]))
    assert evidenced_stage(d) == "series_a"
    assert [r["round"] for r in rounds(d)] == ["Seed", "Series A"]


def test_a_claim_that_disagrees_with_the_record_is_flagged_not_overwritten():
    """The reviewers split here: one wanted the tension surfaced, the other refused to correct a
    founder algorithmically. The spec keeps both and names the difference."""
    d = dossier(sec("Funding rounds", "financing", [{"round_name": "Series A", "event_date": "2026-01-05"}]))
    c = contract_from(fundraising_profile(d), claimed_stage="seed")
    assert c["stage"] == "seed", "the founder's claim still drives the search"
    assert c["stage_evidenced"] == "series_a" and c["stage_disagrees"] is True


def test_no_visible_rounds_means_no_evidenced_stage_rather_than_a_guess():
    d = dossier()
    assert evidenced_stage(d) == ""
    assert contract_from(fundraising_profile(d), claimed_stage="seed")["stage_disagrees"] is False


# ── what we refuse to do ──────────────────────────────────────────────────────────────────────
def test_milestones_keep_their_attribution_and_never_become_metrics():
    """DeepDive refuses a revenue integer for a private company and offers a stated-milestones ledger
    instead. Reading it for a raise must not quietly undo that."""
    d = dossier(sec("Stated milestones", "stated",
                    [{"claim": "Crossed 1,000 teams", "attribution": "their blog", "register": "stated"}]))
    m = milestones(d)[0]
    assert m["attribution"] == "their blog" and m["register"] == "stated"


def test_the_team_is_carried_for_the_reader_not_for_the_score():
    # Both reviewers refused founder-based scoring; the team is shown and never enters the contract.
    d = dossier(sec("Key people", "people", [{"name": "Jane Doe", "title": "CEO"}]))
    assert [t["name"] for t in team(d)] == ["Jane Doe"]
    assert "team" not in contract_from(fundraising_profile(d))


# ── an empty dossier is a stated gap, not an empty promise ────────────────────────────────────
def test_missing_sections_are_named_as_gaps():
    p = fundraising_profile(dossier())
    assert any("co-investor" in g for g in p["gaps"])
    assert any("stage" in g for g in p["gaps"])


def test_a_dossier_with_backers_reports_no_co_investor_gap():
    d = dossier(sec("Investors", "investors", [{"name": "Amplify", "slug": "amplify"}]))
    assert not any("co-investor" in g for g in fundraising_profile(d)["gaps"])
