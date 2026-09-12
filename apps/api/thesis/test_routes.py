from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.thesis import routes


def _thesis(*, owner: bool) -> dict:
    return {"id": "t1", "title": "Thesis", "thesis": "A sufficiently long thesis sentence.",
            "subject": {}, "is_owner": owner, "decision": {}, "research_status": "not_run",
            "claims": [
                {"rung": "problem_exists", "claim": "The problem occurs.", "settleable": "corpus",
                 "critical": True, "research_status": "open", "verdict": "open",
                 "attacked": False, "evidence": []},
                {"rung": "willingness_to_pay", "claim": "The buyer will pay.",
                 "settleable": "call_only", "critical": True, "research_status": "open",
                 "verdict": "open", "attacked": False, "evidence": []},
            ], "turns": []}


def _client(monkeypatch, *, raise_server_exceptions: bool = True):
    async def pool_of():
        return object()

    async def user_of(token: str):
        return {"id": "user-1"} if token == "Bearer owner" else {}

    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token=""):
        if thesis_id != "t1":
            return None
        if owner_id == "user-1" or owner_token == "owner-cap":
            return _thesis(owner=True)
        if share_token == "share-cap":
            return _thesis(owner=False)
        return None

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    app = FastAPI()
    policy = SimpleNamespace(decide=lambda claims: {"recommendation": "continue_diligence",
                                                     "decisive_claims": ["problem_exists"],
                                                     "reason": "Incomplete."},
                             is_critical=lambda rung: rung in {"problem_exists", "willingness_to_pay"})
    app.include_router(routes.build_router(pool_of, providers=None,
                                           manifest=SimpleNamespace(ui=None, thesis_policy=policy),
                                           user_of=user_of, tenant="tenant-a"))
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_research_projection_includes_every_paid_stage() -> None:
    got = routes.project_research_cost(2, web=True, web_available=True)

    assert got["components"] == {"refutation": 0.003, "relationship_judgment": 0.003,
                                 "web_ceiling": 0.024, "case_synthesis": 0.004}
    assert got["projected_usd"] == 0.034


def test_default_tenant_comes_from_eigen_environment(monkeypatch) -> None:
    monkeypatch.setenv("EIGEN_TENANT_ID", "tenant-from-env")

    assert routes.resolve_tenant("") == "tenant-from-env"
    assert routes.resolve_tenant("tenant-explicit") == "tenant-explicit"


def test_share_capability_reads_but_cannot_mutate(monkeypatch) -> None:
    client = _client(monkeypatch)

    shared = client.get("/thesis/t1?share=share-cap")
    denied = client.post("/thesis/t1/call?share=share-cap", json={
        "rung": "problem_exists", "quote": "A firsthand account.", "supports": True,
    })

    assert shared.status_code == 200
    assert shared.json()["thesis"]["is_owner"] is False
    assert denied.status_code in (403, 404)


def test_owner_can_create_and_revoke_a_read_only_share(monkeypatch) -> None:
    async def issue(_pool, thesis_id):
        assert thesis_id == "t1"
        return "new-share"

    async def revoke(_pool, thesis_id):
        assert thesis_id == "t1"

    monkeypatch.setattr(routes.tstore, "issue_share", issue, raising=False)
    monkeypatch.setattr(routes.tstore, "revoke_share", revoke, raising=False)
    client = _client(monkeypatch)

    made = client.post("/thesis/t1/share", headers={"Authorization": "Bearer owner"})
    revoked = client.delete("/thesis/t1/share", headers={"Authorization": "Bearer owner"})

    assert made.status_code == 200 and made.json()["share_token"] == "new-share"
    assert revoked.status_code == 200


def test_owner_can_edit_a_claim_before_research(monkeypatch) -> None:
    seen = []

    async def revise(_pool, thesis_id, rung, claim):
        seen.append((thesis_id, rung, claim))

    monkeypatch.setattr(routes.tstore, "revise_claim", revise)
    client = _client(monkeypatch)

    response = client.patch("/thesis/t1/claim/problem_exists",
                            headers={"Authorization": "Bearer owner"},
                            json={"claim": "The problem recurs every week."})

    assert response.status_code == 200
    assert seen == [("t1", "problem_exists", "The problem recurs every week.")]


