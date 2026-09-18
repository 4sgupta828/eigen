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
    saved = {"rows": []}

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return _thesis(owner=True) if thesis_id == "t1" and (owner_id == "user-1" or owner_token == "owner-cap") else None
    async def fake_set_inquiries(_pool, tid, inquiries):
        saved["rows"] = []
        for order, inq in enumerate(inquiries):
            for i, q in enumerate(inq.get("questions") or []):
                saved["rows"].append({"inquiry_key": inq["key"], "inquiry_name": inq.get("name", ""),
                    "inquiry_framing": inq.get("framing", ""), "inquiry_order": order,
                    "aspect_key": q["dimension"], "kind": q["kind"], "text": q["text"],
                    "target": q["target"], "polarity": q.get("polarity", 1), "id": f"{inq['key']}{i}",
                    "target_status": "", "run_id": ""})
    async def fake_list_questions(_pool, tid, inq=""):
        return [r for r in saved["rows"] if not inq or r["inquiry_key"] == inq]

    # Generation is now a BACKGROUND run (kick off → poll → stop). Mock the run machinery so the kickoff
    # is testable; the generation LOGIC itself is covered by the kernel generate tests.
    created = {}
    async def fake_create_run(_pool, *, thesis_id, idempotency_key, projected_usd, approved_usd, metadata):
        created.update(id="run-1", metadata=metadata); return {"id": "run-1", "state": "approved", "metadata": metadata}
    async def fake_advance_run(_pool, *, thesis_id, run_id, stage, state="running", actual_delta=0.0):
        return {"id": run_id, "state": state, "stage": stage}
    async def fake_get_run(_pool, *, thesis_id, run_id):
        return {"id": run_id, "state": "running", "stage": "starting", "metadata": {"questions": []}}
    async def noop(*a, **k):
        return None

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    monkeypatch.setattr(routes.tstore, "set_inquiries", fake_set_inquiries)
    monkeypatch.setattr(routes.tstore, "list_questions", fake_list_questions)
    monkeypatch.setattr(routes.tstore, "create_run", fake_create_run)
    monkeypatch.setattr(routes.tstore, "advance_run", fake_advance_run)
    monkeypatch.setattr(routes.tstore, "get_run", fake_get_run)
    monkeypatch.setattr(routes.tstore, "fail_run", noop)
    monkeypatch.setattr(routes.tstore, "set_landscape_brief", noop)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)

    # before generation: no questions, no inquiries yet
    r0 = c.get("/thesis/t1/inquiries", headers={"Authorization": "Bearer owner"})
    assert r0.status_code == 200 and r0.json()["inquiries"] == []

    # generate → kicks off a background run and returns immediately (no gateway-timeout-length blocking)
    r1 = c.post("/thesis/t1/inquiries/generate", headers={"Authorization": "Bearer owner"})
    assert r1.status_code == 200
    body = r1.json()
    assert body["status"] == "running" and body["run"]["id"] == "run-1"
    assert created["metadata"].get("generate") is True


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


