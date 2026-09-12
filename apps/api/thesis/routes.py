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

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import argue as arg
from . import attack as atk
from . import converse as conv
from . import decompose as dec
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


class ResearchStartIn(BaseModel):
    max_usd: float = 0.0
    idempotency_key: str = ""
    web: bool = True


class RunIn(BaseModel):
    run_id: str = ""


class ClaimPatch(BaseModel):
    claim: str = ""
    falsifier: str = ""


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

    @r.post("/thesis")
    async def tl_new(body: NewThesis, authorization: str = Header(default="")):
        t = (body.thesis or "").strip()
        if len(t) < 12:
            raise HTTPException(status_code=400, detail="give the thesis as a sentence")
        if body.project_only:
            return {"status": "projection", "projection": dec.project_cost()}
        projection = dec.project_cost()
        if float(projection["projected_usd"]) > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Approve the decomposition cost before creating this thesis."}
        try:
            out = await dec.decompose(_llm_json(), t)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Thesis decomposition failed; retry.") from exc
        if out.get("degraded"):
            raise HTTPException(status_code=503, detail="Thesis decomposition failed; retry.")
        policy = _policy()
        for claim in out.get("claims") or []:
            claim["critical"] = bool(policy and policy.is_critical(claim["rung"]))
            claim["research_status"] = OPEN
        pool = await pool_of()
        oid = await _owner(authorization)
        meta = await tstore.create(pool, thesis=t, claims=out["claims"], subject=out["subject"],
                                   owner_id=oid, title=body.title)
        await tstore.add_turn(pool, meta["id"], role="agent", move="asked",
                              text=_opening(out), payload={"subject": out["subject"]})
        return {"status": "ok", **meta,
                "thesis": await tstore.get(pool, thesis_id=meta["id"],
                                           owner_id=oid,
                                           owner_token=meta.get("owner_token") or "")}

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
        """One exchange. Always closes as exactly one of settled / attacked / needs_person.

        When the author has said something, the agent REPLIES TO IT — and their answer is allowed to
        change the ledger. The first version stored what they typed and never read it, which made
        every turn a monologue on a timer: you push back with ten years of industry knowledge and get
        the agent's pre-computed opinion about a different claim.
        """
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        said = (body.text or "").strip()

        if said:
            await tstore.add_turn(pool, thesis_id, role="user", text=said)
            # A question asked ON A ROW is about that row.
            focus = _claim_by_rung(d, body.rung) or _focus_claim(d)
            got = await conv.reply(_llm_json(), thesis=d["thesis"], claim=focus or {},
                                   said=said, history=d.get("turns") or [])
            if got and focus:
                await _apply_effect(pool, thesis_id, focus, got, said)
                nxt = got.get("next_rung") or ""
                await tstore.set_focus(pool, thesis_id,
                                       nxt if nxt in SETTLEABLE else focus["rung"])
                await tstore.add_turn(pool, thesis_id, role="agent", move=got["move"],
                                      rung=focus["rung"], text=got["reply"],
                                      payload=_payload_for(focus, got))
                return {"status": "ok", "move": {"move": got["move"], "rung": focus["rung"],
                                                 "text": got["reply"]},
                        "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                                   owner_token=x_thesis_owner)}
            # No model, or it gave us nothing usable. Advance — but SAY that we could not read the
            # answer rather than replying with a confident non-sequitur.
            d = await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                 owner_token=x_thesis_owner)
            move = next_move(d)
            move["text"] = ("I could not read that answer just now, so I am carrying on from the "
                            "ledger. " + move["text"])
            await tstore.add_turn(pool, thesis_id, role="agent", move=move["move"],
                                  rung=move["rung"], text=move["text"],
                                  payload=move.get("payload") or {})
            return {"status": "ok", "move": move,
                    "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                               owner_token=x_thesis_owner)}

        move = next_move(d)
        if move.get("rung"):
            await tstore.set_focus(pool, thesis_id, move["rung"])
        await tstore.add_turn(pool, thesis_id, role="agent", move=move["move"],
                              rung=move["rung"], text=move["text"], payload=move.get("payload") or {})
        return {"status": "ok", "move": move,
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

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