def test_research_is_refused_before_run_creation_when_cap_is_too_low(monkeypatch) -> None:
    created = []

    async def create_run(*_args, **kwargs):
        created.append(kwargs)
        return {"id": "run-1"}

    monkeypatch.setattr(routes.tstore, "create_run", create_run)
    client = _client(monkeypatch)

    response = client.post("/thesis/t1/research/start", headers={"Authorization": "Bearer owner"},
                           json={"max_usd": 0.001, "idempotency_key": "request-1", "web": True})

    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert created == []


def test_approved_research_run_records_full_projection_and_tenant(monkeypatch) -> None:
    seen = {}

    async def create_run(_pool, **kwargs):
        seen.update(kwargs)
        return {"id": "run-1", "state": "approved", "approved_usd": kwargs["approved_usd"]}

    monkeypatch.setattr(routes.tstore, "create_run", create_run)
    client = _client(monkeypatch)

    response = client.post("/thesis/t1/research/start", headers={"Authorization": "Bearer owner"},
                           json={"max_usd": 1.0, "idempotency_key": "request-1", "web": False})

    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert seen["metadata"]["tenant"] == "tenant-a"
    assert seen["projected_usd"] == 0.01


def test_one_interview_note_marks_primary_research_needed_not_supported(monkeypatch) -> None:
    evidence, verdicts = [], []

    async def add_evidence(_pool, thesis_id, rung, rows):
        evidence.extend(rows)
        return len(rows)

    async def set_verdict(_pool, thesis_id, rung, verdict, note="", **_kwargs):
        verdicts.append((rung, verdict, note))

    async def add_turn(*_args, **_kwargs):
        return None

    monkeypatch.setattr(routes.tstore, "add_evidence", add_evidence)
    monkeypatch.setattr(routes.tstore, "set_verdict", set_verdict)
    monkeypatch.setattr(routes.tstore, "add_turn", add_turn)
    client = _client(monkeypatch)

    response = client.post("/thesis/t1/call", headers={"Authorization": "Bearer owner"}, json={
        "rung": "willingness_to_pay", "said_by": "Buyer A", "said_role": "buyer",
        "quote": "We would allocate budget after the audit.", "supports": True,
    })

    assert response.status_code == 200
    assert evidence[0]["relation"] == "context"
    assert verdicts[0][1] == "primary_research_needed"


def test_decomposition_failure_is_explicit_and_saves_nothing(monkeypatch) -> None:
    saved = []

    async def broken(_llm, _thesis):
        raise RuntimeError("provider unavailable")

    async def create(*_args, **_kwargs):
        saved.append(True)

    monkeypatch.setattr(routes.dec, "decompose", broken)
    monkeypatch.setattr(routes.tstore, "create", create)
    client = _client(monkeypatch, raise_server_exceptions=False)

    response = client.post("/thesis", headers={"Authorization": "Bearer owner"},
                           json={"thesis": "A sufficiently long thesis sentence.", "max_usd": 0.01})

    assert response.status_code == 503
    assert saved == []


@pytest.mark.asyncio
async def test_author_statement_cannot_auto_settle_a_claim(monkeypatch) -> None:
    evidence, verdicts = [], []

    async def add_evidence(_pool, _thesis_id, _rung, rows):
        evidence.extend(rows)

    async def set_verdict(_pool, _thesis_id, rung, verdict, note="", **_kwargs):
        verdicts.append((rung, verdict, note))

    monkeypatch.setattr(routes.tstore, "add_evidence", add_evidence)
    monkeypatch.setattr(routes.tstore, "set_verdict", set_verdict)

    await routes._apply_effect(object(), "t1", {"rung": "problem_exists"},
                               {"effect": "answered"}, "I have seen this happen.")

    assert evidence[0]["relation"] == "context"
    assert verdicts[0][1] == "primary_research_needed"