def test_generate_frames_the_thesis_then_asks_questions_of_the_frame(monkeypatch):
    """The generate route runs the UNDERSTANDING step first (feeding it the genesis conversation) and
    hands the frame's specific assumptions/risks to the question step — not just the fixed rubric."""
    from types import SimpleNamespace
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE
    saw = {"frame_user": "", "gen_user": ""}
    saved = {"rows": []}

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        if thesis_id != "t1" or owner_id != "user-1":
            return None
        d = _thesis(owner=True)
        d["turns"] = [{"role": "user", "move": "say", "rung": "", "rungs": [],
                       "text": "We sell to hospital procurement, not to nurses.", "payload": {}}]
        return d
    async def fake_set_inquiries(_pool, tid, inquiries):
        saved["rows"] = []
        for order, inq in enumerate(inquiries):
            for i, q in enumerate(inq.get("questions") or []):
                saved["rows"].append({"inquiry_key": inq["key"], "inquiry_name": inq.get("name", ""),
                    "inquiry_framing": inq.get("framing", ""), "inquiry_order": order,
                    "aspect_key": q["dimension"], "kind": q["kind"], "text": q["text"],
                    "target": q["target"], "polarity": q.get("polarity", 1), "id": f"{inq['key']}{i}",
                    "target_status": "", "run_id": ""})
    async def fake_list_questions(_pool, tid, inq=""):
        return [r for r in saved["rows"] if not inq or r["inquiry_key"] == inq]

    import re as _re
    saw["gen_users"] = []
    async def llm_json(system, user):
        if "UNDERSTANDING" in user:                       # the frame step
            saw["frame_user"] = user
            return {"reading": "Sells to hospital procurement.",
                    "assumptions": [{"text": "Procurement, not nurses, holds the budget",
                                     "dimension": "buyer_nameable"}],
                    "risks": [{"text": "Procurement cycles are 18 months", "dimension": "catalyst"}],
                    "unknowns": [], "anchors": ["hospital procurement"]}
        # Every generation call (per line of inquiry, and the gap-fill) lists its dimension keys as
        # "- <key>:"; return one thesis-native question per key so the whole contract is covered.
        keys = _re.findall(r"^- (\w+):", user, _re.M)
        if "COVERAGE GAP" not in user:
            saw["gen_users"].append(user)                 # a MAIN per-inquiry, frame-driven call
        return {"questions": [{"dimension": k, "kind": "seek_support",
                               "text": f"Does the record settle {k} for hospital procurement?",
                               "target": f"The record settles {k}.", "polarity": 1} for k in keys]}

    # Generation is a background run now (untestable fire-and-forget under TestClient), so exercise the
    # frame -> generation COUPLING that `_run_generate` performs directly against the decision module.
    import asyncio as _asyncio
    from eigen_kernel import decision as _dec2
    profile = TECH_DECISION_PROFILE
    decision = "We sell an AI product to hospital procurement."
    async def _drive():
        frame = await _dec2.frame_decision(
            llm_json, decision=decision,
            context="THE CONVERSATION:\nWe sell to hospital procurement, not to nurses.",
            directive=profile.frame_directive(decision), aspects=profile.aspects())
        inquiries = await _dec2.generate_by_inquiry(
            llm_json, decision=decision, inquiries=profile.inquiries(), aspects=profile.aspects(),
            directive=profile.inquiry_directive(decision),
            frame=frame if _dec2.is_substantive(frame) else None)
        return inquiries
    inquiries = _asyncio.run(_drive())
    # the conversation reached the framing step
    assert "hospital procurement, not to nurses" in saw["frame_user"]
    # generation is PER LINE OF INQUIRY — several focused calls, not one
    assert len(saw["gen_users"]) >= 2
    allgen = "\n".join(saw["gen_users"])
    # the frame's tagged assumption + risk reached the focused call for their line of inquiry (depth)
    assert "Procurement, not nurses, holds the budget" in allgen   # buyer_nameable → the buyer inquiry
    assert "Procurement cycles are 18 months" in allgen            # catalyst → the timing inquiry
    assert "LINE OF INQUIRY:" in allgen                            # focused per-inquiry prompt, not a rubric dump
    # coverage still enforced across the full rubric
    covered = {q["dimension"] for inq in inquiries for q in (inq.get("questions") or [])}
    assert {a.key for a in profile.aspects()} <= covered


