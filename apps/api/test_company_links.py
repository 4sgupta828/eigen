"""Contract test for company hyperlinks: ResearchOut.companies is the set of companies the
answer is GROUNDED on (subjects of its own company-source claims), deduped, with a canonical
page + Eigen entity url. Offline: app.state.service.ask is faked. Also asserts the flag gate.

    EIGEN_COMPANY_LINKS=1 PYTHONPATH=apps:packages/vertical_tech:packages/kernel \
      .venv/bin/python -m pytest apps/api/test_company_links.py -q
"""
from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _claim(source_key, title, doc_id):
    return SimpleNamespace(text=f"a fact about {title}", quote="verbatim", atom_id="a1",
                           source_key=source_key, document_title=title, document_id=doc_id)


def _fake_service(claims):
    async def ask(**kw):
        return SimpleNamespace(
            composed_answer="Stripe and Abalone Bio are notable. [1]", grounded=True,
            verified_claims=claims, rejected_claims=[], source_stats={}, coverage_gaps=[],
            visual_observation="", stopped_reason="answered", atoms_gathered=3, retried_empty=False,
            resolved_question="", derived_from_prior=False, effort=1.0)
    ui = SimpleNamespace(source_url=lambda did, quote=None: "https://page/" + did if did else None)
    return SimpleNamespace(ask=ask, ui=ui)


def _client(flag):
    os.environ["EIGEN_COMPANY_LINKS"] = flag
    from api.app import create_app
    app = create_app()
    app.state.service = _fake_service([
        _claim("yc", "Stripe", "yc:stripe"),
        _claim("yc", "Stripe", "yc:stripe"),                 # dup → collapses
        _claim("wikidata", "Abalone Bio", "wikidata:Q42"),
        _claim("openalex", "Some Paper", "openalex:W1"),      # NOT a company source → excluded
        _claim("edgar", "Form D — X", "edgar:0001-23-1"),     # edgar excluded (title is a filing)
    ])
    return TestClient(app)


def test_flag_off_yields_no_companies_and_no_entity_page() -> None:
    client = _client("")
    r = client.post("/research", json={"question": "compare startups", "tenant_id": "demo"})
    assert r.status_code == 200
    assert r.json().get("companies") == []
    assert client.get("/entity/yc:stripe").status_code == 404


def test_companies_are_the_grounded_company_subjects_deduped() -> None:
    client = _client("1")
    r = client.post("/research", json={"question": "compare startups", "tenant_id": "demo"})
    assert r.status_code == 200
    cos = r.json()["companies"]
    names = [c["name"] for c in cos]
    assert names == ["Stripe", "Abalone Bio"]              # dedup; paper + edgar excluded
    by = {c["name"]: c for c in cos}
    assert by["Stripe"]["entity_id"] == "yc:stripe"
    assert by["Stripe"]["url"] == "https://page/yc:stripe"
    assert by["Stripe"]["eigen_url"] == "/entity/yc%3Astripe"
    assert by["Abalone Bio"]["entity_id"] == "wikidata:Q42"