def test_follow_up_turn_is_read_only_never_grades(monkeypatch) -> None:
    """The ship-gate integrity test: a tested-phase follow-up EXPLAINS; it writes no verdict, case,
    decision, or claim revision. Grading happens only in the explicit Test step."""
    writes: list[str] = []
    turns: list[dict] = []

    async def rec_turn(_pool, _tid, **kw):
        turns.append(kw)

    for name in ("set_verdict", "set_cases", "set_decision", "set_overall", "revise_claim",
                 "add_evidence", "set_focus"):
        async def _forbidden(*_a, _n=name, **_k):
            writes.append(_n)
        monkeypatch.setattr(routes.tstore, name, _forbidden, raising=False)
    monkeypatch.setattr(routes.tstore, "add_turn", rec_turn)

    c = _client(monkeypatch)
    r = c.post("/thesis/t1/turn", json={"text": "why is the buyer claim under-tested?",
                                        "rungs": ["problem_exists", "willingness_to_pay"]},
               headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200
    body = r.json()
    assert body["move"]["move"] == "explained"
    assert body["move"]["rungs"] == ["problem_exists", "willingness_to_pay"]
    assert writes == []                       # NOTHING was graded — the integrity invariant
    assert any(t.get("role") == "user" for t in turns)
    assert any(t.get("role") == "agent" for t in turns)


def test_follow_up_scopes_to_the_selected_claims(monkeypatch) -> None:
    seen: dict = {}

    async def spy_followup(_llm, *, thesis, claims, said, history):
        seen["rungs"] = [c["rung"] for c in claims]
        seen["said"] = said
        return {"reply": "grounded answer"}

    async def noop_turn(_pool, _tid, **kw):
        pass

    monkeypatch.setattr(routes.conv, "follow_up", spy_followup)
    monkeypatch.setattr(routes.tstore, "add_turn", noop_turn)
    c = _client(monkeypatch)
    r = c.post("/thesis/t1/turn", json={"text": "explain these", "rungs": ["willingness_to_pay"]},
               headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200
    assert seen["rungs"] == ["willingness_to_pay"]     # scoped to exactly the selected claim
    assert seen["said"] == "explain these"


def test_draft_creates_a_genesis_thesis_without_decomposing(monkeypatch) -> None:
    created: dict = {}

    async def fake_create(_pool, *, thesis, claims, subject, owner_id="", title=""):
        created["claims"] = claims
        created["thesis"] = thesis
        return {"id": "t1", "owner_token": None}

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(routes.tstore, "create", fake_create)
    monkeypatch.setattr(routes.tstore, "set_proposed_thesis", noop)
    monkeypatch.setattr(routes.tstore, "add_turn", noop)

    def boom_decompose(*_a, **_k):
        raise AssertionError("draft must NOT decompose")
    monkeypatch.setattr(routes.dec, "decompose", boom_decompose)

    c = _client(monkeypatch)
    r = c.post("/thesis", json={"thesis": "something for logistics", "draft": True},
               headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    assert created["claims"] == []            # a draft has no claims — it is still in genesis


def test_inquiries_and_generate_drive_the_decision_engine(monkeypatch):
    from types import SimpleNamespace
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE
    saved = {}

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token=""):
        return _thesis(owner=True) if thesis_id == "t1" and (owner_id == "user-1" or owner_token == "owner-cap") else None
    async def fake_set_questions(_pool, tid, inq, rows):
        saved.setdefault(inq, []).extend(rows)
    async def fake_list_questions(_pool, tid, inq=""):
        return [q for k, rows in saved.items() if (not inq or k == inq) for q in
                ({"inquiry_key": k, **r, "id": f"{k}{i}"} for i, r in enumerate(rows))]

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    monkeypatch.setattr(routes.tstore, "set_questions", fake_set_questions)
    monkeypatch.setattr(routes.tstore, "list_questions", fake_list_questions)
    # no LLM → generation falls open to one seek-support question per aspect (free, deterministic)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)

    # before generation: the 4 lines of inquiry exist, no questions
    r0 = c.get("/thesis/t1/inquiries", headers={"Authorization": "Bearer owner"})
    assert r0.status_code == 200
    assert [i["key"] for i in r0.json()["inquiries"]] == ["problem", "buyer", "timing", "market"]
    assert all(not i["questions"] for i in r0.json()["inquiries"])

    # generate → each aspect gets a question; every inquiry now carries questions
    r1 = c.post("/thesis/t1/inquiries/generate", headers={"Authorization": "Bearer owner"})
    assert r1.status_code == 200
    inqs = {i["key"]: i for i in r1.json()["inquiries"]}
    assert all(inqs[k]["questions"] for k in ("problem", "buyer", "timing", "market"))
    # a question carries its lens, reader text, and the declarative target the run will test
    q = inqs["market"]["questions"][0]
    assert q["kind"] == "seek_support" and q["text"] and q["target"]


def test_generate_requires_owner_and_a_profile(monkeypatch):
    from types import SimpleNamespace
    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token=""):
        return _thesis(owner=True) if thesis_id == "t1" and owner_id == "user-1" else None
    monkeypatch.setattr(routes.tstore, "get", fake_get)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    # no profile configured → 409, not a crash
    assert c.post("/thesis/t1/inquiries/generate", headers={"Authorization": "Bearer owner"}).status_code == 409
