"""TestStartupThesis routes — the conversational stress tester.

The mode is a conversation whose job is to attack a thesis, and every agent turn closes as exactly
one of three moves:

  settled       — the record answers this rung; here it is, with its register and source
  attacked      — here is the strongest disconfirming evidence a red-team model went looking for
  needs_person  — no document can settle this; here is who could, and what to ask them

A turn that does none of those wasted the reader's time, and `next_move` never emits a fourth kind.

The mode is flag-gated (EIGEN_THESIS). OFF is a true no-op: no routes, no tables touched.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import argue as arg
from . import attack as atk
from . import converse as conv
from . import decompose as dec
from . import genesis as gen
from . import people as ppl
from . import store as tstore
from .schema import (
    ASK_WHO, CALL_ONLY, OPEN, QUESTION, ROLE_LABEL, SET_ASIDE, SETTLEABLE, STATED, UNSETTLEABLE,
    VERDICT_LABEL, labels,
)


def thesis_enabled() -> bool:
    return os.environ.get("EIGEN_THESIS", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_tenant(value: str = "") -> str:
    return (value or os.environ.get("EIGEN_TENANT_ID") or "demo").strip()


class NewThesis(BaseModel):
    thesis: str = ""
    title: str = ""
    project_only: bool = False
    max_usd: float = 0.0
    draft: bool = False       # create a genesis draft (no decompose, no cost) and converse to a thesis


class GenesisIn(BaseModel):
    text: str = ""            # the author's latest message in the genesis conversation


class ConfirmIn(BaseModel):
    thesis: str = ""          # the sentence the USER accepted/edited — the only commit of the thesis
    max_usd: float = 0.0
    project_only: bool = False


class AttackIn(BaseModel):
    run_id: str = ""
    rung: str = ""            # one rung, or blank for every rung the record could speak to
    # The web leg, used ONLY where our own corpus said nothing — corpus-first is the standing
    # directive and also the cheap order. A demand thesis about a market segment is exactly the case
    # the corpus is thin on and the open web is not.
    web: bool = True
    max_usd: float = 0.25
    # Writing the cases re-argues the WHOLE thesis, so doing it inside a per-claim attack costs one
    # full call per claim and argues most of them against evidence that has not been gathered yet.
    # The client attacks claim by claim (so it can show real progress) and then calls /argue once.
    argue: bool = True


class CallIn(BaseModel):
    """What an expert actually said, attached to the claim it bears on."""
    rung: str
    said_by: str = ""
    said_role: str = ""       # buyer | operator | advisor
    quote: str = ""
    supports: bool = True


class TurnIn(BaseModel):
    text: str = ""            # the user pushing back; blank asks the agent to open
    # WHICH ROW this question is about. A follow-up hung off a table row carries its own subject, so
    # the answer lands on the claim it actually bears on — the first version always credited whatever
    # rung happened to be in focus, so an answer about who owns the budget was filed under "does the
    # problem exist".
    rung: str = ""
    # The SET of claims the user selected as context for one follow-up agent. `rung` (single) is still
    # accepted and folded in for back-compat; `rungs` is the multi-claim scope.
    rungs: list[str] = []


class ResearchStartIn(BaseModel):
    max_usd: float = 0.0
    idempotency_key: str = ""
    web: bool = True


class RunIn(BaseModel):
    run_id: str = ""


class ClaimPatch(BaseModel):
    claim: str = ""
    falsifier: str = ""


class QuestionEdit(BaseModel):
    text: str = ""
    target: str = ""


class QuestionAdd(BaseModel):
    inquiry_key: str = ""
    aspect_key: str = ""
    kind: str = "seek_support"
    text: str = ""
    target: str = ""
    polarity: int = 1


def project_research_cost(n_claims: int, *, web: bool, web_available: bool) -> dict:
    n = max(0, int(n_claims))
    components = {
        "refutation": round(n * 0.0015, 4),
        "relationship_judgment": round(n * 0.0015, 4),
        "web_ceiling": round(n * 2 * atk.WEB_USD_PER_QUERY, 4) if web and web_available else 0.0,
        "case_synthesis": float(arg.project_cost(n)["projected_usd"]),
    }
    return {"claims": n, "components": components,
            "projected_usd": round(sum(components.values()), 4)}


def build_router(pool_of, *, dsn: str = "", providers=None, manifest=None, judge_llm=None,
                 user_of=None, tenant: str = "") -> APIRouter:
    r = APIRouter()
    tenant = resolve_tenant(tenant)

    async def _owner(token: str) -> str:
        if not user_of:
            return ""
        u = await user_of(token)
        return (u or {}).get("id") or ""

    def _llm_json():
        return getattr(providers, "llm_json", None)

    def _ui():
        return getattr(manifest, "ui", None)

    def _policy():
        return getattr(manifest, "thesis_policy", None)

    async def _read(thesis_id: str, authorization: str, owner_token: str = "",
                    share_token: str = "", *, owner_only: bool = False) -> tuple[object, dict]:
        pool = await pool_of()
        d = await tstore.get(pool, thesis_id=thesis_id, owner_id=await _owner(authorization),
                             owner_token=owner_token, share_token=share_token)
        if not d:
            raise HTTPException(status_code=404, detail="no such thesis")
        if owner_only and not d.get("is_owner"):
            raise HTTPException(status_code=403, detail="owner access required")
        return pool, d

    @r.get("/thesis/labels")
    async def tl_labels():
        """The ladder ships to the client so the vocabulary is never hardcoded in the shell."""
        return labels()

    async def _decompose_claims(text: str) -> dict:
        """Thesis text -> {subject, claims (with critical/research_status stamped)}. Raises 503 on a
        degraded/failed decomposition. Shared by create-in-one-shot and genesis-confirm."""
        try:
            out = await dec.decompose(_llm_json(), text)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Thesis decomposition failed; retry.") from exc
        if out.get("degraded"):
            raise HTTPException(status_code=503, detail="Thesis decomposition failed; retry.")
        policy = _policy()
        for claim in out.get("claims") or []:
            claim["critical"] = bool(policy and policy.is_critical(claim["rung"]))
            claim["research_status"] = OPEN
        return out

    @r.post("/thesis")
    async def tl_new(body: NewThesis, authorization: str = Header(default="")):
        t = (body.thesis or "").strip()
        pool = await pool_of()
        oid = await _owner(authorization)
        # Draft: create a genesis row with the raw idea and converse to a thesis. No decompose, no cost.
        if body.draft:
            if len(t) < 3:
                raise HTTPException(status_code=400, detail="say a little about the idea")
            meta = await tstore.create(pool, thesis=t, claims=[], subject={},
                                       owner_id=oid, title=body.title or t)
            await tstore.set_proposed_thesis(pool, meta["id"], t)
            # The client drives the first genesis turn with this same text, which stores the user turn;
            # storing it here too would double it. The draft row + proposed_thesis are enough.
            return {"status": "draft", **meta,
                    "thesis": await tstore.get(pool, thesis_id=meta["id"], owner_id=oid,
                                               owner_token=meta.get("owner_token") or "")}
        if len(t) < 12:
            raise HTTPException(status_code=400, detail="give the thesis as a sentence")
        if body.project_only:
            return {"status": "projection", "projection": dec.project_cost()}
        projection = dec.project_cost()
        if float(projection["projected_usd"]) > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Approve the decomposition cost before creating this thesis."}
        out = await _decompose_claims(t)
        meta = await tstore.create(pool, thesis=t, claims=out["claims"], subject=out["subject"],
                                   owner_id=oid, title=body.title)
        await tstore.add_turn(pool, meta["id"], role="agent", move="asked",
                              text=_opening(out), payload={"subject": out["subject"]})
        return {"status": "ok", **meta,
                "thesis": await tstore.get(pool, thesis_id=meta["id"],
                                           owner_id=oid,
                                           owner_token=meta.get("owner_token") or "")}

    @r.post("/thesis/{thesis_id}/genesis")
    async def tl_genesis(thesis_id: str, body: GenesisIn, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """One genesis turn: sharpen the draft toward a concrete thesis. Draft-only (no claims yet)."""
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if d.get("claims"):
            raise HTTPException(status_code=409, detail="this thesis is already decomposed")
        said = (body.text or "").strip()
        if said:
            await tstore.add_turn(pool, thesis_id, role="user", text=said)
        turns = d.get("turns") or []
        used = sum(1 for t in turns if t.get("role") == "agent" and t.get("move") == "genesis")
        got = await gen.turn(_llm_json(), said=said, history=turns,
                             budget_left=max(0, gen.GENESIS_BUDGET - used))
        proposed = got.get("proposed_thesis") or d.get("proposed_thesis") or d.get("thesis") or ""
        await tstore.set_proposed_thesis(pool, thesis_id, proposed)
        reply = got.get("reply") or ("" if got.get("ready") else "Tell me a little more.")
        if reply or got.get("questions"):
            await tstore.add_turn(pool, thesis_id, role="agent", move="genesis", text=reply,
                                  payload={"questions": got.get("questions") or [],
                                           "proposed_thesis": proposed, "ready": bool(got.get("ready"))})
        return {"status": "ok", "reply": reply, "proposed_thesis": proposed,
                "questions": got.get("questions") or [], "ready": bool(got.get("ready")),
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    @r.post("/thesis/{thesis_id}/confirm")
    async def tl_confirm(thesis_id: str, body: ConfirmIn, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Commit the thesis the USER accepted, and decompose it into the ladder. The only commit."""
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        t = (body.thesis or d.get("proposed_thesis") or d.get("thesis") or "").strip()
        if len(t) < 12:
            raise HTTPException(status_code=400, detail="give the thesis as a sentence")
        if d.get("claims"):
            raise HTTPException(status_code=409, detail="this thesis is already decomposed")
        if body.project_only:
            return {"status": "projection", "projection": dec.project_cost()}
        projection = dec.project_cost()
        if float(projection["projected_usd"]) > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Approve the decomposition cost before building the claim ladder."}
        out = await _decompose_claims(t)
        await tstore.commit_claims(pool, thesis_id, thesis=t, claims=out["claims"],
                                   subject=out["subject"])
        await tstore.add_turn(pool, thesis_id, role="agent", move="asked",
                              text=_opening(out), payload={"subject": out["subject"]})
        return {"status": "ok",
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    @r.get("/thesis/{thesis_id}")
    async def tl_get(thesis_id: str, share: str = "", authorization: str = Header(default=""),
                     x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        _pool, d = await _read(thesis_id, authorization, x_thesis_owner, share)
        return {"status": "ok", "thesis": d}

    @r.get("/theses")
    async def tl_recent(limit: int = 40, authorization: str = Header(default="")):
        return {"theses": await tstore.recent(await pool_of(), owner_id=await _owner(authorization),
                                              limit=min(100, max(1, limit)))}

    @r.post("/thesis/{thesis_id}/share")
    async def tl_share(thesis_id: str, authorization: str = Header(default=""),
                       x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        return {"status": "ok", "share_token": await tstore.issue_share(pool, thesis_id)}

    @r.delete("/thesis/{thesis_id}/share")
    async def tl_unshare(thesis_id: str, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.revoke_share(pool, thesis_id)
        return {"status": "ok"}

    @r.post("/thesis/{thesis_id}/research/start")
    async def tl_research_start(thesis_id: str, body: ResearchStartIn,
                                authorization: str = Header(default=""),
                                x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        web_available = bool(body.web and atk._web_client(manifest))
        projection = project_research_cost(len(d.get("claims") or []), web=body.web,
                                           web_available=web_available)
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected research cost exceeds the approved maximum."}
        try:
            run = await tstore.create_run(
                pool, thesis_id=thesis_id, idempotency_key=body.idempotency_key,
                projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                metadata={"claims": len(d.get("claims") or []), "web": body.web,
                          "web_available": web_available, "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "approved", "projection": projection, "run": run}

    @r.post("/thesis/{thesis_id}/attack")
    async def tl_attack(thesis_id: str, body: AttackIn, authorization: str = Header(default=""),
                        x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Run the FOR search and the red-team AGAINST search over one rung or all of them.

        Corpus reads are free; the refuter is one small cross-family call per claim. The cap is the
        gate, as everywhere else in this app.
        """
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        run = await tstore.get_run(pool, thesis_id=thesis_id, run_id=body.run_id)
        if not run or run.get("state") not in ("approved", "running"):
            raise HTTPException(status_code=409, detail="an approved research run is required")
        todo = [c for c in d["claims"]
                if (not body.rung or c["rung"] == body.rung) and c["settleable"] != CALL_ONLY]
        web = atk._web_client(manifest) if body.web else None
        ctx = " ".join(str(v) for v in (d.get("subject") or {}).values())
        done = []
        for c in todo:
            res = await atk.attack_claim(dsn, claim=c["claim"], settleable=c["settleable"],
                                         judge_llm=judge_llm, ui=_ui(), extra_context=ctx,
                                         web_client=web, relation_llm=_llm_json(),
                                         evidence_policy=_policy(), tenant=tenant)
            for row in res["evidence"]:
                row["run_id"] = body.run_id
            await tstore.add_evidence(pool, thesis_id, c["rung"], res["evidence"])
            await tstore.set_verdict(pool, thesis_id, c["rung"], res["verdict"], res["note"],
                                     attacked=bool(res["attack_attempted"]))
            await tstore.advance_run(
                pool, thesis_id=thesis_id, run_id=body.run_id, stage=f"claim:{c['rung']}",
                actual_delta=round(0.003 + res.get("web_queries", 0) * atk.WEB_USD_PER_QUERY, 4))
            done.append({"rung": c["rung"], "verdict": res["verdict"], "counts": res["counts"],
                         "against_queries": res["against_queries"],
                         "web_queries": res.get("web_queries", 0)})
        # Primary research remains a blocker until independently corroborated.
        for c in d["claims"]:
            if c["settleable"] == CALL_ONLY and c["verdict"] == OPEN:
                await tstore.set_verdict(pool, thesis_id, c["rung"], "primary_research_needed",
                                         "This claim needs independent primary research.")
        if body.argue:
            await _write_cases(pool, thesis_id, d)
        return {"status": "ok", "attacked": done,
                "thesis": await tstore.get(pool, thesis_id=thesis_id,
                                           owner_id=await _owner(authorization),
                                           owner_token=x_thesis_owner)}

    async def _write_cases(pool, thesis_id: str, fresh: dict) -> bool:
        """Both cases per claim plus the integrated reading. One call for the whole thesis, after
        every claim has its evidence — ten separate calls cost ten times as much and argue each claim
        without knowing the others."""
        try:
            cases, overall = await arg.cases_for(_llm_json(), thesis=fresh["thesis"],
                                                 claims=fresh["claims"])
            await tstore.set_cases(pool, thesis_id, cases)
            if overall:
                await tstore.set_overall(pool, thesis_id, overall)
            return bool(cases or overall)
        except Exception:      # noqa: BLE001 — a table without written cases still shows its evidence
            return False

    @r.post("/thesis/{thesis_id}/argue")
    async def tl_argue(thesis_id: str, body: RunIn, authorization: str = Header(default=""),
                       x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Write the cases and the collective take over whatever evidence exists now."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        run = await tstore.get_run(pool, thesis_id=thesis_id, run_id=body.run_id)
        if not run or run.get("state") not in ("approved", "running"):
            raise HTTPException(status_code=409, detail="an approved research run is required")
        wrote = await _write_cases(pool, thesis_id, d)
        policy = _policy()
        decision = (policy.decide(d.get("claims") or []) if policy else
                    {"recommendation": "continue_diligence", "decisive_claims": [],
                     "reason": "No decision policy is configured."})
        await tstore.set_decision(pool, thesis_id, decision, research_status="completed")
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=body.run_id,
                                 stage="completed", state="completed",
                                 actual_delta=arg.project_cost(len(d.get("claims") or []))["projected_usd"])
        return {"status": "ok", "wrote": wrote,
                "synthesis_status": "completed" if wrote else "failed", "decision": decision,
                "thesis": await tstore.get(pool, thesis_id=thesis_id,
                                           owner_id=await _owner(authorization),
                                           owner_token=x_thesis_owner)}

    @r.post("/thesis/{thesis_id}/call")
    async def tl_call(thesis_id: str, body: CallIn, authorization: str = Header(default=""),
                      x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """What a named person told you, typed as evidence on the claim it bears on.

        `stated`, always — a first-hand account is strong evidence for exactly the rungs documents
        cannot reach, and it is never laundered into `filed`.
        """
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if body.rung not in SETTLEABLE:
            raise HTTPException(status_code=400, detail="unknown rung")
        if not (body.quote or "").strip():
            raise HTTPException(status_code=400, detail="nothing was said")
        who = (body.said_by or "an unnamed source").strip()
        await tstore.add_evidence(pool, thesis_id, body.rung, [{
            "side": "for" if body.supports else "against", "relation": "context",
            "register": STATED,
            "source_key": "call", "signal_only": False,
            "title": f"{who}" + (f" ({body.said_role})" if body.said_role else ""),
            "quote": body.quote.strip(), "source_url": "",
            "basis": "first-hand, on a call", "said_by": who, "said_role": body.said_role or "",
        }])
        cur = next((c for c in d["claims"] if c["rung"] == body.rung), None)
        if cur is not None:
            await tstore.set_verdict(
                pool, thesis_id, body.rung, "primary_research_needed",
                f"{who} provided one account; seek an independent account or corroboration.")
        await tstore.add_turn(pool, thesis_id, role="user", move="", rung=body.rung,
                              text=body.quote.strip()[:400])
        return {"status": "ok",
                "thesis": await tstore.get(pool, thesis_id=thesis_id,
                                           owner_id=await _owner(authorization),
                                           owner_token=x_thesis_owner)}

    @r.patch("/thesis/{thesis_id}/claim/{rung}")
    async def tl_claim(thesis_id: str, rung: str, body: ClaimPatch,
                       authorization: str = Header(default=""),
                       x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if rung not in SETTLEABLE:
            raise HTTPException(status_code=400, detail="unknown rung")
        claim = (body.claim or "").strip()
        if len(claim) < 8:
            raise HTTPException(status_code=400, detail="claim is too short")
        await tstore.revise_claim(pool, thesis_id, rung, claim)
        return {"status": "ok"}

    @r.post("/thesis/{thesis_id}/turn")
    async def tl_turn(thesis_id: str, body: TurnIn, authorization: str = Header(default=""),
                      x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """One follow-up exchange, scoped to the claim(s) the user selected. READ-ONLY: it explains the
        evidence and never re-grades a verdict, rewrites a case, or moves the recommendation — grading
        is done once, by the explicit Test step. (This replaced the old ledger-mutating conversation:
        testing is now explicit, so the conversation only reads.)
        """
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        said = (body.text or "").strip()

        # The selected context: the multi-select `rungs`, else the single `rung`, else the focus/weakest.
        want = [x for x in (list(body.rungs) + ([body.rung] if body.rung else [])) if x]
        by_rung = {c["rung"]: c for c in d.get("claims") or []}
        selected = [by_rung[x] for x in dict.fromkeys(want) if x in by_rung]
        if not selected:
            fc = _focus_claim(d)
            selected = [fc] if fc else []
        scope = [c["rung"] for c in selected]

        if said:
            await tstore.add_turn(pool, thesis_id, role="user", text=said, rungs=scope)
        got = await conv.follow_up(_llm_json(), thesis=d.get("thesis") or "", claims=selected,
                                   said=said, history=d.get("turns") or [])
        reply = got.get("reply") or "The evidence for the selected claims is shown above."
        await tstore.add_turn(pool, thesis_id, role="agent", move="explained", text=reply,
                              rung=scope[0] if scope else "", rungs=scope,
                              payload={"rungs": scope})
        return {"status": "ok", "move": {"move": "explained", "rungs": scope, "text": reply},
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    # ---- async research run: the whole test, server-side, no partial ----------------------------
    # The browser used to drive /attack claim by claim and paint each verdict as it landed. The owner
    # wants ONE explicit "Test this thesis" that runs everything to completion with no half-painted
    # brief. So the run executes here, in the background, over the ts_run state machine; the client
    # polls status and renders only when it is done. A deploy can kill this in-process task — the run
    # is therefore RESUMABLE at claim granularity (a claim already tested by this run is skipped) and
    # the client silently re-POSTs /research/run to resume, which idempotency makes invisible.
    STALE_SECONDS = 30

    async def _run_research(thesis_id: str, run_id: str):
        pool = await pool_of()
        try:
            d = await tstore.get(pool, thesis_id=thesis_id)
            if not d:
                return
            done_rungs = await tstore.claims_tested_by_run(pool, thesis_id, run_id)
            todo = [c for c in d["claims"]
                    if c["settleable"] != CALL_ONLY and c["rung"] not in done_rungs]
            run = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            web = atk._web_client(manifest) if (run or {}).get("metadata", {}).get("web") else None
            ctx = " ".join(str(v) for v in (d.get("subject") or {}).values())
            for c in todo:
                res = await atk.attack_claim(dsn, claim=c["claim"], settleable=c["settleable"],
                                             judge_llm=judge_llm, ui=_ui(), extra_context=ctx,
                                             web_client=web, relation_llm=_llm_json(),
                                             evidence_policy=_policy(), tenant=tenant)
                for row in res["evidence"]:
                    row["run_id"] = run_id
                await tstore.add_evidence(pool, thesis_id, c["rung"], res["evidence"])
                await tstore.set_verdict(pool, thesis_id, c["rung"], res["verdict"], res["note"],
                                         attacked=bool(res["attack_attempted"]), run_id=run_id)
                await tstore.advance_run(
                    pool, thesis_id=thesis_id, run_id=run_id, stage=f"claim:{c['rung']}",
                    actual_delta=round(0.003 + res.get("web_queries", 0) * atk.WEB_USD_PER_QUERY, 4))
            # Primary-research claims stay blockers until independently corroborated.
            for c in d["claims"]:
                if c["settleable"] == CALL_ONLY and c["verdict"] == OPEN:
                    await tstore.set_verdict(pool, thesis_id, c["rung"], "primary_research_needed",
                                             "This claim needs independent primary research.",
                                             run_id=run_id)
            fresh = await tstore.get(pool, thesis_id=thesis_id)
            await _write_cases(pool, thesis_id, fresh)
            policy = _policy()
            decision = (policy.decide(fresh.get("claims") or []) if policy else
                        {"recommendation": "continue_diligence", "decisive_claims": [],
                         "reason": "No decision policy is configured."})
            await tstore.set_decision(pool, thesis_id, decision, research_status="completed")
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed",
                                     actual_delta=arg.project_cost(len(fresh.get("claims") or []))
                                     ["projected_usd"])
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — a failed run must never corrupt state; it fails closed
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "research run failed", "detail": str(exc)[:300]})

    def _run_progress(d: dict, run_id: str) -> dict:
        claims = [c for c in d.get("claims") or [] if c["settleable"] != CALL_ONLY]
        done = sum(1 for c in claims if c.get("tested_run_id") == run_id)
        return {"done": done, "total": len(claims)}

    def _is_stale(run: dict) -> bool:
        if not run or run.get("state") != "running":
            return False
        ts = run.get("updated_at") or ""
        try:
            when = datetime.fromisoformat(str(ts))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - when).total_seconds() > STALE_SECONDS

    @r.post("/thesis/{thesis_id}/research/run")
    async def tl_research_run(thesis_id: str, body: RunIn, authorization: str = Header(default=""),
                              x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Kick off (or resume) the whole test in the background. Returns immediately; poll status."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        run = await tstore.get_run(pool, thesis_id=thesis_id, run_id=body.run_id)
        if not run:
            raise HTTPException(status_code=404, detail="no such run")
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        # Already actively progressing (fresh heartbeat) → don't start a second task.
        if run.get("state") == "running" and not _is_stale(run):
            return {"status": "running", "run": run}
        if run.get("state") not in ("approved", "running", "failed"):
            raise HTTPException(status_code=409, detail="run is not resumable")
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=body.run_id, stage="running",
                                 state="running")
        asyncio.create_task(_run_research(thesis_id, body.run_id))
        return {"status": "running",
                "run": await tstore.get_run(pool, thesis_id=thesis_id, run_id=body.run_id)}

    @r.get("/thesis/{thesis_id}/research/status")
    async def tl_research_status(thesis_id: str, run: str = "",
                                 authorization: str = Header(default=""),
                                 x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Derived progress for the active/named run. Marks a stalled run failed so a resume can take
        over — progress is read from real state (verdicts written), never a hand-managed flag."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner)
        run_id = run or ((d.get("claims") or [{}])[0] or {}).get("tested_run_id", "")
        record = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id) if run_id else None
        if record and _is_stale(record):
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="stalled",
                                  error={"reason": "run stalled (likely an API restart); resume"})
            record = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
        prog = _run_progress(d, run_id) if run_id else {"done": 0, "total": 0}
        return {"status": "ok", "run_id": run_id,
                "state": (record or {}).get("state", "none"),
                "stage": (record or {}).get("stage", ""),
                "error": (record or {}).get("error") or {},
                "actual_usd": (record or {}).get("actual_usd", 0.0), **prog}

    # ---- lines of inquiry: the decision-engine surface ------------------------------------------
    # Generate typed Socratic questions per aspect, let the user curate them, then run ONE line of
    # inquiry at a time against evidence. The kernel engine (eigen_kernel.decision) owns the mechanics;
    # the active vertical's DecisionProfile (manifest.decision_profile) supplies aspects + judgment.
    from eigen_kernel import decision as _dec
    from .engine_adapter import make_gather as _make_gather, make_synthesize as _make_synthesize

    def _profile():
        return getattr(manifest, "decision_profile", None)

    def _aspect_by_key(profile, key: str):
        return next((a for a in profile.aspects() if a.key == key), None)

    def _attack_fn(settleable: str, ctx: str, web: bool):
        async def go(target: str):
            wc = atk._web_client(manifest) if web else None
            return await atk.attack_claim(dsn, claim=target, settleable=settleable, judge_llm=judge_llm,
                                          ui=_ui(), extra_context=ctx, web_client=wc,
                                          relation_llm=_llm_json(), evidence_policy=_policy(), tenant=tenant)
        return go

    @r.get("/thesis/{thesis_id}/inquiries")
    async def tl_inquiries(thesis_id: str, authorization: str = Header(default=""),
                           x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """The lines of inquiry (from the profile) with their questions (from the store)."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner)
        profile = _profile()
        if profile is None:
            return {"status": "ok", "inquiries": []}
        qs = await tstore.list_questions(pool, thesis_id)
        by_inq: dict[str, list] = {}
        for q in qs:
            by_inq.setdefault(q["inquiry_key"], []).append(q)
        out = []
        for inq in profile.inquiries():
            iqs = by_inq.get(inq.key, [])
            # Per-aspect verdict is DERIVED (never a second decision path): resolve each answered
            # question to an aspect signal, aggregate via the profile.
            aspects = []
            for akey in inq.aspect_keys:
                aspect = _aspect_by_key(profile, akey)
                group = [q for q in iqs if q["aspect_key"] == akey]
                answered = [q for q in group if q.get("target_status")]
                if aspect is not None and answered:
                    statuses = [_dec.QuestionStatus(
                        _dec.Question(kind=_dec.QuestionKind(q["kind"]), text=q["text"],
                                      target=q["target"], polarity=int(q["polarity"])),
                        q["target_status"]) for q in answered]
                    verdict = _dec.aggregate_aspect(profile, statuses, critical=bool(aspect.critical))
                else:
                    verdict = "open"
                aspects.append({"key": akey, "prompt": getattr(aspect, "prompt", ""),
                                "critical": bool(getattr(aspect, "critical", False)), "verdict": verdict})
            out.append({"key": inq.key, "name": inq.name, "framing": inq.framing,
                        "aspects": aspects, "questions": iqs})
        return {"status": "ok", "inquiries": out}

    @r.get("/thesis/{thesis_id}/inquiry/status")
    async def tl_inquiry_status(thesis_id: str, run: str = "",
                                authorization: str = Header(default=""),
                                x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Poll a running line of inquiry. Progress is derived from questions actually answered by the
        run (real state), not a hand-managed flag; a stalled run is failed so it can be resumed."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner)
        record = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run) if run else None
        if record and _is_stale(record):
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run, stage="stalled",
                                  error={"reason": "run stalled (likely an API restart); resume"})
            record = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run)
        want = list((record or {}).get("metadata", {}).get("questions") or [])
        qs = await tstore.list_questions(pool, thesis_id)
        by_id = {q["id"]: q for q in qs}
        done = sum(1 for qid in want if by_id.get(qid, {}).get("run_id") == run and by_id[qid].get("target_status"))
        return {"status": "ok", "run_id": run, "state": (record or {}).get("state", "none"),
                "stage": (record or {}).get("stage", ""), "error": (record or {}).get("error") or {},
                "done": done, "total": len(want)}

    @r.post("/thesis/{thesis_id}/inquiries/generate")
    async def tl_generate(thesis_id: str, authorization: str = Header(default=""),
                          x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Generate a typed Socratic question set per aspect (unrun questions only are replaced)."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        profile = _profile()
        if profile is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        decision = d.get("thesis") or ""
        for inq in profile.inquiries():
            rows: list[dict] = []
            for key in inq.aspect_keys:
                aspect = _aspect_by_key(profile, key)
                if aspect is None:
                    continue
                questions = await _dec.generate_questions(
                    _llm_json(), aspect=aspect, decision=decision,
                    directive=profile.question_directive(aspect, decision))
                rows.extend({"aspect_key": key, "kind": q.kind.value, "text": q.text,
                             "target": q.target, "polarity": q.polarity} for q in questions)
            await tstore.set_questions(pool, thesis_id, inq.key, rows)
        return await tl_inquiries(thesis_id, authorization, x_thesis_owner)

    @r.patch("/thesis/{thesis_id}/question/{qid}")
    async def tl_edit_question(thesis_id: str, qid: str, body: QuestionEdit,
                               authorization: str = Header(default=""),
                               x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        nid = await tstore.edit_question(pool, thesis_id, qid, text=body.text or "", target=body.target or "")
        if not nid:
            raise HTTPException(status_code=404, detail="no such question")
        return {"status": "ok", "id": nid}

    @r.post("/thesis/{thesis_id}/question")
    async def tl_add_question(thesis_id: str, body: QuestionAdd,
                              authorization: str = Header(default=""),
                              x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if not (body.text or "").strip() or not (body.target or "").strip():
            raise HTTPException(status_code=400, detail="a question needs text and a target")
        qid = await tstore.add_question(pool, thesis_id, body.inquiry_key, body.aspect_key,
                                        kind=body.kind or "seek_support", text=body.text,
                                        target=body.target, polarity=body.polarity)
        return {"status": "ok", "id": qid}

    @r.delete("/thesis/{thesis_id}/question/{qid}")
    async def tl_remove_question(thesis_id: str, qid: str, authorization: str = Header(default=""),
                                 x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.remove_question(pool, thesis_id, qid)
        return {"status": "ok"}

    async def _run_inquiry(thesis_id: str, inquiry_key: str, run_id: str, web: bool):
        """Run one line of inquiry: for each aspect, gather evidence per question (shared across
        identical targets), qualify + aggregate via the profile, persist each answer + the run."""
        pool = await pool_of()
        try:
            profile = _profile()
            d = await tstore.get(pool, thesis_id=thesis_id)
            ctx = " ".join(str(v) for v in (d.get("subject") or {}).values())
            synth = _make_synthesize(_llm_json())
            qs = [q for q in await tstore.list_questions(pool, thesis_id, inquiry_key)]
            by_aspect: dict[str, list] = {}
            for q in qs:
                by_aspect.setdefault(q["aspect_key"], []).append(q)
            for akey, group in by_aspect.items():
                aspect = _aspect_by_key(profile, akey)
                if aspect is None:
                    continue
                gather = _make_gather(_attack_fn(aspect.settleable, ctx, web))
                for row in group:
                    q = _dec.Question(kind=_dec.QuestionKind(row["kind"]), text=row["text"],
                                      target=row["target"], polarity=int(row["polarity"]))
                    st = await _dec.run_question(gather, profile, q, synth)
                    await tstore.answer_question(pool, thesis_id, row["id"],
                                                 target_status=st.target_status, answer=st.answer,
                                                 evidence_ids=list(st.evidence_ids), run_id=run_id)
                await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id,
                                         stage=f"aspect:{akey}", actual_delta=0.01)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — a failed run fails closed, never corrupts
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "inquiry run failed", "detail": str(exc)[:300]})

    @r.post("/thesis/{thesis_id}/inquiry/{inquiry_key}/run")
    async def tl_run_inquiry(thesis_id: str, inquiry_key: str, body: ResearchStartIn,
                             authorization: str = Header(default=""),
                             x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Kick off ONE line of inquiry — cost projected + gated, serialized per thesis. Idempotency is
        the active question set, so re-running an unchanged inquiry is a no-op."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        qs = await tstore.list_questions(pool, thesis_id, inquiry_key)
        if not qs:
            raise HTTPException(status_code=409, detail="generate questions for this inquiry first")
        projection = project_research_cost(len(qs), web=body.web, web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected inquiry cost exceeds the approved maximum."}
        key = body.idempotency_key or tstore.active_question_hash(qs)
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"inquiry": inquiry_key, "questions": [q["id"] for q in qs],
                                                    "web": body.web, "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_inquiry(thesis_id, inquiry_key, run["id"], body.web))
        return {"status": "running", "run": run}

    return r


def _claim_by_rung(d: dict, rung: str) -> dict | None:
    r = (rung or "").strip()
    if not r:
        return None
    for c in d.get("claims") or []:
        if c["rung"] == r:
            return c
    return None


def _focus_claim(d: dict) -> dict | None:
    """The claim the conversation is ON. Falls back to whatever `next_move` would raise next, so a
    reply always has a subject even on the very first exchange."""
    claims = d.get("claims") or []
    if not claims:
        return None
    f = (d.get("focus_rung") or "").strip()
    for c in claims:
        if c["rung"] == f:
            return c
    m = next_move(d)
    if m.get("rung"):
        for c in claims:
            if c["rung"] == m["rung"]:
                return c
    return claims[0]


async def _apply_effect(pool, thesis_id: str, claim: dict, got: dict, said: str) -> None:
    """Persist author input without allowing one account to settle an evidence claim."""
    eff = got.get("effect") or "none"
    rung = claim["rung"]
    if eff == "revise" and got.get("revised_claim"):
        # Their wording wins. It is their thesis.
        await tstore.revise_claim(pool, thesis_id, rung, got["revised_claim"])
        return
    if eff in ("answered", "contradicted"):
        # What they know is STATED evidence from them, attributed. It is never laundered into filed,
        # and it is never silently merged with what the record says.
        await tstore.add_evidence(pool, thesis_id, rung, [{
            "side": "for" if eff == "answered" else "against", "relation": "context",
            "register": STATED,
            "source_key": "call", "signal_only": False, "title": "the author, in conversation",
            "quote": said[:1200], "source_url": "", "basis": "said by the author, not a source",
            "said_by": "the author", "said_role": "author"}])
        await tstore.set_verdict(
            pool, thesis_id, rung, "primary_research_needed",
            "The author provided one account; seek an independent account or corroboration.")
        return


def _payload_for(claim: dict, got: dict) -> dict:
    """What the reply needs to SHOW beside it: the evidence it is arguing from, and — when the move
    is needs_person — who and what to ask."""
    ev = claim.get("evidence") or []
    if got["move"] == "needs_person":
        return {"ask": list(ASK_WHO.get(claim["rung"], ())),
                "question": _question_for(claim["rung"], claim,
                                          [e for e in ev if e["side"] == "against"],
                                          [e for e in ev if e["side"] == "for"]),
                "people": ppl.from_evidence(ev)}
    shown = [e for e in ev if not e.get("signal_only")][:3]
    return {"evidence": shown} if shown else {}


# ---- the agent's move ---------------------------------------------------------------------------

# Weakest first. A stress test opens on the claim most likely to be false, not the one most likely to
# please: the record arguing against you, then the claim nobody could attack, then the ones only a
# person can settle, and only then what is merely unexamined.
_ORDER = ("contradicted", "under_tested", "unsettleable", "open", "supported")


def next_move(d: dict) -> dict:
    """Pick the claim worth talking about, and say which of the three moves this is.

    Never asks the reader something the record could answer — that is the rule that keeps this from
    becoming a chatbot with twenty questions.
    """
    claims = d.get("claims") or []
    unattacked = [c for c in claims
                  if c["settleable"] != CALL_ONLY and not c.get("attacked")]
    if unattacked:
        return {"move": "attacked", "rung": "", "text":
                f"I have {len(claims)} claims this thesis rests on and I have not tested "
                f"{len(unattacked)} of them yet. Let me go and try to break them.",
                "payload": {"action": "attack"}}

    ranked = sorted(claims, key=lambda c: (_ORDER.index(c["verdict"])
                                           if c["verdict"] in _ORDER else 99))
    for c in ranked:
        v, rung = c["verdict"], c["rung"]
        ev = c.get("evidence") or []
        against = [e for e in ev if e["side"] == "against" and not e["signal_only"]]
        forr = [e for e in ev if e["side"] == "for" and not e["signal_only"]]

        if v == "contradicted" and against:
            return {"move": "attacked", "rung": rung, "text":
                    f"The weakest link is “{c['claim']}”. The record argues against it: "
                    f"{_cite(against[0])}. Your thesis has to survive that — what am I missing?",
                    "payload": {"evidence": against[:3]}}
        if v == "under_tested":
            return {"move": "attacked", "rung": rung, "text":
                    f"“{c['claim']}” is under-tested. I searched for support and ran a red-team "
                    f"search for counter-evidence, and neither found anything congruent. That is "
                    f"not the same as it being true — nobody has written this down either way.",
                    "payload": {}}
        if v == "unsettleable" and not any(e["source_key"] == "call" for e in ev):
            who = ", ".join(ROLE_LABEL[r] for r in ASK_WHO.get(rung, ()) if r in ROLE_LABEL)
            return {"move": "needs_person", "rung": rung, "text":
                    f"“{c['claim']}” cannot be settled from any document — {QUESTION[rung]} "
                    f"You need {who or 'a person who has lived it'}. Here is what to ask.",
                    "payload": {"ask": list(ASK_WHO.get(rung, ())),
                                "question": _question_for(rung, c, against, forr),
                                "people": ppl.from_evidence(ev),
                                "guidance": ppl.buyer_guidance(
                                    c["claim"], (d.get("subject") or {}).get("segment", ""))}}
        if v == "supported" and forr:
            return {"move": "settled", "rung": rung, "text":
                    f"“{c['claim']}” holds up: {_cite(forr[0])}. Note the attack found nothing "
                    f"against it, which is weaker than it sounds — it may just be unwritten.",
                    "payload": {"evidence": forr[:3]}}

    return {"move": "settled", "rung": "", "text":
            "Every claim has been tested as far as the record goes. What is left needs people — "
            "run the calls and paste back what they say.", "payload": {}}


def _cite(e: dict) -> str:
    t = (e.get("title") or e.get("source_key") or "a source").strip()[:80]
    q = (e.get("quote") or "").strip().replace("\n", " ")[:160]
    return f"“{q}” — {t} [{e.get('register', 'stated')}]"


def _question_for(rung: str, claim: dict, against: list, forr: list) -> str:
    """A question carrying the evidence that motivates it. A question with nothing behind it is a
    generic customer-discovery prompt, and this mode does not generate those."""
    base = {
        "willingness_to_pay": "What do you currently spend on this, and what would have to be true "
                              "for you to move that budget?",
        "switching_feasible": "If something better existed, what would actually stop you switching "
                              "— contracts, integrations, or whose neck is on the line?",
        "budget_category": "Which budget line would this come out of today, and who owns it?",
        "buyer_nameable": "Who signs for this in your organisation, and who has to agree first?",
        "catalyst": "What changed recently that made this worth revisiting at all?",
    }.get(rung, f"{QUESTION[rung]} What have you seen?")
    if against:
        return base + f" (Ask because the record says: “{(against[0].get('quote') or '')[:120]}”.)"
    if forr:
        return base + f" (Ask because the record says: “{(forr[0].get('quote') or '')[:120]}”.)"
    return base


def _opening(out: dict) -> str:
    s = out.get("subject") or {}
    bits = [v for v in (s.get("product"), s.get("segment")) if v]
    head = " for ".join(bits) if bits else "this thesis"
    call_only = [k for k, v in SETTLEABLE.items() if v == CALL_ONLY]
    return (f"I read this as {head}. It rests on {len(out.get('claims') or [])} claims that could "
            f"each be false. {len(call_only)} of them — willingness to pay and switching cost — no "
            f"document can settle, so those are calls from the start. Let me try to break the rest.")
