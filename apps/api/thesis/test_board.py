"""ThesisBoard sanitizers — the anonymity + answered-only invariants that keep a public snapshot safe.
These are the security-critical guarantees (no submitter identity, no private evidence, no empty plans
leaked to the world), so they get a direct test rather than relying on the route wiring."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.thesis import board as b
from api.thesis import routes


def _board_client(monkeypatch):
    """A TestClient whose store is faked with an in-memory board, so the publish → list → get → unpublish
    ROUTE flow (including the anonymize + answered-only transforms the route applies) is exercised end to
    end without a database."""
    from eigen_vertical_tech.decision import TECH_DECISION_PROFILE
    BOARD: dict[str, dict] = {}
    OWNER = "user-1"

    def _thesis():
        return {"id": "t1", "owner_id": OWNER, "title": "Acme", "thesis": "Acme wins freight ML for brokers.",
                "subject": {"company": "Acme"}, "is_owner": True, "share_token": "s", "owner_token_hash": "h",
                "versions": [{"text": "old"}], "shaping_prefs": ["x"], "turns": [{"role": "user", "text": "p"}],
                "pitch_deck": {"spine": {}}, "collective_take": {}, "competitive": {},
                "claims": [{"rung": "problem_exists", "evidence": [
                    {"id": "e1", "source_key": "call", "quote": "private"},
                    {"id": "e2", "source_key": "sec", "quote": "public"}]}]}

    QUESTIONS = [
        {"id": "q1", "inquiry_key": "problem", "inquiry_name": "Is the problem real?", "inquiry_framing": "",
         "inquiry_order": 0, "aspect_key": "problem_exists", "text": "Is the pain real?",
         "kind": "seek_support", "target": "Brokers lose money to it", "polarity": 1,
         "target_status": "target_supported", "answer": "Yes, brokers lose 3% [[e:e2]]", "priority": 0},
        {"id": "q2", "inquiry_key": "problem", "inquiry_name": "Is the problem real?", "inquiry_framing": "",
         "inquiry_order": 0, "aspect_key": "status_quo_costs", "text": "Does it cost?",
         "kind": "seek_support", "target": "The status quo costs money", "polarity": 1,
         "target_status": "", "answer": "", "priority": 1},              # UNANSWERED — must be stripped
    ]

    async def pool_of():
        return object()
    async def user_of(token):
        return {"id": OWNER} if token == "Bearer owner" else {}
    async def fake_get(_p, *, thesis_id="", share_token="", owner_id="", owner_token="", trusted=False):
        return _thesis() if thesis_id == "t1" and (owner_id == OWNER or owner_token == "owner-cap") else None
    async def fake_list_questions(_p, tid, inq=""):
        return [q for q in QUESTIONS if not inq or q["inquiry_key"] == inq]
    async def fake_publish_board(_p, *, thesis_id, owner_id, title, summary, payload, findings):
        eid = BOARD.get(thesis_id, {}).get("id") or ("b_" + thesis_id)
        BOARD[thesis_id] = {"id": eid, "thesis_id": thesis_id, "owner_id": owner_id, "title": title,
                            "summary": summary, "findings": findings, "payload": payload}
        return eid
    async def fake_board_list(_p, *, limit=60):
        return [{"id": e["id"], "title": e["title"], "summary": e["summary"], "findings": e["findings"],
                 "published_at": "2026-09-17T00:00:00", "updated_at": "2026-09-17T00:00:00"}
                for e in BOARD.values()]
    async def fake_board_get(_p, entry_id):
        e = next((x for x in BOARD.values() if x["id"] == entry_id), None)
        if not e:
            return None
        out = dict(e["payload"])
        out.update({"board_id": e["id"], "title": e["title"], "summary": e["summary"],
                    "findings": e["findings"], "published_at": "2026-09-17T00:00:00", "anonymous": True})
        return out                                          # NB: no thesis_id / owner_id
    async def fake_entry_for(_p, thesis_id):
        return BOARD.get(thesis_id, {}).get("id", "")
    async def fake_delete(_p, thesis_id):
        BOARD.pop(thesis_id, None)
    async def fake_voices(_p, thesis_id):
        return {"buckets": [{"label": "Supports the thesis", "items": [{"id": "v1", "why": "backs pricing"}]}],
                "moments": [{"id": "v1", "kind": "podcast", "title": "Freight ML", "speaker": "A Founder"}]}
    async def fake_bs_full(_p, *, thesis_id):
        return [{"id": "th1", "owner_id": OWNER, "thesis_id": thesis_id, "title": "Bear case",
                 "messages": [{"role": "user", "content": {"text": "what breaks this?"}},
                              {"role": "agent", "content": {"reply": "Distribution."}}]}]

    for name, fn in [("get", fake_get), ("list_questions", fake_list_questions),
                     ("publish_board", fake_publish_board), ("board_list", fake_board_list),
                     ("board_get", fake_board_get), ("board_entry_for_thesis", fake_entry_for),
                     ("board_delete", fake_delete), ("get_thesis_voices", fake_voices),
                     ("get_brainstorm_threads_full", fake_bs_full)]:
        monkeypatch.setattr(routes.tstore, name, fn)

    app = FastAPI()
    app.include_router(routes.build_router(
        pool_of, providers=None,
        manifest=SimpleNamespace(ui=None, thesis_policy=None, decision_profile=TECH_DECISION_PROFILE,
                                 web_domains=(), retrieval_sources={}),
        user_of=user_of, tenant="t"))
    return TestClient(app), BOARD


def test_publish_lists_and_serves_an_anonymized_answered_only_snapshot(monkeypatch):
    c, BOARD = _board_client(monkeypatch)
    H = {"Authorization": "Bearer owner"}
    # board starts empty and is public (no auth)
    assert c.get("/board").json()["entries"] == []
    # publish
    r = c.post("/thesis/t1/publish", headers=H)
    assert r.status_code == 200
    entry_id = r.json()["board_id"]
    # stored payload is anonymized + answered-only (the security-critical assertions)
    stored = BOARD["t1"]["payload"]
    doc = stored["doc"]
    assert "owner_id" not in doc and "versions" not in doc and doc["id"] == "" and doc["turns"] == []
    assert [e["id"] for e in doc["claims"][0]["evidence"]] == ["e2"]      # private 'call' evidence gone
    assert [q["id"] for i in stored["inq"]["inquiries"] for q in i["questions"]] == ["q1"]  # q2 stripped
    assert BOARD["t1"]["findings"] == 1
    # the snapshot also carries the organized Voices and the Brainstorm threads, anonymized + self-contained
    assert stored["inq"]["voices"]["buckets"][0]["label"] == "Supports the thesis"
    assert stored["inq"]["voices"]["moments"][0]["id"] == "v1"
    bs = stored["inq"]["brainstorm"]
    assert len(bs) == 1 and bs[0]["title"] == "Bear case"
    assert "owner_id" not in bs[0] and "thesis_id" not in bs[0]              # identity stripped
    assert [m["role"] for m in bs[0]["messages"]] == ["user", "agent"]
    # public list + entry (no auth) never expose identity
    listed = c.get("/board").json()["entries"]
    assert len(listed) == 1 and listed[0]["id"] == entry_id and "owner_id" not in listed[0]
    entry = c.get("/board/" + entry_id).json()["entry"]
    assert entry["anonymous"] is True and "owner_id" not in entry and "thesis_id" not in entry
    assert entry["doc"]["thesis"] == "Acme wins freight ML for brokers."


def test_owner_get_shows_board_status_then_unpublish_removes_it(monkeypatch):
    c, BOARD = _board_client(monkeypatch)
    H = {"Authorization": "Bearer owner"}
    c.post("/thesis/t1/publish", headers=H)
    # owner GET reports where it's published
    assert c.get("/thesis/t1", headers=H).json()["thesis"]["board_entry"] == BOARD["t1"]["id"]
    # unpublish clears it
    assert c.request("DELETE", "/thesis/t1/publish", headers=H).status_code == 200
    assert "t1" not in BOARD
    assert c.get("/board").json()["entries"] == []


def test_publish_requires_at_least_one_answered_line(monkeypatch):
    c, BOARD = _board_client(monkeypatch)
    # wipe answers so nothing qualifies
    async def none_answered(_p, tid, inq=""):
        return [{"id": "q1", "inquiry_key": "problem", "aspect_key": "problem_exists", "text": "q",
                 "inquiry_name": "n", "inquiry_framing": "", "inquiry_order": 0, "target_status": "", "answer": ""}]
    monkeypatch.setattr(routes.tstore, "list_questions", none_answered)
    r = c.post("/thesis/t1/publish", headers={"Authorization": "Bearer owner"})
    assert r.status_code == 409 and "answer at least one" in r.json()["detail"]


def test_board_endpoints_are_public_no_auth(monkeypatch):
    c, _ = _board_client(monkeypatch)
    assert c.get("/board").status_code == 200                 # no Authorization header
    assert c.get("/board/does-not-exist").status_code == 404


def _doc():
    return {
        "id": "thesis-secret-16", "owner_id": "user-42", "thesis": "Acme wins logistics ML",
        "title": "Acme thesis", "subject": {"company": "Acme", "segment": "freight"},
        "is_owner": True, "share_token": "should-be-gone", "owner_token_hash": "hash",
        "versions": [{"text": "older wording", "rationale": "why"}],
        "shaping_prefs": ["prefers a named buyer"], "proposed_thesis": "draft", "decision": {"x": 1},
        "turns": [{"role": "user", "text": "private brainstorming"}],
        "claims": [{"rung": "problem", "thesis_id": "thesis-secret-16", "evidence": [
            {"id": "e1", "source_key": "call", "quote": "private expert call", "said_by": "an expert"},
            {"id": "e2", "source_key": "sec", "quote": "public filing says X", "source_subject": "Acme",
             "thesis_id": "thesis-secret-16"}]}],
    }


def test_anonymize_strips_submitter_identity_and_private_state():
    a = b.anonymize_doc(_doc())
    # submitter identity + private working state are gone
    for k in ("owner_id", "share_token", "owner_token_hash", "versions", "shaping_prefs",
              "proposed_thesis", "decision"):
        assert k not in a, f"{k} leaked into the public snapshot"
    assert a["id"] == "" and a["is_owner"] is False and a["turns"] == []   # no source id, no owner, no chat
    # the ANALYSIS itself is kept — the subject/company is the point of the thesis, not the author
    assert a["thesis"] == "Acme wins logistics ML" and a["subject"] == {"company": "Acme", "segment": "freight"}


def test_anonymize_drops_private_expert_call_evidence_keeps_public():
    a = b.anonymize_doc(_doc())
    claim = a["claims"][0]
    assert "thesis_id" not in claim                        # the internal source id never leaks
    ev = claim["evidence"]
    assert [e["id"] for e in ev] == ["e2"]                 # the owner-only 'call' row is removed
    assert ev[0]["quote"] == "public filing says X"        # public evidence survives (citations resolve)
    assert "thesis_id" not in ev[0]                        # nor on the evidence rows


def test_anonymize_does_not_mutate_the_original():
    d = _doc()
    b.anonymize_doc(d)
    assert d["owner_id"] == "user-42" and len(d["claims"][0]["evidence"]) == 2   # original untouched


def test_answered_only_strips_unanswered_lines_and_questions():
    inq = [
        {"key": "problem", "questions": [
            {"target_status": "target_supported", "answer": "yes, churn is 30% [[e:e2]]"},
            {"target_status": "", "answer": ""},                      # unanswered — dropped
            {"target_status": "target_untested", "answer": "   "}]},  # blank answer — dropped
        {"key": "market", "questions": [                              # whole line unanswered — dropped
            {"target_status": "", "answer": ""}]},
    ]
    out = b.answered_inquiries(inq)
    assert [i["key"] for i in out] == ["problem"]
    assert len(out[0]["questions"]) == 1 and b.answered_count(out) == 1
