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


class NewThesis(BaseModel):
    thesis: str = ""
    title: str = ""
    project_only: bool = False


class AttackIn(BaseModel):
    rung: str = ""            # one rung, or blank for every rung the record could speak to
    max_usd: float = 0.10


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


def build_router(pool_of, *, dsn: str = "", providers=None, manifest=None, judge_llm=None,
                 user_of=None) -> APIRouter:
    r = APIRouter()

    async def _owner(token: str) -> str:
        if not user_of:
            return ""
        u = await user_of(token)
        return (u or {}).get("id") or ""

    def _llm_json():
        return getattr(providers, "llm_json", None)

    def _ui():
        return getattr(manifest, "ui", None)

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
        out = await dec.decompose(_llm_json(), t)
        pool = await pool_of()
        meta = await tstore.create(pool, thesis=t, claims=out["claims"], subject=out["subject"],
                                   owner_id=await _owner(authorization), title=body.title)
        await tstore.add_turn(pool, meta["id"], role="agent", move="asked",
                              text=_opening(out), payload={"subject": out["subject"]})
        return {"status": "ok", **meta,
                "thesis": await tstore.get(pool, thesis_id=meta["id"],
                                           owner_id=await _owner(authorization))}

    @r.get("/thesis/{thesis_id}")
    async def tl_get(thesis_id: str, authorization: str = Header(default="")):
        d = await tstore.get(await pool_of(), thesis_id=thesis_id,
                             owner_id=await _owner(authorization))
        if not d:
            raise HTTPException(status_code=404, detail="no such thesis")
        return {"status": "ok", "thesis": d}

    @r.get("/theses")
    async def tl_recent(limit: int = 40, authorization: str = Header(default="")):
        return {"theses": await tstore.recent(await pool_of(), owner_id=await _owner(authorization),
                                              limit=min(100, max(1, limit)))}

    @r.post("/thesis/{thesis_id}/attack")
    async def tl_attack(thesis_id: str, body: AttackIn, authorization: str = Header(default="")):
        """Run the FOR search and the red-team AGAINST search over one rung or all of them.

        Corpus reads are free; the refuter is one small cross-family call per claim. The cap is the
        gate, as everywhere else in this app.
        """
        pool = await pool_of()
        d = await tstore.get(pool, thesis_id=thesis_id, owner_id=await _owner(authorization))
        if not d:
            raise HTTPException(status_code=404, detail="no such thesis")
        todo = [c for c in d["claims"]
                if (not body.rung or c["rung"] == body.rung) and c["settleable"] != CALL_ONLY]
        projected = round(0.0015 * len(todo), 4)
        if projected > body.max_usd:
            return {"status": "refused", "projection": {"claims": len(todo),
                                                        "projected_usd": projected},
                    "reason": f"attacking {len(todo)} claims projects ${projected:.3f}, "
                              f"over the ${body.max_usd:.2f} cap"}
        ctx = " ".join(str(v) for v in (d.get("subject") or {}).values())
        done = []
        for c in todo:
            res = await atk.attack_claim(dsn, claim=c["claim"], settleable=c["settleable"],
                                         judge_llm=judge_llm, ui=_ui(), extra_context=ctx)
            await tstore.add_evidence(pool, thesis_id, c["rung"], res["evidence"])
            await tstore.set_verdict(pool, thesis_id, c["rung"], res["verdict"], res["note"],
                                     attacked=True)
            done.append({"rung": c["rung"], "verdict": res["verdict"], "counts": res["counts"],
                         "against_queries": res["against_queries"]})
        # Every call-only rung is stamped once, so the ledger never shows them as merely unexamined.
        for c in d["claims"]:
            if c["settleable"] == CALL_ONLY and c["verdict"] == OPEN:
                await tstore.set_verdict(pool, thesis_id, c["rung"], UNSETTLEABLE,
                                         "No document can settle this. It needs a person.")
        # Now WRITE BOTH CASES. One call for the whole thesis, after every claim has its evidence —
        # ten separate calls cost ten times as much and argue each claim without knowing the others.
        fresh = await tstore.get(pool, thesis_id=thesis_id, owner_id=await _owner(authorization))
        try:
            cases = await arg.cases_for(_llm_json(), thesis=fresh["thesis"],
                                        claims=fresh["claims"])
            await tstore.set_cases(pool, thesis_id, cases)
        except Exception:      # noqa: BLE001 — a table without written cases still shows its evidence
            pass
        return {"status": "ok", "attacked": done,
                "thesis": await tstore.get(pool, thesis_id=thesis_id,
                                           owner_id=await _owner(authorization))}

    @r.post("/thesis/{thesis_id}/call")
    async def tl_call(thesis_id: str, body: CallIn, authorization: str = Header(default="")):
        """What a named person told you, typed as evidence on the claim it bears on.

        `stated`, always — a first-hand account is strong evidence for exactly the rungs documents
        cannot reach, and it is never laundered into `filed`.
        """
        pool = await pool_of()
        d = await tstore.get(pool, thesis_id=thesis_id, owner_id=await _owner(authorization))
        if not d:
            raise HTTPException(status_code=404, detail="no such thesis")
        if body.rung not in SETTLEABLE:
            raise HTTPException(status_code=400, detail="unknown rung")
        if not (body.quote or "").strip():
            raise HTTPException(status_code=400, detail="nothing was said")
        who = (body.said_by or "an unnamed source").strip()
        await tstore.add_evidence(pool, thesis_id, body.rung, [{
            "side": "for" if body.supports else "against", "register": STATED,
            "source_key": "call", "signal_only": False,
            "title": f"{who}" + (f" ({body.said_role})" if body.said_role else ""),
            "quote": body.quote.strip(), "source_url": "",
            "basis": "first-hand, on a call", "said_by": who, "said_role": body.said_role or "",
        }])
        cur = next((c for c in d["claims"] if c["rung"] == body.rung), None)
        # A call is the ONLY thing that can move a call-only rung off unsettleable.
        if cur is not None:
            v = "supported" if body.supports else "contradicted"
            await tstore.set_verdict(pool, thesis_id, body.rung, v,
                                     f"{who} said so on a call — one account, not a filing.")
        await tstore.add_turn(pool, thesis_id, role="user", move="", rung=body.rung,
                              text=body.quote.strip()[:400])
        return {"status": "ok",
                "thesis": await tstore.get(pool, thesis_id=thesis_id,
                                           owner_id=await _owner(authorization))}

    @r.post("/thesis/{thesis_id}/turn")
    async def tl_turn(thesis_id: str, body: TurnIn, authorization: str = Header(default="")):
        """One exchange. Always closes as exactly one of settled / attacked / needs_person.

        When the author has said something, the agent REPLIES TO IT — and their answer is allowed to
        change the ledger. The first version stored what they typed and never read it, which made
        every turn a monologue on a timer: you push back with ten years of industry knowledge and get
        the agent's pre-computed opinion about a different claim.
        """
        oid = await _owner(authorization)
        pool = await pool_of()
        d = await tstore.get(pool, thesis_id=thesis_id, owner_id=oid)
        if not d:
            raise HTTPException(status_code=404, detail="no such thesis")
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
                        "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid)}
            # No model, or it gave us nothing usable. Advance — but SAY that we could not read the
            # answer rather than replying with a confident non-sequitur.
            d = await tstore.get(pool, thesis_id=thesis_id, owner_id=oid)
            move = next_move(d)
            move["text"] = ("I could not read that answer just now, so I am carrying on from the "
                            "ledger. " + move["text"])
            await tstore.add_turn(pool, thesis_id, role="agent", move=move["move"],
                                  rung=move["rung"], text=move["text"],
                                  payload=move.get("payload") or {})
            return {"status": "ok", "move": move,
                    "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid)}

        move = next_move(d)
        if move.get("rung"):
            await tstore.set_focus(pool, thesis_id, move["rung"])
        await tstore.add_turn(pool, thesis_id, role="agent", move=move["move"],
                              rung=move["rung"], text=move["text"], payload=move.get("payload") or {})
        return {"status": "ok", "move": move,
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid)}

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
    """What the author's answer DID to the claim. Without this the conversation is theatre — you can
    settle a rung out of your own experience and the ledger will still say `open`."""
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
            "side": "for" if eff == "answered" else "against", "register": STATED,
            "source_key": "call", "signal_only": False, "title": "the author, in conversation",
            "quote": said[:1200], "source_url": "", "basis": "said by the author, not a source",
            "said_by": "the author", "said_role": "author"}])
        await tstore.set_verdict(
            pool, thesis_id, rung,
            "supported" if eff == "answered" else "contradicted",
            "The author answered this from their own knowledge — one account, not a source.")
        return
    if eff == "irrelevant":
        await tstore.set_verdict(pool, thesis_id, rung, SET_ASIDE,
                                 "The author says this rung does not apply to their thesis.")


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