def test_delete_line_and_clear_all_are_owner_gated_and_preserve_answered(monkeypatch):
    """Per-line delete and clear-all remove drafted questions via the store; a reader cannot, and the
    store calls target only unrun questions (answered work is preserved there)."""
    from types import SimpleNamespace
    calls = {"line": [], "clear": []}

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else ({"id": "user-2"} if token == "Bearer other" else {})
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return _thesis(owner=True) if thesis_id == "t1" and owner_id == "user-1" else None
    async def fake_remove_inquiry(_pool, tid, key):
        calls["line"].append((tid, key)); return 2
    async def fake_clear_inquiries(_pool, tid):
        calls["clear"].append(tid); return 5

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    monkeypatch.setattr(routes.tstore, "remove_inquiry", fake_remove_inquiry)
    monkeypatch.setattr(routes.tstore, "clear_inquiries", fake_clear_inquiries)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)

    # owner: delete one line
    r = c.delete("/thesis/t1/inquiry/buyer", headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200 and r.json()["removed"] == 2
    assert calls["line"] == [("t1", "buyer")]

    # owner: clear all
    r = c.delete("/thesis/t1/inquiries", headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200 and r.json()["removed"] == 5
    assert calls["clear"] == ["t1"]

    # a non-owner is refused (owner_only read gate) and never reaches the store
    r = c.delete("/thesis/t1/inquiries", headers={"Authorization": "Bearer other"})
    assert r.status_code in (401, 403, 404)
    assert calls["clear"] == ["t1"]      # unchanged — the reader's call did not mutate


def test_experts_surfaces_who_and_what_to_ask_for_call_only_aspects(monkeypatch):
    """Phase 0 Expert mode: /experts returns the call_only aspects with the role to ask, this thesis's
    questions for that aspect, and any candidate named in already-gathered evidence."""
    from types import SimpleNamespace
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        if thesis_id != "t1" or owner_id != "user-1":
            return None
        d = _thesis(owner=True)
        d["subject"] = {"segment": "mid-market 3PLs"}
        # an operator named in an eng_blog artifact — people.from_evidence should surface them
        d["claims"] = [{"rung": "switching_feasible", "evidence": [
            {"source_key": "eng_blog", "quote": "We migrated off handheld scanners over six months.",
             "title": "Our warehouse cutover", "source_url": "https://ops.example/cutover",
             "register": "stated", "facets": {"author": "Dana Ops"}}]}]
        return d
    async def fake_list_questions(_pool, tid, inq=""):
        return [{"id": "q1", "aspect_key": "switching_feasible", "kind": "seek_support",
                 "text": "How long did your last tooling cutover actually take?", "target": "t",
                 "polarity": 1, "target_status": "", "inquiry_key": "timing", "inquiry_name": "Timing",
                 "inquiry_framing": "", "inquiry_order": 0, "run_id": ""}]

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    monkeypatch.setattr(routes.tstore, "list_questions", fake_list_questions)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    r = c.get("/thesis/t1/experts", headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200
    aspects = {a["key"]: a for a in r.json()["aspects"]}
    # only call_only aspects appear — now including team credibility (founder-market fit, panel 2026-09-16)
    assert set(aspects) == {"switching_feasible", "willingness_to_pay", "team_credibility"}
    sf = aspects["switching_feasible"]
    assert any(role["role"] == "operator" for role in sf["roles"])          # ASK_WHO role surfaced
    assert "How long did your last tooling cutover actually take?" in sf["questions"]   # what to ask
    assert any(cand["name"] == "Dana Ops" and cand["role"] == "operator" for cand in sf["candidates"])
    # willingness_to_pay is a buyer rung with no named buyer → honest guidance, not a fake contact
    wtp = aspects["willingness_to_pay"]
    assert wtp["candidates"] == [] and "economic buyer" in wtp["guidance"]


def test_experts_is_empty_without_a_profile(monkeypatch):
    from types import SimpleNamespace
    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return _thesis(owner=True) if thesis_id == "t1" and owner_id == "user-1" else None
    monkeypatch.setattr(routes.tstore, "get", fake_get)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    r = c.get("/thesis/t1/experts", headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200 and r.json()["aspects"] == []


def test_experts_discover_runs_the_people_leg_scoped_to_a_call_only_aspect(monkeypatch):
    """Phase 1: /experts/discover phrases a query per role (vertical), runs the kernel people leg, and
    returns PUBLIC profile links for a call_only aspect only — never for a corpus aspect."""
    from types import SimpleNamespace
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE
    from eigen_kernel.providers.people_search import PersonResult
    import eigen_kernel.runtime.build as kbuild
    captured = {"queries": []}

    class _FakePeople:
        async def search(self, query, *, max_results=8, filters=None):
            captured["queries"].append(query)
            return [PersonResult(name="Dana Ops", profile_url="https://linkedin.com/in/dana",
                                 headline="VP Operations, Acme 3PL", provider="exa", relevance=0.9)]
    monkeypatch.setattr(kbuild, "build_people", lambda **k: _FakePeople())

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        if thesis_id != "t1" or owner_id != "user-1":
            return None
        d = _thesis(owner=True); d["subject"] = {"segment": "mid-market 3PLs"}; return d
    monkeypatch.setattr(routes.tstore, "get", fake_get)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}, people_domains=()),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    # a call_only aspect → discovery runs
    r = c.post("/thesis/t1/experts/discover", headers={"Authorization": "Bearer owner"},
               json={"aspect_key": "switching_feasible"})
    assert r.status_code == 200
    cands = r.json()["candidates"]
    assert cands and cands[0]["name"] == "Dana Ops" and cands[0]["profile_url"].startswith("https://linkedin")
    assert any("mid-market 3PLs" in q for q in captured["queries"])   # vertical phrased it in-segment
    # a corpus aspect is refused (thesis-scoped to call_only, no directory drift)
    r2 = c.post("/thesis/t1/experts/discover", headers={"Authorization": "Bearer owner"},
                json={"aspect_key": "problem_exists"})
    assert r2.status_code == 400


def test_transcript_extracts_gated_call_evidence_and_moves_the_verdict(monkeypatch):
    """Phase 3: a transcript → verbatim-gated call evidence on a call_only aspect; the first account
    lands as primary_research_needed (never a settle from one voice)."""
    from types import SimpleNamespace
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE
    written, verdicts = {"rows": []}, []
    T = "Buyer: switching took a single weekend, far easier than we budgeted for."

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        if thesis_id != "t1":
            return None
        if not (owner_id == "user-1" or trusted):
            return None
        d = _thesis(owner=True); d["subject"] = {"segment": "3PLs"}
        d["claims"] = [{"rung": "switching_feasible", "evidence": list(written["rows"])}]
        return d
    async def add_evidence(_pool, tid, rung, rows):
        for r in rows:
            written["rows"].append(r)
        return len(rows)
    async def set_verdict(_pool, tid, rung, verdict, note="", **k):
        verdicts.append((rung, verdict))
    async def llm_json(system, user):
        return {"points": [{"quote": "switching took a single weekend, far easier than we budgeted for",
                            "point": "Switching was easy.", "relation": "supports"}]}

    monkeypatch.setattr(routes.tstore, "get", fake_get)
    monkeypatch.setattr(routes.tstore, "add_evidence", add_evidence)
    monkeypatch.setattr(routes.tstore, "set_verdict", set_verdict)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=SimpleNamespace(llm_json=llm_json),
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    r = c.post("/thesis/t1/experts/transcript", headers={"Authorization": "Bearer owner"},
               json={"aspect_key": "switching_feasible", "said_by": "Dana", "said_role": "buyer",
                     "firm": "Acme 3PL", "transcript": T})
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) == 1 and body["points"][0]["relation"] == "supports"
    assert body["verdict"] == "primary_research_needed"          # one account is never a settle
    # the written row is typed call evidence, private, first-hand
    row = written["rows"][0]
    assert row["source_key"] == "call" and row["register"] == "stated" and row["signal_only"] is False
    assert row["said_by"] == "Dana" and row["source_subject"] == "Acme 3PL"
    # a corpus aspect is refused
    r2 = c.post("/thesis/t1/experts/transcript", headers={"Authorization": "Bearer owner"},
                json={"aspect_key": "problem_exists", "transcript": T})
    assert r2.status_code == 400


def test_experts_search_is_standalone_no_thesis_required(monkeypatch):
    """The first-class Experts mode: a freeform people search that needs no thesis."""
    from types import SimpleNamespace
    from eigen_kernel.providers.people_search import PersonResult
    import eigen_kernel.runtime.build as kbuild

    class _FakePeople:
        async def search(self, query, *, max_results=8, filters=None):
            return [PersonResult(name="Dana Ops", profile_url="https://linkedin.com/in/dana",
                                 headline="VP Operations, Acme 3PL", provider="exa")]
    monkeypatch.setattr(kbuild, "build_people", lambda **k: _FakePeople())

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "u"} if token else {}
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None,
                                 web_domains=(), retrieval_sources={}, people_domains=()),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    r = c.post("/experts/search", json={"query": "warehouse operations leaders at 3PLs"})
    assert r.status_code == 200
    cands = r.json()["candidates"]
    assert cands and cands[0]["name"] == "Dana Ops" and cands[0]["profile_url"].startswith("https://linkedin")
    # too-short query is refused
    assert c.post("/experts/search", json={"query": "x"}).status_code == 400


def test_experts_search_passes_structured_filters_to_the_people_leg(monkeypatch):
    from types import SimpleNamespace
    from eigen_kernel.providers.people_search import PersonResult
    import eigen_kernel.runtime.build as kbuild
    seen = {}

    class _FakePeople:
        async def search(self, query, *, max_results=8, filters=None):
            seen["query"] = query; seen["filters"] = filters
            return [PersonResult(name="Dana Ops", profile_url="https://linkedin.com/in/dana", provider="pdl")]
    monkeypatch.setattr(kbuild, "build_people", lambda **k: _FakePeople())
    async def pool_of():
        return object()
    async def user_of(token):
        return {}
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None,
                                 web_domains=(), retrieval_sources={}, people_domains=()),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    # filters-only (no freeform query) is allowed and passed through
    r = c.post("/experts/search", json={"query": "", "filters": {"title": "VP Operations",
               "past_company": "Amazon", "location": "Texas"}})
    assert r.status_code == 200 and r.json()["candidates"][0]["name"] == "Dana Ops"
    assert seen["filters"] == {"title": "VP Operations", "past_company": "Amazon", "location": "Texas"}
    assert "VP Operations" in seen["query"]           # filters folded into the Exa query too


def _genesis_client(monkeypatch, *, llm, captured):
    """A router wired for the genesis shaping endpoints: a DRAFT thesis (no claims), a model, and the
    versioning/turn store functions mocked so we can assert what the endpoints persist."""
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    draft = {"id": "t1", "thesis": "", "proposed_thesis": "Companies will pay for X.", "subject": {},
             "is_owner": True, "claims": [], "turns": [], "versions": captured["versions"], "shaping_prefs": []}

    async def pool_of(): return object()
    async def user_of(token): return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return draft if thesis_id == "t1" and (owner_id == "user-1" or owner_token == "owner-cap") else None
    async def fake_add_version(_pool, tid, text, *, source="", rationale="", parent_id=""):
        vid = f"v{len(captured['versions']) + 1}"
        captured["versions"].append({"id": vid, "text": text, "source": source, "rationale": rationale,
                                     "active": True})
        return vid
    async def fake_list(_pool, tid): return captured["versions"]
    async def fake_revert(_pool, tid, vid):
        v = next((x for x in captured["versions"] if x["id"] == vid), None)
        return {"id": vid, "text": v["text"]} if v else None
    async def fake_prefs(_pool, tid, prefs): captured["prefs"] = prefs
    async def fake_turn(_pool, tid, *, role, move="", text="", payload=None, **_k):
        captured["turns"].append({"role": role, "move": move, "text": text, "payload": payload or {}})
    for name, fn in [("get", fake_get), ("add_thesis_version", fake_add_version),
                     ("list_thesis_versions", fake_list), ("revert_thesis_version", fake_revert),
                     ("set_shaping_prefs", fake_prefs), ("add_turn", fake_turn)]:
        monkeypatch.setattr(routes.tstore, name, fn)
    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=SimpleNamespace(llm_json=llm),
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=None,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    return TestClient(app)


def test_improve_applies_a_version_and_carries_proposed_thesis_for_the_card(monkeypatch):
    # Regression: after Improve, the working-thesis card vanished because the improve turn stored
    # `improved_thesis`, but the client card keys on `proposed_thesis`. The turn must carry it.
    cap = {"versions": [], "turns": [], "prefs": None}
    async def llm(_system, _user):
        return {"questions": [{"q": "Who buys?", "a": "The VP of RevOps."}, {"q": "no answer"}],
                "improved_thesis": "RevOps teams at mid-market SaaS will pay for X because Y.",
                "rationale": "Named the buyer and mechanism.", "shaping_prefs": ["wants a named buyer"]}
    c = _genesis_client(monkeypatch, llm=llm, captured=cap)
    r = c.post("/thesis/t1/improve", json={}, headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True and "RevOps" in body["proposed_thesis"]
    assert len(body["questions"]) == 1                       # self-answered, the untyped junk dropped
    assert len(cap["versions"]) == 1                         # a backtrackable version was created
    imp = next(t for t in cap["turns"] if t["move"] == "improve")
    assert imp["payload"]["proposed_thesis"].startswith("RevOps")   # the card renders (the fix)
    assert cap["prefs"] == ["wants a named buyer"]           # shaping memory persisted


def test_versions_and_revert_backtrack_the_thesis(monkeypatch):
    cap = {"versions": [{"id": "v1", "text": "First wording.", "source": "genesis", "active": False},
                        {"id": "v2", "text": "Second wording.", "source": "self_improve", "active": True}],
           "turns": [], "prefs": None}
    async def llm(_s, _u): return {}
    c = _genesis_client(monkeypatch, llm=llm, captured=cap)
    v = c.get("/thesis/t1/versions", headers={"Authorization": "Bearer owner"})
    assert v.status_code == 200 and len(v.json()["versions"]) == 2
    r = c.post("/thesis/t1/revert", json={"version_id": "v1"}, headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200 and r.json()["proposed_thesis"] == "First wording."   # backtracked
    bad = c.post("/thesis/t1/revert", json={"version_id": "nope"}, headers={"Authorization": "Bearer owner"})
    assert bad.status_code == 404


def test_brainstorm_thread_message_and_expand_kickoff(monkeypatch):
    """The brainstorm surface: open a thread, post a message (user msg persisted + async turn kicked
    off), list threads, and fire an enrichment leg. The turn/leg LOGIC is covered elsewhere; here we
    assert the endpoints wire the run machinery correctly."""
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": "user-1"} if token == "Bearer owner" else {}
    async def fake_get(_pool, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return _thesis(owner=True) if thesis_id == "t1" and (owner_id == "user-1" or trusted) else None

    store = {"threads": {}, "msgs": []}
    async def fake_create_thread(_pool, *, thesis_id, owner_id="", title=""):
        tid = "bs_1"; store["threads"][tid] = {"id": tid, "thesis_id": thesis_id, "title": title, "memory": {}}
        return dict(store["threads"][tid])
    async def fake_get_thread(_pool, *, thesis_id, thread_id):
        t = store["threads"].get(thread_id)
        if not t:
            return None
        out = dict(t); out["messages"] = [m for m in store["msgs"] if m["thread_id"] == thread_id]; return out
    async def fake_list_threads(_pool, *, thesis_id):
        return [dict(t, messages=0) for t in store["threads"].values()]
    async def fake_add_msg(_pool, *, thesis_id, thread_id, role, content):
        store["msgs"].append({"thread_id": thread_id, "role": role, "content": content}); return len(store["msgs"])
    async def fake_rename(_pool, *, thesis_id, thread_id, title):
        store["threads"][thread_id]["title"] = title
    async def noop(*a, **k):
        return None

    created = {}
    async def fake_create_run(_pool, *, thesis_id, idempotency_key, projected_usd, approved_usd, metadata):
        created.update(metadata=metadata); return {"id": "run-1", "state": "approved", "metadata": metadata}
    async def fake_advance_run(_pool, *, thesis_id, run_id, stage, state="running", actual_delta=0.0):
        return {"id": run_id, "state": state, "stage": stage}
    async def fake_get_run(_pool, *, thesis_id, run_id):
        return {"id": run_id, "state": "cancelled"}   # so the fire-and-forget task exits immediately
    async def fake_list_questions(_pool, tid, inq=""):
        return []

    for name, fn in [("get", fake_get), ("create_brainstorm_thread", fake_create_thread),
                     ("get_brainstorm_thread", fake_get_thread), ("list_brainstorm_threads", fake_list_threads),
                     ("add_brainstorm_msg", fake_add_msg), ("rename_brainstorm_thread", fake_rename),
                     ("set_brainstorm_memory", noop), ("delete_brainstorm_thread", noop),
                     ("create_run", fake_create_run), ("advance_run", fake_advance_run),
                     ("get_run", fake_get_run), ("fail_run", noop), ("list_questions", fake_list_questions)]:
        monkeypatch.setattr(routes.tstore, name, fn, raising=False)

    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), people_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    c = TestClient(app)
    H = {"Authorization": "Bearer owner"}

    # open a thread
    r = c.post("/thesis/t1/brainstorm/thread", json={}, headers=H)
    assert r.status_code == 200
    tid = r.json()["thread"]["id"]

    # post a message → user msg persisted, async turn kicked off
    r = c.post(f"/thesis/t1/brainstorm/thread/{tid}/message", json={"text": "Where is this weakest?"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert created["metadata"].get("brainstorm") is True and created["metadata"]["thread_id"] == tid
    assert any(m["role"] == "user" and m["content"]["text"] == "Where is this weakest?" for m in store["msgs"])

    # empty message rejected
    assert c.post(f"/thesis/t1/brainstorm/thread/{tid}/message", json={"text": "  "}, headers=H).status_code == 400

    # list past brainstorms
    r = c.get("/thesis/t1/brainstorm/threads", headers=H)
    assert r.status_code == 200 and len(r.json()["threads"]) == 1

    # expand: unknown leg rejected, known leg kicks off a run
    assert c.post(f"/thesis/t1/brainstorm/thread/{tid}/expand", json={"leg": "bogus"}, headers=H).status_code == 400
    r = c.post(f"/thesis/t1/brainstorm/thread/{tid}/expand", json={"leg": "experts", "query": "RevOps"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert created["metadata"].get("expand") == "experts"
