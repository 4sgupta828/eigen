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
import hashlib
import logging
import os
import time

log = logging.getLogger("eigen.thesis")
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import argue as arg
from . import attack as atk
from . import board as tboard
from . import brainstorm as bstorm
from . import competitive as compres
from . import converse as conv
from . import decompose as dec
from . import genesis as gen
from . import people as ppl
from . import prioritize as prio
from . import settings as tsettings
from . import store as tstore
from . import synth as syn
from . import transcript as tx
from . import voices as tvoices
from .schema import (
    ASK_WHO, BUYER, CALL_ONLY, OPEN, QUESTION, ROLE_LABEL, SET_ASIDE, SETTLEABLE, STATED, UNSETTLEABLE,
    VERDICT_LABEL, labels,
)


def thesis_enabled() -> bool:
    return os.environ.get("EIGEN_THESIS", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_tenant(value: str = "") -> str:
    return (value or os.environ.get("EIGEN_TENANT_ID") or "demo").strip()


class ThesisAttachment(BaseModel):
    data: str = ""            # base64-encoded file bytes (or base64 UTF-8 for a pasted document)
    media_type: str = ""      # e.g. application/pdf, text/plain
    name: str = ""


class NewThesis(BaseModel):
    thesis: str = ""
    title: str = ""
    project_only: bool = False
    max_usd: float = 0.0
    draft: bool = False       # create a genesis draft (no decompose, no cost) and converse to a thesis
    attachments: list[ThesisAttachment] = []   # intake reference material (pasted docs / uploaded PDFs)


class GenesisIn(BaseModel):
    text: str = ""            # the author's latest message in the genesis conversation
    attachments: list[ThesisAttachment] = []   # more reference material added mid-conversation


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


class BrainstormMsgIn(BaseModel):
    text: str = ""                 # the user's message for this brainstorm turn


class BrainstormExpandIn(BaseModel):
    leg: str = ""                  # experts | references | media | deepdive
    query: str = ""                # the focused query to run for this direction


class BrainstormThreadIn(BaseModel):
    title: str = ""


class VoicesOrganizeIn(BaseModel):
    moments: list[dict] = []       # compact candidates from /voices/search: {id, kind, title, snippet, speaker, show}
    refresh: bool = False


class ResearchStartIn(BaseModel):
    max_usd: float = 0.0
    idempotency_key: str = ""
    web: bool = True
    level: int = 0             # critical-subset run: 0 = P0 only, 1 = P0+P1, 2 = P0+P1+P2 … (priority level)


class RunIn(BaseModel):
    run_id: str = ""


class ClaimPatch(BaseModel):
    claim: str = ""
    falsifier: str = ""


class QuestionEdit(BaseModel):
    text: str = ""
    target: str = ""


class SettingIn(BaseModel):
    key: str = ""
    value: str = ""                  # "" clears the override → falls back to the env/default


class ThesisIdIn(BaseModel):
    thesis_id: str = ""
    to_account: bool = False         # claim to the signed-in account (owner_id) vs mint a device token


class EditThesisIn(BaseModel):
    text: str = ""                   # the author's directly-edited thesis wording


class ImproveIn(BaseModel):
    instruction: str = ""            # optional: "narrow to X" — steers a directed pass (legacy/back-compat)
    action: str = "propose"          # propose | accept | reject — the deficiency-driven sharpening flow
    pillar: str = ""                 # the pillar being accepted or rejected
    proposed_thesis: str = ""        # the accepted rewrite to apply


class RevertIn(BaseModel):
    version_id: str = ""       # the thesis version to backtrack to


class CompetitiveAddIn(BaseModel):
    names: list[str] = []      # the candidate competitors the user chose to analyze + add
    max_usd: float = 0.0
    idempotency_key: str = ""


class ExpertDiscoverIn(BaseModel):
    aspect_key: str = ""       # thesis-scoped: discover experts for ONE call_only aspect, not a directory


class TranscriptIn(BaseModel):
    aspect_key: str = ""
    said_by: str = ""
    said_role: str = ""        # buyer | operator | advisor
    firm: str = ""             # the account: independence is per person AND firm
    transcript: str = ""


class SaveExpertIn(BaseModel):
    name: str = ""
    url: str = ""              # public profile — never a guessed one
    firm: str = ""
    role: str = ""
    headline: str = ""
    source: str = "manual"     # exa | pdl | manual


class InquiryTranscriptIn(BaseModel):
    expert_name: str = ""
    expert_url: str = ""       # public profile of who you spoke with
    firm: str = ""
    role: str = ""
    transcript: str = ""
    save_to_roster: bool = True   # also add this person to the cross-thesis expert map


class PeopleSearchIn(BaseModel):
    query: str = ""            # freeform expertise query (Exa's semantic leg)
    max_results: int = 10
    # structured filters (PDL's precision leg): title, seniority, company, past_company, skills, location
    filters: dict | None = None


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


def project_competitive_cost(max_players: int, *, web_available: bool) -> dict:
    """Cost of researching the competitive landscape: one player-identification pull + one profiling pull
    per player, each an open-web search + an extraction call. Bounded by max_players."""
    calls = 1 + max(1, int(max_players))                       # identify + one per player
    web = round(calls * atk.WEB_USD_PER_QUERY, 4) if web_available else 0.0
    llm = round(calls * 0.003, 4)                              # one extraction call each
    return {"players": max_players, "components": {"web_search": web, "extraction": llm},
            "projected_usd": round(web + llm, 4)}


def build_router(pool_of, *, dsn: str = "", providers=None, manifest=None, judge_llm=None,
                 user_of=None, tenant: str = "", startup_search=None) -> APIRouter:
    # `startup_search(text, limit) -> [{name, note}]`: our internal Startup Search (hybrid company index),
    # injected when available so competitive discovery sources direct competitors from our own corpus.
    r = APIRouter()
    tenant = resolve_tenant(tenant)
    _VOICES_CACHE_V = 2      # bump to invalidate stored voices-organize caches when the logic changes

    async def _owner(token: str) -> str:
        if not user_of:
            return ""
        u = await user_of(token)
        return (u or {}).get("id") or ""

    def _llm_json():
        # Wrapped so a failure of the default (DeepSeek) seam records its cause too — the OpenAI seams
        # record natively — so any run whose artifact comes back empty can surface WHY, not fail silent.
        from .llm import recording
        return recording(getattr(providers, "llm_json", None))

    def _llm_reason() -> str:
        """The last LLM/provider error in this run's task (out of credits, rate-limited, …), or ''."""
        try:
            from .llm import LAST_LLM_ERROR
            return LAST_LLM_ERROR.get() or ""
        except Exception:      # noqa: BLE001
            return ""

    def _reset_llm_error():
        try:
            from .llm import LAST_LLM_ERROR
            LAST_LLM_ERROR.set("")
        except Exception:      # noqa: BLE001
            pass

    def _strong_llm_json():
        # The stronger (OpenAI) model for the quality-critical steps — synthesizing the answer and
        # reformulating search queries — where the eval showed us weak. Falls back to the default seam.
        try:
            from .llm import strong_json
            return strong_json() or _llm_json()
        except Exception:      # noqa: BLE001
            return _llm_json()

    def _openai_only_llm_json():
        # OpenAI-ONLY seam (no DeepSeek fallback). The sample-thesis generator must run on the strong
        # (OpenAI) model to be genuinely non-obvious; if OpenAI is unconfigured we return None so the
        # caller yields "" and the endpoint answers 502, rather than quietly using the weaker default.
        # Model is configurable via EIGEN_THESIS_STRONG_MODEL (default gpt-4o) inside strong_json().
        try:
            from .llm import strong_json
            return strong_json()
        except Exception:      # noqa: BLE001
            return None

    def _extract_attachments(atts) -> list[dict]:
        """Text-extract intake attachments (pasted documents + uploaded PDFs) via the shared media
        pipeline → [{name, media_type, chars, text}]. Images are ignored for a thesis. Never raises."""
        rows = [(a.model_dump() if hasattr(a, "model_dump") else dict(a)) for a in (atts or []) if a]
        if not rows:
            return []
        try:
            from api.media import attachments_to_media
            _imgs, docs, pdfs, _notes = attachments_to_media(rows)
        except Exception:      # noqa: BLE001 — a bad attachment never blocks intake
            return []
        out: list[dict] = []
        for d in docs:
            t = (d.get("text") or "").strip()
            if t:
                out.append({"name": d.get("name") or "document", "media_type": "text",
                            "chars": len(t), "text": t[:12000]})
        for p in pdfs:
            t = (p.get("text_fallback") or "").strip()
            if t:
                out.append({"name": p.get("name") or "document.pdf", "media_type": "pdf",
                            "chars": len(t), "text": t[:12000]})
        return out[:6]

    def _attach_context(stored: list[dict], *, cap: int = 8000) -> str:
        """Render stored attachments as reference-material context for the genesis / sharpen prompts."""
        parts = [f"— {a.get('name') or 'document'} —\n{(a.get('text') or '').strip()}"
                 for a in (stored or []) if (a.get("text") or "").strip()]
        return ("\n\n".join(parts))[:cap].strip()

    def _ui():
        return getattr(manifest, "ui", None)

    def _policy():
        return getattr(manifest, "thesis_policy", None)

    async def _read(thesis_id: str, authorization: str, owner_token: str = "",
                    share_token: str = "", *, owner_only: bool = False) -> tuple[object, dict]:
        pool = await pool_of()
        await tsettings.ensure_fresh(pool)   # keep the runtime settings cache warm for any run this kicks off
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

    # ---- admin settings: runtime toggles (e.g. the reasoning provider), gated by the admin token ----
    def _admin_ok(token: str) -> bool:
        want = os.environ.get("EIGEN_ADMIN_TOKEN", "")
        return bool(want) and token == want

    @r.get("/thesis/admin/settings")
    async def tl_admin_settings(x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        """The runtime settings + their allowed values, for the admin Settings UI. Admin-token gated."""
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        pool = await pool_of()
        return {"status": "ok", "settings": await tsettings.effective(pool)}

    @r.post("/thesis/admin/settings")
    async def tl_admin_set_setting(body: SettingIn, x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        """Set (or clear, with an empty value) one runtime setting. Takes effect within seconds across
        workers — no redeploy. Admin-token gated."""
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        pool = await pool_of()
        try:
            value = await tsettings.set_value(pool, body.key, body.value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "key": body.key, "value": value,
                "settings": await tsettings.effective(pool)}

    # ---- admin recovery: list EVERY thesis, re-adopt one onto this device, or delete it. There is no
    # account model yet — a thesis is owned by whoever holds its capability token (in localStorage). If
    # that token is lost (another browser/device, cleared storage), the thesis vanishes from "My theses"
    # even though it still exists (and may be on the board). These admin-gated tools recover it.
    @r.get("/thesis/admin/theses")
    async def tl_admin_all(limit: int = 200, x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        return {"status": "ok", "theses": await tstore.all_theses(await pool_of(), limit=min(500, max(1, limit)))}

    @r.post("/thesis/admin/adopt")
    async def tl_admin_adopt(body: ThesisIdIn, authorization: str = Header(default=""),
                             x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        """Recover a thesis for the operator. `to_account`: bind it to the signed-in account (owner_id)
        so it shows in that account's "My theses" on any device. Otherwise mint a fresh device
        capability token (returned once, never stored in the clear) for this browser only."""
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        tid = (body.thesis_id or "").strip()
        pool = await pool_of()
        if body.to_account:
            account = await _owner(authorization)
            if not account:
                raise HTTPException(status_code=400, detail="sign in first — no account to claim to")
            if not await tstore.claim_thesis_to_account(pool, tid, account):
                raise HTTPException(status_code=404, detail="no such thesis")
            return {"status": "ok", "thesis_id": tid, "account": True}
        token = await tstore.adopt_thesis(pool, tid)
        if not token:
            raise HTTPException(status_code=404, detail="no such thesis")
        return {"status": "ok", "thesis_id": tid, "owner_token": token}

    @r.post("/thesis/admin/delete")
    async def tl_admin_delete(body: ThesisIdIn, x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        ok = await tstore.delete_thesis(await pool_of(), (body.thesis_id or "").strip())
        if not ok:
            raise HTTPException(status_code=404, detail="no such thesis")
        return {"status": "ok"}

    @r.post("/thesis/admin/unpublish")
    async def tl_admin_unpublish(body: ThesisIdIn, x_admin_token: str = Header(default="", alias="X-Admin-Token")):
        """Remove a thesis's snapshot from the public ThesisBoard (moderation) — the thesis itself is
        kept. Admin-token gated. Idempotent: unpublishing an already-private thesis is a no-op."""
        if not _admin_ok(x_admin_token):
            raise HTTPException(status_code=403, detail="admin token required")
        await tstore.board_delete(await pool_of(), (body.thesis_id or "").strip())
        return {"status": "ok"}

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
            stored = _extract_attachments(body.attachments)
            if stored:
                await tstore.set_thesis_attachments(pool, meta["id"], stored)
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
        # Fold in any reference material added this turn, and carry the whole set as prompt context.
        stored = list(d.get("attachments") or [])
        new_att = _extract_attachments(body.attachments)
        if new_att:
            stored = (stored + new_att)[:6]
            await tstore.set_thesis_attachments(pool, thesis_id, stored)
        attach_ctx = _attach_context(stored)
        turns = d.get("turns") or []
        used = sum(1 for t in turns if t.get("role") == "agent" and t.get("move") == "genesis")
        # A ReAct agent with GOAL + MEMORY (strong model). Memory (thesis + assumptions + open threads +
        # resolved) is carried on the last agent turn's payload — read it in, pass it through, store the
        # updated memory back. The agent reasons (thought), engages the input, holds or updates the thesis.
        prior_mem = next((t.get("payload", {}).get("memory") for t in reversed(turns)
                          if t.get("role") == "agent" and t.get("payload", {}).get("memory")), None)
        got = await gen.turn(_strong_llm_json(), said=said, history=turns,
                             budget_left=max(0, gen.GENESIS_BUDGET - used), memory=prior_mem,
                             context=attach_ctx)
        ready = bool(got.get("ready"))
        reply = got.get("reply") or ("Ready when you are." if ready else "Tell me a little more.")
        # The agent's current thesis this turn; keep the last good one if the model returned none.
        proposed = got.get("proposed_thesis") or d.get("proposed_thesis") or d.get("thesis") or ""
        memory = got.get("memory") or {}
        # Versioning: if the agent CHANGED the thesis this turn, record a new version (backtrackable);
        # otherwise just keep the draft text. A change prompted by the author's message is `directed`,
        # an autonomous sharpen is `genesis`. Shaping memory is persisted so it survives across sessions.
        prior_text = (d.get("proposed_thesis") or d.get("thesis") or "").strip()
        if proposed and proposed.strip() != prior_text:
            await tstore.add_thesis_version(
                pool, thesis_id, proposed, source=("directed" if said else "genesis"),
                rationale=got.get("change_rationale") or "")
        elif proposed:
            await tstore.set_proposed_thesis(pool, thesis_id, proposed)
        if memory.get("shaping_prefs"):
            await tstore.set_shaping_prefs(pool, thesis_id, memory["shaping_prefs"])
        await tstore.add_turn(pool, thesis_id, role="agent", move="genesis", text=reply,
                              payload={"ready": ready, "proposed_thesis": proposed, "memory": memory,
                                       "change_rationale": got.get("change_rationale") or ""})
        return {"status": "ok", "reply": reply, "ready": ready, "proposed_thesis": proposed,
                "memory": memory, "change_rationale": got.get("change_rationale") or "",
                "versions": await tstore.list_thesis_versions(pool, thesis_id),
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    @r.post("/thesis/{thesis_id}/edit")
    async def tl_edit_thesis(thesis_id: str, body: EditThesisIn, authorization: str = Header(default=""),
                             x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Refine the draft thesis by hand — the author's own wording wins (correct, add precision,
        generalize, add a claim). Records a backtrackable version and updates the working thesis.
        Draft-only: refuses once decomposed (edit before you test)."""
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if d.get("claims"):
            raise HTTPException(status_code=409, detail="this thesis is already decomposed")
        text = (body.text or "").strip()[:gen.THESIS_CAP]
        if len(text) < 12:
            raise HTTPException(status_code=400, detail="the thesis needs to be at least a sentence")
        current = (d.get("proposed_thesis") or d.get("thesis") or "").strip()
        if text != current:
            await tstore.add_thesis_version(pool, thesis_id, text, source="user_edit",
                                            rationale="Refined by the author")
            await tstore.set_proposed_thesis(pool, thesis_id, text)
            # An agent turn carrying the new working thesis, so the card (which reads the last such turn)
            # shows the edit — the same channel the sharpen/accept turns use.
            await tstore.add_turn(pool, thesis_id, role="agent", move="edited",
                                  text="Refined the thesis directly.", payload={"proposed_thesis": text})
        return {"status": "ok", "proposed_thesis": text,
                "versions": await tstore.list_thesis_versions(pool, thesis_id),
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid, owner_token=x_thesis_owner)}

    @r.post("/thesis/{thesis_id}/improve")
    async def tl_improve(thesis_id: str, body: ImproveIn, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Sharpen the thesis toward a SOLID investment thesis — one identified deficiency + one proposed
        rewrite at a time, which the author ACCEPTS (applied as a backtrackable version) or REJECTS (skip
        that pillar). Every call returns the NEXT proposal. Draft-only: refuses once decomposed."""
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if d.get("claims"):
            raise HTTPException(status_code=409, detail="this thesis is already decomposed")
        current = (d.get("proposed_thesis") or d.get("thesis") or "").strip()
        if not current:
            raise HTTPException(status_code=409, detail="draft a thesis first")
        action = (body.action or "propose").strip()
        pillar = (body.pillar or "").strip()
        label = gen._PILLAR_LABEL.get(pillar, pillar or "the thesis")

        if action == "accept" and (body.proposed_thesis or "").strip() and body.proposed_thesis.strip() != current:
            applied = body.proposed_thesis.strip()[:gen.THESIS_CAP]
            await tstore.add_thesis_version(pool, thesis_id, applied, source="improve",
                                            rationale=f"Strengthened: {label}")
            await tstore.set_proposed_thesis(pool, thesis_id, applied)
            current = applied
            await tstore.add_turn(pool, thesis_id, role="agent", move="improve",
                                  text=f"Accepted — strengthened {label}.",
                                  payload={"pillar": pillar, "status": "accepted", "proposed_thesis": applied})
        elif action == "reject" and pillar:
            await tstore.add_turn(pool, thesis_id, role="agent", move="improve",
                                  text=f"Skipped {label} for now.",
                                  payload={"pillar": pillar, "status": "rejected", "proposed_thesis": current})

        # Skip pillars already accepted (now covered) or explicitly rejected, from the record.
        d2 = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
        turns = (d2 or {}).get("turns") or []
        accepted, rejected = set(), set()
        for t in turns:
            p = (t.get("payload") or {})
            k, st = str(p.get("pillar") or ""), str(p.get("status") or "")
            if k in gen._PILLAR_KEYS:
                (accepted if st == "accepted" else rejected if st == "rejected" else set()).add(k)
        skip = sorted(accepted | rejected)
        prior_mem = next((t.get("payload", {}).get("memory") for t in reversed(turns)
                          if t.get("role") == "agent" and t.get("payload", {}).get("memory")), None)
        if not (prior_mem or {}).get("shaping_prefs") and d.get("shaping_prefs"):
            prior_mem = {**(prior_mem or {}), "shaping_prefs": d.get("shaping_prefs")}

        proposal = await gen.next_improvement(_strong_llm_json(), thesis=current, skip=skip, memory=prior_mem,
                                              context=_attach_context((d2 or {}).get("attachments") or []))
        pillars = [{"key": p["key"], "label": p["label"],
                    "addressed": p["key"] in accepted, "skipped": p["key"] in rejected} for p in gen.PILLARS]
        return {"status": "ok", "proposal": proposal, "skip": skip, "pillars": pillars,
                "proposed_thesis": current,
                "versions": await tstore.list_thesis_versions(pool, thesis_id),
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    @r.get("/thesis/{thesis_id}/versions")
    async def tl_versions(thesis_id: str, authorization: str = Header(default=""),
                          x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """The thesis version timeline (oldest first, active flagged) — the backtrack surface."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner)
        return {"status": "ok", "versions": await tstore.list_thesis_versions(pool, thesis_id)}

    @r.post("/thesis/{thesis_id}/revert")
    async def tl_revert(thesis_id: str, body: RevertIn, authorization: str = Header(default=""),
                        x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Backtrack the thesis to an earlier version. A later edit from here branches (redo differently).
        Draft-only: refuses once decomposed."""
        oid = await _owner(authorization)
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if d.get("claims"):
            raise HTTPException(status_code=409, detail="this thesis is already decomposed")
        got = await tstore.revert_thesis_version(pool, thesis_id, body.version_id)
        if got is None:
            raise HTTPException(status_code=404, detail="no such version")
        return {"status": "ok", "proposed_thesis": got["text"],
                "versions": await tstore.list_thesis_versions(pool, thesis_id),
                "thesis": await tstore.get(pool, thesis_id=thesis_id, owner_id=oid,
                                           owner_token=x_thesis_owner)}

    @r.post("/thesis/sample")
    async def tl_sample():
        """Generate ONE plausible, realistic, falsifiable startup thesis (from the model's parametric
        knowledge, varied by a random sector) — a one-click way to try the intake conversation. No auth,
        no persistence; a tiny LLM call. OpenAI-only (no DeepSeek fallback) for a genuinely non-obvious,
        detailed thesis — 502 if OpenAI is unconfigured rather than a weaker sample."""
        t = await gen.sample_thesis(_openai_only_llm_json())
        if not t:
            raise HTTPException(status_code=502, detail="could not generate a thesis just now — try again")
        return {"status": "ok", "thesis": t}

    @r.post("/thesis/sample/simple")
    async def tl_sample_simple():
        """GenSimpleThesis — an ISEF/CSEF-caliber high-school SCIENCE-FAIR research project (novel,
        differentiated, falsifiable, and feasible for a motivated student), across all ISEF categories,
        not just software. Separate from the main investor sample so schools can use the platform. No
        auth, no persistence. OpenAI-only (same as the main sample), 502 if OpenAI is unconfigured."""
        t = await gen.sample_thesis_simple(_openai_only_llm_json())
        if not t:
            raise HTTPException(status_code=502, detail="could not generate an idea just now — try again")
        return {"status": "ok", "thesis": t}

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
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, share)
        if d.get("is_owner"):      # tell the owner whether (and where) this thesis is on the public board
            d["board_entry"] = await tstore.board_entry_for_thesis(pool, thesis_id)
        return {"status": "ok", "thesis": d}

    @r.get("/theses")
    async def tl_recent(limit: int = 40, authorization: str = Header(default="")):
        return {"theses": await tstore.recent(await pool_of(), owner_id=await _owner(authorization),
                                              limit=min(100, max(1, limit)))}

    @r.delete("/thesis/{thesis_id}")
    async def tl_delete_thesis(thesis_id: str, authorization: str = Header(default=""),
                               x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Permanently delete a thesis the caller owns (and its board entry, if published)."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.delete_thesis(pool, thesis_id)
        return {"status": "ok"}

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
    # A single question's evidence run (corpus + web + red-team + relation judge + synthesis) can take
    # well over a minute; the heartbeat touches the run per question, so a genuinely stalled run is one
    # with no progress for a couple of minutes, not one merely working on a slow question.
    STALE_SECONDS = 150

    async def _run_research(thesis_id: str, run_id: str):
        pool = await pool_of()
        try:
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            if not d:
                return
            done_rungs = await tstore.claims_tested_by_run(pool, thesis_id, run_id)
            todo = [c for c in d["claims"]
                    if c["settleable"] != CALL_ONLY and c["rung"] not in done_rungs]
            run = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            web = atk._web_client(manifest) if (run or {}).get("metadata", {}).get("web") else None
            ctx = " ".join(str(v) for v in (d.get("subject") or {}).values())
            for c in todo:
                rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
                if (rn or {}).get("state") == "cancelled":      # stopped by the user — keep partial results
                    return
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
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            # Primary-research claims stay blockers until independently corroborated.
            for c in d["claims"]:
                if c["settleable"] == CALL_ONLY and c["verdict"] == OPEN:
                    await tstore.set_verdict(pool, thesis_id, c["rung"], "primary_research_needed",
                                             "This claim needs independent primary research.",
                                             run_id=run_id)
            fresh = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
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

    def _genesis_transcript(doc: dict) -> str:
        """Render the conversation that produced the thesis into plain text for the framing step — the
        messy specifics the one-line thesis leaves out live here. Owner-only turns; capped for cost."""
        lines = []
        for t in (doc.get("turns") or []):
            text = (t.get("text") or "").strip()
            if not text:
                continue
            who = "author" if t.get("role") == "user" else "analyst"
            lines.append(f"{who}: {text}")
        return "\n".join(lines)[-6000:]

    def _genesis_memory(doc: dict) -> dict:
        """The DISTILLED memory genesis carried forward — assumptions surfaced and open threads still
        resolving — read off the last agent turn's payload (same place tl_genesis stores it). This is
        higher-signal than the raw transcript: the author already worked out what the thesis rests on and
        what is unsettled, so the framing/question step should test THOSE, not re-derive from scratch."""
        for t in reversed(doc.get("turns") or []):
            if t.get("role") == "agent":
                mem = (t.get("payload") or {}).get("memory")
                if isinstance(mem, dict) and (mem.get("assumptions") or mem.get("open_threads")):
                    return mem
        return {}

    def _framing_context(doc: dict) -> str:
        """Raw transcript PLUS the distilled memory, so the frame sees both the messy specifics and the
        author's own surfaced assumptions / still-resolving threads."""
        parts = []
        mem = _genesis_memory(doc)
        if mem.get("assumptions"):
            parts.append("ASSUMPTIONS THE AUTHOR SURFACED (test each — its falsity would break the thesis):\n"
                         + "\n".join(f"- {a}" for a in mem["assumptions"][:8]))
        if mem.get("open_threads"):
            parts.append("STILL RESOLVING — open threads the author flagged as unsettled (the questions must "
                         "close these):\n" + "\n".join(f"- {o}" for o in mem["open_threads"][:8]))
        transcript = _genesis_transcript(doc)
        if transcript:
            parts.append("THE CONVERSATION THAT PRODUCED THE THESIS (raw — mine it for specifics):\n" + transcript)
        return "\n\n".join(parts)

    def _aspect_by_key(profile, key: str):
        return next((a for a in profile.aspects() if a.key == key), None)

    def _evidence_questions(profile, rows: list[dict]) -> list[dict]:
        """The question rows that ACTUALLY run against evidence — call_only aspects (settled by no
        document) are excluded from cost projection, the run set, and progress, so an inquiry with a
        call_only dimension still projects honestly and reaches 100% (its expert-call questions are not
        spend and never 'answered' from the record)."""
        call_only = {a.key for a in profile.aspects() if getattr(a, "settleable", "") == "call_only"}
        return [q for q in rows if q.get("aspect_key") not in call_only]

    def _attack_fn(settleable: str, ctx: str, web: bool):
        # ctx carries the FULL frame: the thesis under test + the aspect + the subject, so retrieval and
        # the relation judge disambiguate a bare target against what we are actually testing.
        async def go(target: str):
            wc = atk._web_client(manifest) if web else None
            return await atk.attack_claim(dsn, claim=target, settleable=settleable, judge_llm=judge_llm,
                                          ui=_ui(), extra_context=ctx, web_client=wc,
                                          relation_llm=_llm_json(), evidence_policy=_policy(), tenant=tenant,
                                          always_retrieve=True, reformulate_llm=_strong_llm_json())
            #  reformulate with the strong model for specifics; the inquiry model runs the user's own
            #  question — always show what the record says, even for a call_only aspect (authority policy
            #  still keeps low-tier coverage from carrying it). Never a bare "nothing found".
        return go

    async def _run_question_rows(thesis_id: str, run_id: str, rows: list[dict], web: bool):
        """Run a specific list of question rows against evidence, carrying full context (thesis + aspect
        + lens intent). Shared by a whole-inquiry run and a single-question run. Grouped by aspect so a
        support/contradiction pair on the same target shares one retrieval."""
        pool = await pool_of()
        profile = _profile()
        d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
        thesis = d.get("thesis") or ""
        subject = " ".join(str(v) for v in (d.get("subject") or {}).values())
        by_aspect: dict[str, list] = {}
        for q in rows:
            by_aspect.setdefault(q["aspect_key"], []).append(q)
        for akey, group in by_aspect.items():
            aspect = _aspect_by_key(profile, akey)
            if aspect is None:
                continue
            # call_only aspects (willingness-to-pay, switching cost, team) are settled by NO document —
            # never spend a retrieval + judge on them (panel 2026-09-16). Their questions stand as the
            # expert-call agenda; the aspect reads `unsettleable` (see _aspect_verdict).
            if getattr(aspect, "settleable", "") == "call_only":
                continue
            frame = f"Thesis under test: {thesis} | Aspect: {aspect.prompt} | {subject}".strip()
            gather = _make_gather(_attack_fn(aspect.settleable, frame, web))
            synth = _make_synthesize(_strong_llm_json(), thesis=thesis, aspect=aspect.prompt)
            for row in group:
                # Idempotent resume: a question already answered by THIS run is skipped, so a resumed
                # run re-drives only what is left and never repeats work.
                if row.get("run_id") == run_id and row.get("target_status"):
                    continue
                q = _dec.Question(kind=_dec.QuestionKind(row["kind"]), text=row["text"],
                                  target=row["target"], polarity=int(row["polarity"]))
                # Persist the gathered evidence to the ledger (keyed to the aspect/rung) BEFORE the
                # answer — otherwise the answer's [[e:id]] citations reference rows that were never
                # stored, so they cannot resolve and the answer reads "without evidence". gather is
                # cached, so run_question below reuses this same pull with no second retrieval.
                ev = await gather(q)
                for e in ev:
                    e["run_id"] = run_id
                if ev:
                    await tstore.add_evidence(pool, thesis_id, row["aspect_key"], ev)
                st = await _dec.run_question(gather, profile, q, synth)
                await tstore.answer_question(pool, thesis_id, row["id"], target_status=st.target_status,
                                             answer=st.answer, evidence_ids=list(st.evidence_ids), run_id=run_id)
                # Heartbeat per QUESTION (not per aspect): a slow aspect used to leave the run silent for
                # minutes, tripping the stale check and triggering a resume storm that deadlocked. A
                # per-question touch keeps a healthy run visibly alive.
                await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id,
                                         stage=f"q:{row['id']}", actual_delta=0.01)

    def _aspect_verdict(profile, group: list[dict]) -> str:
        """Derive a dimension's verdict from its answered questions (never a second decision path)."""
        aspect = _aspect_by_key(profile, group[0]["aspect_key"]) if group else None
        # A call_only dimension no document can settle reads `unsettleable`, not `open` — its questions
        # are never run against evidence; they route to the people-discovery leg (kernel run_aspect).
        if aspect is not None and getattr(aspect, "settleable", "") == "call_only":
            return _dec.UNSETTLEABLE
        answered = [q for q in group if q.get("target_status")]
        if not answered:
            return "open"
        statuses = [_dec.QuestionStatus(
            _dec.Question(kind=_dec.QuestionKind(q["kind"]), text=q["text"], target=q["target"],
                          polarity=int(q["polarity"])), q["target_status"]) for q in answered]
        return _dec.aggregate_aspect(profile, statuses, critical=bool(getattr(aspect, "critical", False)))

    async def _inquiries_view(pool, thesis_id: str, d: dict) -> dict:
        """The lines-of-inquiry view over a thesis — clusters (grouped by the assignment each question got)
        with a per-dimension verdict derived from the answers, plus the three synthesis artifacts. Shared
        by the owner GET and the public-board snapshot builder."""
        profile = _profile()
        qs = await tstore.list_questions(pool, thesis_id)
        by_inq: dict[str, list] = {}
        for q in qs:
            by_inq.setdefault(q["inquiry_key"], []).append(q)
        order = {k: min(int(q.get("inquiry_order") or 0) for q in g) for k, g in by_inq.items()}
        out = []
        for key in sorted(by_inq, key=lambda k: order.get(k, 0)):
            iqs = by_inq[key]
            by_dim: dict[str, list] = {}
            for q in iqs:
                by_dim.setdefault(q["aspect_key"], []).append(q)
            aspects = [{"key": dk, "prompt": getattr(_aspect_by_key(profile, dk), "prompt", dk),
                        "critical": bool(getattr(_aspect_by_key(profile, dk), "critical", False)),
                        "settleable": getattr(_aspect_by_key(profile, dk), "settleable", ""),
                        "verdict": _aspect_verdict(profile, g)} for dk, g in by_dim.items()]
            out.append({"key": key, "name": iqs[0].get("inquiry_name") or "Line of inquiry",
                        "framing": iqs[0].get("inquiry_framing") or "", "aspects": aspects, "questions": iqs})
        return {"inquiries": out,
                "deck": (d or {}).get("pitch_deck") or {}, "take": (d or {}).get("collective_take") or {},
                "competitive": (d or {}).get("competitive") or {}}

    @r.get("/thesis/{thesis_id}/inquiries")
    async def tl_inquiries(thesis_id: str, share: str = "", authorization: str = Header(default=""),
                           x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """The lines of inquiry — GENERATED per thesis and read back from the store, with per-dimension
        verdicts and the three synthesis artifacts. Accepts a read-only `share` token so a public/shared
        viewer can load the deck + take + competitive too (not just the thesis header)."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, share)
        return {"status": "ok", **await _inquiries_view(pool, thesis_id, _d)}

    @r.get("/thesis/{thesis_id}/experts")
    async def tl_experts(thesis_id: str, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Phase 0 of Expert mode — 'who to ask / what to ask'. For the aspects the RECORD cannot settle
        (call_only), surface: the role to ask (ASK_WHO), the questions to put to them (this thesis's own
        generated questions for that aspect), and any candidate named in evidence we already gathered
        (people.from_evidence — strong-key identity only, never a name merge). No new provider: this is
        decision support built from what the thesis already holds."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner)
        profile = _profile()
        if profile is None:
            return {"status": "ok", "aspects": []}
        # Candidates come from evidence already retrieved for this thesis (each carries its artifact).
        all_ev = [e for c in (d.get("claims") or []) for e in (c.get("evidence") or [])]
        facets_by_quote = {(e.get("quote") or "")[:120]: (e.get("facets") or {}) for e in all_ev}
        candidates = ppl.from_evidence(all_ev, facets_by_quote)
        qs = await tstore.list_questions(pool, thesis_id)
        q_by_aspect: dict[str, list] = {}
        for q in qs:
            q_by_aspect.setdefault(q["aspect_key"], []).append(q)
        segment = " ".join(str(v) for v in (d.get("subject") or {}).values())
        ev_by_rung: dict[str, list] = {}
        for c in (d.get("claims") or []):
            ev_by_rung[c.get("rung")] = c.get("evidence") or []
        out = []
        for a in profile.aspects():
            if getattr(a, "settleable", "") != CALL_ONLY:
                continue                              # primary: only the rungs no document can settle
            group = q_by_aspect.get(a.key, [])
            roles = list(ASK_WHO.get(a.key, ()))
            cands = [c for c in candidates if c.get("role") in roles]
            # A call_only aspect is settled by CALLS, not documents: its verdict comes from the logged
            # expert calls (tx.call_status), and the logged points are shown so the loop is visible.
            rung_ev = ev_by_rung.get(a.key, [])
            calls = [{"quote": e.get("quote", ""), "said_by": e.get("said_by", ""),
                      "said_role": e.get("said_role", ""), "firm": e.get("source_subject", ""),
                      "relation": e.get("relation", "")}
                     for e in rung_ev if e.get("source_key") == "call"]
            verdict, cnote = tx.call_status(rung_ev)
            out.append({
                "key": a.key, "prompt": a.prompt, "verdict": verdict, "verdict_note": cnote,
                "roles": [{"role": r, "label": ROLE_LABEL.get(r, r)} for r in roles],
                "questions": [q["text"] for q in group] or [a.prompt],
                "candidates": cands, "calls": calls,
                "guidance": ppl.buyer_guidance(a.prompt, segment) if (BUYER in roles and not cands) else "",
            })
        return {"status": "ok", "aspects": out}

    @r.post("/thesis/{thesis_id}/experts/discover")
    async def tl_experts_discover(thesis_id: str, body: ExpertDiscoverIn,
                                  authorization: str = Header(default=""),
                                  x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Phase 1 — discover experts for ONE call_only aspect via the people leg (Exa public-web
        profile search). Thesis-scoped (an aspect_key, not a freeform directory query): the vertical
        phrases the query per role, the kernel port runs it, and we return PUBLIC profile links only —
        ranking signal for who to reach out to, NEVER evidence. Paid; runs on an explicit user click."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        profile = _profile()
        aspect = _aspect_by_key(profile, body.aspect_key) if profile else None
        if aspect is None or getattr(aspect, "settleable", "") != CALL_ONLY:
            raise HTTPException(status_code=400, detail="expert discovery is for call_only aspects only")
        roles = list(ASK_WHO.get(body.aspect_key, ()))
        segment = " ".join(str(v) for v in (d.get("subject") or {}).values())
        decision = d.get("thesis") or ""
        try:
            from eigen_kernel.runtime.build import build_people
            client = build_people(mode=os.environ.get("EIGEN_PROVIDER_MODE") or "live",
                                  include_domains=tuple(getattr(manifest, "people_domains", ()) or ()))
        except Exception:      # noqa: BLE001 — no people leg configured → empty, reported as such
            return {"status": "ok", "aspect_key": body.aspect_key, "candidates": [], "unavailable": True}
        seen: set = set()
        found: list[dict] = []
        for role in (roles or ["operator"]):
            q = (profile.people_query(role=role, aspect_prompt=aspect.prompt, decision=decision,
                                      segment=segment)
                 if hasattr(profile, "people_query") else f"{role} in {segment}")
            try:
                rows = await client.search(q, max_results=6)
            except Exception:      # noqa: BLE001 — a provider failure thins results, never 500s
                rows = []
            for p in rows:
                url = (p.profile_url or "").strip().lower()
                if not url or url in seen:
                    continue
                seen.add(url)
                found.append({"name": p.name, "profile_url": p.profile_url, "headline": p.headline,
                              "org": p.org, "role": role, "relevance": p.relevance,
                              "provider": p.provider})
        return {"status": "ok", "aspect_key": body.aspect_key, "roles": roles, "candidates": found}

    @r.post("/thesis/{thesis_id}/experts/transcript")
    async def tl_transcript(thesis_id: str, body: TranscriptIn, authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Phase 3 — close the loop: an expert-call transcript → chunked, extracted, VERBATIM-gated
        `call` evidence on a call_only aspect, then a conservative verdict (call_status): one account is
        primary-research-needed, two INDEPENDENT accounts (person AND firm) move it, never controlling.
        Owner-only; a call is private to the thesis (store.get hides source_key=='call' from shares)."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if body.aspect_key not in SETTLEABLE:
            raise HTTPException(status_code=400, detail="unknown aspect")
        if SETTLEABLE.get(body.aspect_key) != CALL_ONLY:
            raise HTTPException(status_code=400, detail="transcripts attach to call_only aspects only")
        if not (body.transcript or "").strip():
            raise HTTPException(status_code=400, detail="paste the call transcript")
        who = (body.said_by or "an unnamed source").strip()
        subject = " ".join(str(v) for v in (d.get("subject") or {}).values())
        points = await tx.extract_call_points(_llm_json(), transcript=body.transcript,
                                              aspect_prompt=QUESTION.get(body.aspect_key, body.aspect_key),
                                              thesis=d.get("thesis") or "", subject=subject)
        if not points:
            return {"status": "ok", "aspect_key": body.aspect_key, "points": [],
                    "note": "Nothing in that transcript could be tied verbatim to this aspect."}
        rows = [{
            "side": "for" if p["relation"] == "supports" else "against", "relation": p["relation"],
            "register": STATED, "source_key": "call", "signal_only": False,
            "title": who + (f" ({body.said_role})" if body.said_role else "")
                     + (f", {body.firm}" if body.firm else ""),
            "quote": p["quote"], "source_url": "", "basis": "first-hand, on a call",
            "said_by": who, "said_role": body.said_role or "", "source_subject": body.firm or "",
            "evidence_kind": "expert_call",
            "independence_key": f"call:{who.lower()}|{(body.firm or '').lower()}",
        } for p in points]
        await tstore.add_evidence(pool, thesis_id, body.aspect_key, rows)
        # Recompute the aspect verdict across ALL call evidence on this rung (existing + new).
        fresh = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
        rung_ev = next((c.get("evidence") or [] for c in (fresh.get("claims") or [])
                        if c.get("rung") == body.aspect_key), [])
        verdict, note = tx.call_status(rung_ev)
        if any(c.get("rung") == body.aspect_key for c in (fresh.get("claims") or [])):
            await tstore.set_verdict(pool, thesis_id, body.aspect_key, verdict, note)
        return {"status": "ok", "aspect_key": body.aspect_key, "verdict": verdict, "note": note,
                "points": [{"quote": p["quote"], "point": p["point"], "relation": p["relation"],
                            "said_by": who, "said_role": body.said_role or ""} for p in points]}

    @r.post("/experts/search")
    async def tl_experts_standalone(body: PeopleSearchIn):
        """Standalone expert discovery — the first-class Experts mode. Freeform query drives Exa's
        semantic leg; structured `filters` (title/seniority/company/past-company/skills/location) drive
        PDL's precision leg. Independent of any thesis. Returns PUBLIC profile links (signal, never
        evidence). Paid; runs on an explicit search."""
        f = {k: str(v).strip() for k, v in (body.filters or {}).items() if str(v or "").strip()}
        q = (body.query or "").strip()
        # Exa is semantic, so fold the filters into a natural-language query when the box is empty.
        if not q and f:
            bits = [f.get("seniority", ""), f.get("title", "")]
            if f.get("company"):
                bits.append("at " + f["company"])
            if f.get("past_company"):
                bits.append("previously at " + f["past_company"])
            if f.get("skills"):
                bits.append("skilled in " + f["skills"])
            if f.get("location"):
                bits.append("in " + f["location"])
            q = " ".join(b for b in bits if b).strip()
        if len(q) < 3 and not f:
            raise HTTPException(status_code=400, detail="say who you're looking for, or set a filter")
        try:
            from eigen_kernel.runtime.build import build_people
            client = build_people(mode=os.environ.get("EIGEN_PROVIDER_MODE") or "live",
                                  include_domains=tuple(getattr(manifest, "people_domains", ()) or ()))
            rows = await client.search(q or (f.get("title") or "expert"),
                                       max_results=max(1, min(20, int(body.max_results or 10))),
                                       filters=(f or None))
        except Exception:      # noqa: BLE001 — no people leg / provider error → empty, reported as such
            return {"status": "ok", "query": q, "candidates": [], "unavailable": True}
        seen: set = set()
        out: list[dict] = []
        for p in rows:
            u = (p.profile_url or "").strip().lower()
            if not u or u in seen:
                continue
            seen.add(u)
            out.append({"name": p.name, "profile_url": p.profile_url, "headline": p.headline,
                        "org": p.org, "relevance": p.relevance, "provider": p.provider})
        return {"status": "ok", "query": q, "candidates": out}

    # ---- Expert roster (a personal, cross-thesis map) -------------------------------------------
    @r.get("/experts/roster")
    async def tl_roster(authorization: str = Header(default="")):
        """The owner's saved experts — a cross-thesis map. Experts found while validating one thesis
        stay available to the next."""
        owner = await _owner(authorization)
        return {"status": "ok", "experts": await tstore.list_experts(await pool_of(), owner)}

    @r.post("/experts/roster")
    async def tl_roster_save(body: SaveExpertIn, authorization: str = Header(default="")):
        """Save one expert to the roster (from a search result or by hand). Dedups on the profile URL."""
        owner = await _owner(authorization)
        if not (body.name or "").strip() and not (body.url or "").strip():
            raise HTTPException(status_code=400, detail="an expert needs at least a name or a profile URL")
        eid = await tstore.save_expert(await pool_of(), owner, name=body.name, url=body.url,
                                       firm=body.firm, role=body.role, headline=body.headline,
                                       source=body.source or "manual")
        return {"status": "ok", "id": eid}

    @r.delete("/experts/roster/{expert_id}")
    async def tl_roster_remove(expert_id: str, authorization: str = Header(default="")):
        owner = await _owner(authorization)
        n = await tstore.remove_expert(await pool_of(), owner, expert_id)
        return {"status": "ok", "removed": n}

    # ---- Per-line-of-inquiry transcript -> verbatim-gated insights -------------------------------
    @r.get("/thesis/{thesis_id}/transcripts")
    async def tl_inquiry_transcripts(thesis_id: str, authorization: str = Header(default=""),
                                     x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Saved expert-call transcripts + their extracted insights, grouped by line of inquiry. The raw
        transcript body is owner-only (never returned here); a shared view sees the insights, not the paste."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner)
        rows = await tstore.list_transcripts(pool, thesis_id, include_raw=False)
        if not d.get("is_owner"):
            rows = []                       # transcripts are private to the owner
        by_line: dict[str, list] = {}
        for row in rows:
            row["tally"] = tx.insight_tally(row.get("insights") or [])
            by_line.setdefault(row.get("inquiry_key") or "", []).append(row)
        return {"status": "ok", "by_line": by_line}

    @r.post("/thesis/{thesis_id}/inquiry/{inquiry_key}/transcript")
    async def tl_inquiry_transcript(thesis_id: str, inquiry_key: str, body: InquiryTranscriptIn,
                                    authorization: str = Header(default=""),
                                    x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Close the loop on a LINE OF INQUIRY: an expert-call transcript → chunked, VERBATIM-gated
        insights, each tagged validates|invalidates|context toward this line's questions and tied to the
        expert (name + public URL). Saved and, optionally, the expert added to the cross-thesis roster.
        Owner-only; the raw transcript never leaves the owner's view. Expert opinion is 'stated' — it is
        shown as a validate/invalidate tally, never allowed to settle the line (the sentiment discipline)."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if not (body.transcript or "").strip():
            raise HTTPException(status_code=400, detail="paste the call transcript")
        qs = [q for q in await tstore.list_questions(pool, thesis_id) if q.get("inquiry_key") == inquiry_key]
        if not qs:
            raise HTTPException(status_code=404, detail="no such line of inquiry")
        name = qs[0].get("inquiry_name") or inquiry_key
        framing = qs[0].get("inquiry_framing") or ""
        subject = " ".join(str(v) for v in (d.get("subject") or {}).values())
        insights = await tx.extract_insights(_llm_json(), transcript=body.transcript, inquiry_name=name,
                                             framing=framing, questions=[q["text"] for q in qs],
                                             thesis=d.get("thesis") or "", subject=subject)
        expert_id = ""
        if body.save_to_roster and ((body.expert_name or "").strip() or (body.expert_url or "").strip()):
            expert_id = await tstore.save_expert(pool, await _owner(authorization), name=body.expert_name,
                                                 url=body.expert_url, firm=body.firm, role=body.role,
                                                 headline="", source="manual")
        tid = await tstore.add_transcript(pool, thesis_id, inquiry_key, expert_id=expert_id,
                                          expert_name=body.expert_name, expert_url=body.expert_url,
                                          firm=body.firm, role=body.role, transcript=body.transcript,
                                          insights=insights)
        return {"status": "ok", "id": tid, "inquiry_key": inquiry_key, "expert_id": expert_id,
                "insights": insights, "tally": tx.insight_tally(insights),
                "note": "" if insights else "Nothing in that transcript could be tied verbatim to this line."}

    @r.delete("/thesis/{thesis_id}/transcript/{transcript_id}")
    async def tl_inquiry_transcript_remove(thesis_id: str, transcript_id: str,
                                           authorization: str = Header(default=""),
                                           x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        n = await tstore.remove_transcript(pool, thesis_id, transcript_id)
        return {"status": "ok", "removed": n}

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

    @r.post("/thesis/{thesis_id}/inquiry/cancel")
    async def tl_cancel_run(thesis_id: str, run: str = "", authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Stop a research run the user kicked off — the whole-thesis run, a single-question run, or a
        competitive run. Cooperative: the run's background loop halts before its next unit; work already
        done is kept. Cancels the given `run`, or the thesis's one active run when omitted."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        cancelled = await tstore.cancel_run(pool, thesis_id=thesis_id, run_id=(run or None))
        return {"status": "cancelled" if cancelled else "none", "run_id": cancelled}

    @r.get("/thesis/{thesis_id}/inquiry/active")
    async def tl_active_run(thesis_id: str, authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """The thesis's one in-flight run (kind is in its metadata: generate / regenerate / competitive /
        research), so the client can re-attach its progress indicator after a page refresh — the run keeps
        going server-side regardless. `{run: null}` when nothing is active."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner)
        run = await tstore.get_active_run(pool, thesis_id=thesis_id)
        kind = ""
        if run:
            m = run.get("metadata") or {}
            kind = ("generate" if m.get("generate") else "regenerate" if m.get("regenerate")
                    else "deck" if m.get("deck") else "competitive" if m.get("competitive")
                    else "brainstorm" if m.get("brainstorm") else "research")
        return {"run": run, "kind": kind, "thread_id": (run.get("metadata") or {}).get("thread_id", "") if run else ""}

    # ---- brainstorm: a continuous, memory-bearing agent over the thesis's whole context ------------
    # Each turn (and each on-click enrichment leg) is an async, stoppable run so a long think never
    # blocks the request or dangles when the user navigates away. The conversational mechanics are the
    # kernel's (compose_brainstorm); real people / prior work / media come from the app's legs, never the
    # model. Messages persist to ts_brainstorm_msg; the structured memory persists to the thread row so
    # the agent stays continuous across sessions.

    def _thread_history(thread: dict) -> list[dict]:
        hist = []
        for m in (thread.get("messages") or []):
            c = m.get("content") or {}
            text = c.get("text") if m.get("role") == "user" else c.get("reply")
            if (text or "").strip():
                hist.append({"role": m.get("role"), "text": text})
        return hist

    async def _run_brainstorm(thesis_id: str, run_id: str, thread_id: str, said: str):
        pool = await pool_of()
        _reset_llm_error()
        try:
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            thread = await tstore.get_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id)
            if not d or not thread:
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                      error={"reason": "thesis or thread is missing"})
                return
            qs = await tstore.list_questions(pool, thesis_id)
            turn = await bstorm.run_turn(_take_llm_json(), _profile(), doc=d, questions=qs, said=said,
                                         memory=thread.get("memory") or {}, history=_thread_history(thread))
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            # No reply and the model failed → surface the real reason as the agent's message, so the chat
            # tells the user why instead of showing an empty bubble.
            reply = turn.get("reply") or ""
            if not reply and _llm_reason():
                reply = f"⚠ Couldn't respond: {_llm_reason()}"
            await tstore.add_brainstorm_msg(pool, thesis_id=thesis_id, thread_id=thread_id, role="agent",
                                            content={"reply": reply,
                                                     "sections": turn.get("sections") or [],
                                                     "directions": turn.get("directions") or [],
                                                     "visuals": turn.get("visuals") or []})
            await tstore.set_brainstorm_memory(pool, thread_id=thread_id, memory=turn.get("memory") or {})
            # Name an untitled thread from its first exchange, so "past brainstorms" reads well.
            if not (thread.get("title") or "").strip():
                title = (said or "").strip()[:60] or "Brainstorm"
                await tstore.rename_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id, title=title)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed", state="completed")
        except Exception as exc:      # noqa: BLE001 — fail closed; a bad turn never corrupts the thread
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "brainstorm turn failed", "detail": str(exc)[:300]})

    async def _run_expand(thesis_id: str, run_id: str, thread_id: str, leg: str, query: str):
        pool = await pool_of()
        try:
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            card = await bstorm.run_leg(leg, manifest, _profile(), _llm_json(), doc=d or {}, query=query)
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            await tstore.add_brainstorm_msg(pool, thesis_id=thesis_id, thread_id=thread_id, role="agent",
                                            content={"card": card})
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed", state="completed")
        except Exception as exc:      # noqa: BLE001
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "enrichment failed", "detail": str(exc)[:300]})

    @r.post("/thesis/{thesis_id}/brainstorm/thread")
    async def tl_brainstorm_new(thesis_id: str, body: BrainstormThreadIn,
                                authorization: str = Header(default=""),
                                x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Open a fresh brainstorm thread on this thesis. -> the (empty) thread."""
        oid = await _owner(authorization)
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        thread = await tstore.create_brainstorm_thread(pool, thesis_id=thesis_id, owner_id=oid,
                                                       title=body.title or "")
        thread["messages"] = []
        return {"status": "ok", "thread": thread}

    @r.get("/thesis/{thesis_id}/brainstorm/threads")
    async def tl_brainstorm_threads(thesis_id: str, authorization: str = Header(default=""),
                                    x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Past brainstorms on this thesis, most-recent first (title + message count for the list)."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        threads = await tstore.list_brainstorm_threads(pool, thesis_id=thesis_id)
        return {"status": "ok", "threads": threads}

    @r.get("/thesis/{thesis_id}/brainstorm/thread/{thread_id}")
    async def tl_brainstorm_thread(thesis_id: str, thread_id: str, authorization: str = Header(default=""),
                                   x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """One thread with its full transcript + running memory."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        thread = await tstore.get_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="no such thread")
        return {"status": "ok", "thread": thread}

    @r.patch("/thesis/{thesis_id}/brainstorm/thread/{thread_id}")
    async def tl_brainstorm_rename(thesis_id: str, thread_id: str, body: BrainstormThreadIn,
                                   authorization: str = Header(default=""),
                                   x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.rename_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id, title=body.title or "")
        return {"status": "ok"}

    @r.delete("/thesis/{thesis_id}/brainstorm/thread/{thread_id}")
    async def tl_brainstorm_delete(thesis_id: str, thread_id: str, authorization: str = Header(default=""),
                                   x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.delete_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id)
        return {"status": "ok"}

    @r.post("/thesis/{thesis_id}/brainstorm/thread/{thread_id}/message")
    async def tl_brainstorm_message(thesis_id: str, thread_id: str, body: BrainstormMsgIn,
                                    authorization: str = Header(default=""),
                                    x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Post one message; the agent answers in the BACKGROUND (async, stoppable). The user message is
        persisted immediately so it renders at once; the client polls `/inquiry/status?run=` and reloads
        the thread when the run completes."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        said = (body.text or "").strip()
        if not said:
            raise HTTPException(status_code=400, detail="say something to brainstorm about")
        thread = await tstore.get_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="no such thread")
        await tstore.add_brainstorm_msg(pool, thesis_id=thesis_id, thread_id=thread_id, role="user",
                                        content={"text": said})
        key = "bs-" + tstore.new_idempotency_key()
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=0.0, approved_usd=1.0,
                                          metadata={"brainstorm": True, "thread_id": thread_id,
                                                    "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="thinking", state="running")
        asyncio.create_task(_run_brainstorm(thesis_id, run["id"], thread_id, said))
        return {"status": "running", "run": run}

    @r.post("/thesis/{thesis_id}/brainstorm/thread/{thread_id}/expand")
    async def tl_brainstorm_expand(thesis_id: str, thread_id: str, body: BrainstormExpandIn,
                                   authorization: str = Header(default=""),
                                   x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Fire ONE enrichment leg the agent suggested (experts / references / media / deepdive) in the
        BACKGROUND; on completion a sourced card is appended to the thread. Async + stoppable."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        leg = (body.leg or "").strip()
        if leg not in bstorm.LEG_KINDS:
            raise HTTPException(status_code=400, detail="unknown enrichment")
        thread = await tstore.get_brainstorm_thread(pool, thesis_id=thesis_id, thread_id=thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="no such thread")
        key = "bsx-" + tstore.new_idempotency_key()
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=0.0, approved_usd=1.0,
                                          metadata={"brainstorm": True, "expand": leg, "thread_id": thread_id,
                                                    "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage=leg, state="running")
        asyncio.create_task(_run_expand(thesis_id, run["id"], thread_id, leg, (body.query or "").strip()))
        return {"status": "running", "run": run}

    @r.post("/thesis/{thesis_id}/voices/organize")
    async def tl_voices_organize(thesis_id: str, body: VoicesOrganizeIn,
                                 authorization: str = Header(default=""),
                                 x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Organize the candidate Voices (retrieved by the client from /voices/search) into
        relevance-to-the-investigation buckets, pruning the off-topic ones — one LLM pass, cached by the
        candidate set so a revisit doesn't re-spend. Voices are a signal, not evidence."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        cands = [m for m in (body.moments or []) if isinstance(m, dict) and m.get("id")][:30]
        ids = sorted(str(m.get("id")) for m in cands)
        key = hashlib.sha256("\0".join(ids).encode("utf-8")).hexdigest()[:20] if ids else ""
        cached = await tstore.get_thesis_voices(pool, thesis_id)
        # `_VOICES_CACHE_V` invalidates caches from an earlier organize (e.g. the over-pruning version that
        # dropped podcasts/talks) — bump it whenever the organize logic changes.
        if (cached.get("key") == key and cached.get("v") == _VOICES_CACHE_V and cached.get("buckets")
                and not body.refresh):
            return {"status": "ok", "buckets": cached.get("buckets") or [], "cached": True}
        profile = _profile()
        directive = profile.voices_directive(d.get("thesis") or "") if profile and hasattr(profile, "voices_directive") else ""
        qs = await tstore.list_questions(pool, thesis_id)
        ctx = tvoices.thesis_context(d, qs)
        out = await tvoices.organize_voices(_llm_json(), directive=directive, context=ctx, candidates=cands)
        # Store the moment cards alongside the buckets so the board snapshot (and any later reader) can
        # render Voices with no live search — the buckets only carry item ids.
        payload = {"key": key, "v": _VOICES_CACHE_V, "buckets": out.get("buckets") or [],
                   "moments": cands, "generated_at": int(time.time())}
        await tstore.set_thesis_voices(pool, thesis_id, payload)
        return {"status": "ok", "buckets": payload["buckets"], "cached": False}

    async def _landscape_scan(d: dict, *, light: bool = False) -> dict:
        """Orient-before-you-ask: scan the CURRENT landscape (corpus + live web + our Startup index) into
        a dated brief, so the questions name what is real NOW, not the model's training memory. The kernel
        capability is domain-free; the legs and the 'what to learn' directive are injected here. Never
        raises — a leg we cannot reach just widens the brief's `unknowns`."""
        profile = _profile()
        decision = (d.get("proposed_thesis") or d.get("thesis") or "").strip()
        subject = " ".join(str(v) for v in (d.get("subject") or {}).values()).strip()
        directive = profile.orientation_directive(decision) if hasattr(profile, "orientation_directive") else ""
        wc = atk._web_client(manifest)
        pool = await pool_of()

        async def retrieve(q: str):
            vecs = await atk._embed_queries([q])
            async with pool.acquire() as conn:
                rows = await atk._corpus_hits(conn, tenant, q, vecs.get(q))
            return [{"title": r.get("document_title") or r.get("source_key") or "", "text": r.get("text") or "",
                     "source": r.get("source_key") or "", "as_of": r.get("published_at") or "", "register": "filed"}
                    for r in rows[:3]]

        async def web(q: str):
            if wc is None:
                return []
            res = await wc.search(q, max_results=4, open_web=True)
            out = []
            for x in res or []:
                text = " ".join(filter(None, [*(getattr(x, "highlights", ()) or ()), getattr(x, "snippet", "") or "",
                                              (getattr(x, "body", "") or "")[:1200]]))
                out.append({"title": getattr(x, "title", "") or "", "url": getattr(x, "url", "") or "", "text": text[:1500]})
            return out

        async def peers(q: str):
            if startup_search is None:
                return []
            return await startup_search(q, 4) or []

        caps = dict(n_queries=4, per_query=1, web_cap=3) if light else dict(n_queries=6, per_query=2, web_cap=6)
        # Time-bound the scan so a slow web leg can NEVER be what tips /inquiries/generate over the gateway
        # timeout — on overrun we proceed with an empty brief (generation stays current-clause-guarded).
        try:
            return await asyncio.wait_for(
                _dec.orient_and_scan(_strong_llm_json(), retrieve=retrieve, web=web, peers=peers,
                                     decision=decision, subject=subject, directive=directive, **caps),
                timeout=(10 if light else 18))
        except asyncio.TimeoutError:
            log.info("landscape scan timed out (thesis budget) — proceeding without the brief")
            return _dec.empty_brief(note="the landscape scan timed out")

    async def _run_generate(thesis_id: str, run_id: str):
        """Design the plan in the BACKGROUND (scan → frame → generate → prioritize → store) so a long,
        landscape-grounded generation never blocks the request or dies when the user navigates away.
        Cancel-checked between phases; the client polls status and stops it like any other run."""
        pool = await pool_of()
        _reset_llm_error()

        async def _cancelled() -> bool:
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            return (rn or {}).get("state") == "cancelled"

        try:
            profile = _profile()
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            if not d or profile is None:
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="setup",
                                      error={"reason": "thesis or decision profile unavailable"})
                return
            decision = d.get("thesis") or ""
            directive = profile.inquiry_directive(decision) if hasattr(profile, "inquiry_directive") else ""
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="scanning", state="running")
            # Scan the current landscape (best-effort) so the plan names what is real now, not stale memory.
            brief: dict = {}
            try:
                brief = await _landscape_scan(d)
                await tstore.set_landscape_brief(pool, thesis_id, brief)
            except Exception:      # noqa: BLE001 — never let the scan break plan generation
                brief = brief or {}
            landscape = _dec.brief_context(brief)
            if await _cancelled():
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="framing", state="running")
            # Frame (deep-understanding) — grounded in the dated landscape too.
            aspects = profile.aspects()
            frame = {}
            if hasattr(profile, "frame_directive"):
                ctx = _framing_context(d)
                if landscape:
                    ctx = (ctx + "\n\n" + landscape) if ctx else landscape
                frame = await _dec.frame_decision(
                    _take_llm_json(), decision=decision, context=ctx,
                    directive=profile.frame_directive(decision), aspects=aspects)
            if await _cancelled():
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="drafting", state="running")
            fr = frame if _dec.is_substantive(frame) else None
            # The GENERATOR sees the dated landscape too, or the currency clause has no facts to bind to.
            gen_directive = (directive + "\n\n" + landscape) if landscape else directive
            if hasattr(profile, "inquiries") and profile.inquiries():
                inquiries = await _dec.generate_by_inquiry(
                    _strong_llm_json(), decision=decision, inquiries=profile.inquiries(), aspects=aspects,
                    directive=gen_directive, frame=fr)
            else:
                inquiries = await _dec.generate_inquiries(
                    _strong_llm_json(), decision=decision, aspects=aspects, directive=gen_directive, frame=fr)
            # Anti-staleness lint (observability, non-destructive): flag question specifics not in the scan.
            if not _dec.brief_is_empty(brief):
                stale = sorted({e for inq in inquiries for q in (inq.get("questions") or [])
                                for e in _dec.unsourced_specifics(q.get("text") or "", brief)})
                if stale:
                    log.info("landscape lint (thesis=%s): %d question specific(s) not in the scan: %s",
                             thesis_id, len(stale), stale[:12])
            if await _cancelled():
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="prioritizing", state="running")
            await prio.assign_priorities(profile, inquiries, thesis=decision, llm_json=_strong_llm_json())
            if await _cancelled():
                return
            await tstore.set_inquiries(pool, thesis_id, inquiries)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed", state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — fail closed; a failed generation never corrupts state
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": _llm_reason() or "plan generation failed", "detail": str(exc)[:300],
                                         "tb": _tb.format_exc()[-800:]})

    @r.post("/thesis/{thesis_id}/inquiries/generate")
    async def tl_generate(thesis_id: str, authorization: str = Header(default=""),
                          x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Kick off the research-plan generation in the BACKGROUND and return immediately; the client polls
        status (`/inquiry/status?run=…`) and can stop it (`/inquiry/cancel`). Landscape-grounded (orient →
        scan → frame → generate) so the plan names what is real now, not the model's training memory — a
        long call that must not block the request or dangle if the user navigates away."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if _profile() is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        key = "gen-" + tstore.new_idempotency_key()
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=0.0, approved_usd=1.0,
                                          metadata={"generate": True, "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="starting", state="running")
        asyncio.create_task(_run_generate(thesis_id, run["id"]))
        return {"status": "running", "run": run}

    @r.post("/thesis/{thesis_id}/inquiries/prioritize")
    async def tl_prioritize(thesis_id: str, authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """(Re)assign P0/P1/P2 priority levels to the CURRENT questions — for a thesis drafted before
        priorities, or to re-prioritize after edits. One cheap LLM pass; no re-generation, no evidence run."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        profile = _profile()
        if profile is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        qs = await tstore.list_questions(pool, thesis_id)
        if not qs:
            raise HTTPException(status_code=409, detail="draft the questions first")
        await prio.assign_priorities(profile, [{"questions": qs}], thesis=d.get("thesis") or "",
                                     llm_json=_strong_llm_json())
        await tstore.set_question_priorities(pool, thesis_id, {q["id"]: q.get("priority", 1) for q in qs})
        return await tl_inquiries(thesis_id, authorization=authorization, x_thesis_owner=x_thesis_owner)

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

    @r.delete("/thesis/{thesis_id}/inquiry/{inquiry_key}")
    async def tl_remove_inquiry(thesis_id: str, inquiry_key: str, authorization: str = Header(default=""),
                                x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Delete one line of inquiry's drafted (unrun) questions. Answered questions are preserved."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        removed = await tstore.remove_inquiry(pool, thesis_id, inquiry_key)
        return {"status": "ok", "removed": removed}

    @r.delete("/thesis/{thesis_id}/inquiries")
    async def tl_clear_inquiries(thesis_id: str, authorization: str = Header(default=""),
                                 x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Clear ALL drafted (unrun) questions to start fresh. Answered questions are preserved."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        removed = await tstore.clear_inquiries(pool, thesis_id)
        return {"status": "ok", "removed": removed}

    async def _run_inquiry(thesis_id: str, inquiry_key: str, run_id: str, web: bool):
        """Run one line of inquiry: every question of it, then complete the run."""
        pool = await pool_of()
        try:
            rows = await tstore.list_questions(pool, thesis_id, inquiry_key)
            await _run_question_rows(thesis_id, run_id, rows, web)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — a failed run fails closed, never corrupts
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "inquiry run failed", "detail": str(exc)[:300], "tb": _tb.format_exc()[-800:]})

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
        runnable = _evidence_questions(_profile(), qs)          # call_only excluded from spend + progress
        projection = project_research_cost(len(runnable), web=body.web,
                                           web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected inquiry cost exceeds the approved maximum."}
        key = body.idempotency_key or tstore.active_question_hash(qs)
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"inquiry": inquiry_key,
                                                    "questions": [q["id"] for q in runnable],
                                                    "web": body.web, "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_inquiry(thesis_id, inquiry_key, run["id"], body.web))
        return {"status": "running", "run": run}

    def _take_llm_json():
        # The Collective Take gets the DEEP-THINKING reasoning model (gpt-5.x via take_json); the deck +
        # matrix stay on the faster strong seam. Falls back to strong if OpenAI is unconfigured.
        try:
            from .llm import take_json
            return take_json() or _strong_llm_json()
        except Exception:      # noqa: BLE001
            return _strong_llm_json()

    async def _synthesize(thesis_id: str) -> dict:
        """Compose + persist the Pitch Deck, Collective Take, and Competitive Analysis across every
        answered question. The take runs on the reasoning seam; deck + matrix on the strong seam."""
        pool = await pool_of()
        return await syn.synthesize_all(pool, thesis_id, _profile(), _strong_llm_json(),
                                        take_llm_json=_take_llm_json(), default_llm=_llm_json())

    async def _run_all(thesis_id: str, run_id: str, web: bool, todo_rows: list[dict] | None = None):
        """Run un-answered questions as ONE run, then synthesize the deck + take so both exist the moment
        the run reports completed. `todo_rows` runs a specific SUBSET (the critical-subset path); when
        omitted, every un-answered evidence question runs (the run-all path)."""
        pool = await pool_of()
        try:
            if todo_rows is None:
                qs = await tstore.list_questions(pool, thesis_id)
                todo_rows = [q for q in _evidence_questions(_profile(), qs) if not q.get("target_status")]
            if todo_rows:
                await _run_question_rows(thesis_id, run_id, todo_rows, web)
            # Synthesize BEFORE marking completed, so the poll's /inquiries refresh already carries the
            # deck + take (the status endpoint shows this stage while the two calls run).
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="synthesizing",
                                     actual_delta=0.01)
            try:
                await _synthesize(thesis_id)
            except Exception:      # noqa: BLE001 — synthesis is best-effort; findings are safe, the user
                pass               # can Rebuild. Never fail the whole run over the write-up.
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — a failed run fails closed, never corrupts
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "run-all failed", "detail": str(exc)[:300], "tb": _tb.format_exc()[-800:]})

    @r.post("/thesis/{thesis_id}/inquiries/run")
    async def tl_run_all(thesis_id: str, body: ResearchStartIn, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Run ALL lines of inquiry at once — only the un-answered questions — then build the Startup
        Pitch Deck + Collective Take. ONE run over every un-run question (respects the one-active-run
        serialization); cost projected + gated like a single line of inquiry."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        qs = await tstore.list_questions(pool, thesis_id)
        if not qs:
            raise HTTPException(status_code=409, detail="draft the questions first")
        todo = [q for q in _evidence_questions(_profile(), qs) if not q.get("target_status")]
        # Nothing to research: skip straight to a fresh synthesis (free — no evidence gathered).
        if not todo:
            result = await _synthesize(thesis_id)
            return {"status": "synthesized", "findings": result.get("findings", 0)}
        projection = project_research_cost(len(todo), web=body.web, web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected cost of running all lines of inquiry exceeds the approved maximum."}
        key = body.idempotency_key or ("all-" + tstore.active_question_hash(todo))
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"all": True, "questions": [q["id"] for q in todo],
                                                    "web": body.web, "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_all(thesis_id, run["id"], body.web))
        return {"status": "running", "run": run}

    @r.post("/thesis/{thesis_id}/inquiries/run_critical")
    async def tl_run_critical(thesis_id: str, body: ResearchStartIn, authorization: str = Header(default=""),
                              x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Run only the CRITICAL SUBSET across all lines — the questions whose answers would most move the
        fund/pass call (LLM-ranked, deterministic fallback, coverage floor over critical aspects) — then
        synthesize. Cheaper than run-all; cost projected + gated over the chosen subset."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        qs = await tstore.list_questions(pool, thesis_id)
        if not qs:
            raise HTTPException(status_code=409, detail="draft the questions first")
        # Priority levels are assigned at GENERATION (P0/P1/P2). The critical-subset run just filters by
        # level (0 = P0 crux, 1 = P0+P1, …) — no re-ranking. Fall back to runtime ranking only for older
        # theses generated before priorities existed (everything defaulted to level 1 with no P0).
        lvl = max(0, int(body.level or 0))
        evidence_qs = _evidence_questions(_profile(), qs)
        unrun = [q for q in evidence_qs if not q.get("target_status")]
        has_p0 = any(int(q.get("priority", 1)) == 0 for q in evidence_qs)
        if has_p0:
            subset = [q for q in unrun if int(q.get("priority", 1)) <= lvl]
        else:
            subset = await prio.select_subset(_profile(), evidence_qs,
                                              thesis=_d.get("thesis") or "", llm_json=_strong_llm_json(), cap=12)
        if not subset:
            result = await _synthesize(thesis_id)     # nothing to run (all answered) → free re-synth
            return {"status": "synthesized", "findings": result.get("findings", 0)}
        projection = project_research_cost(len(subset), web=body.web,
                                           web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection, "selected": len(subset),
                    "reason": "Projected cost of the critical subset exceeds the approved maximum."}
        key = body.idempotency_key or ("crit-" + tstore.active_question_hash(subset))
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"critical": True, "questions": [q["id"] for q in subset],
                                                    "web": body.web, "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_all(thesis_id, run["id"], body.web, subset))
        return {"status": "running", "run": run, "selected": len(subset)}

    @r.get("/thesis/{thesis_id}/inquiries/run_plan")
    async def tl_run_plan(thesis_id: str, authorization: str = Header(default=""),
                          x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Per-priority-level progress over the evidence questions — how many are answered vs remaining at
        each level (P0 crux → P1 → P2 …) and which layer to run next. Drives the layered Run UI so the
        author sees what's done, what's left, and can deepen one layer at a time."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner)
        qs = await tstore.list_questions(pool, thesis_id)
        ev = _evidence_questions(_profile(), qs) if _profile() else qs
        labels = {0: "P0 · the crux", 1: "P1 · core coverage", 2: "P2 · deeper coverage"}
        tot: dict[int, int] = {}
        ans: dict[int, int] = {}
        for q in ev:
            lvl = int(q.get("priority") or 1)
            tot[lvl] = tot.get(lvl, 0) + 1
            if q.get("target_status"):
                ans[lvl] = ans.get(lvl, 0) + 1
        levels = [{"level": l, "label": labels.get(l, f"P{l} · further"), "total": tot[l],
                   "answered": ans.get(l, 0), "remaining": tot[l] - ans.get(l, 0)} for l in sorted(tot)]
        answered = sum(ans.values())
        total = sum(tot.values())
        next_level = next((l for l in sorted(tot) if ans.get(l, 0) < tot[l]), None)
        # run_critical(next_level) runs EVERY unrun question with priority <= next_level (so it also mops up
        # any straggler from an earlier level), which is exactly what the "run next layer" button triggers.
        next_run = (sum(tot[l] - ans.get(l, 0) for l in tot if l <= next_level)
                    if next_level is not None else 0)
        take = d.get("collective_take") or {}
        has_take = bool((take.get("bottom_line") or {}).get("text") or (take.get("sections") and any(
            (s.get("grounded") or s.get("analysis")) for s in take.get("sections") or [])))
        return {"status": "ok", "levels": levels, "answered": answered, "total": total,
                "remaining": total - answered, "all_answered": total > 0 and answered >= total,
                "next_level": next_level, "next_run": next_run, "has_take": has_take}

    @r.post("/thesis/{thesis_id}/synthesize")
    async def tl_synthesize(thesis_id: str, authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Rebuild the Collective Take from the EXISTING findings — no research, no spend beyond the one
        grounded synthesis call. The Pitch Deck (/deck) and Competitive landscape are separate artifacts,
        generated on demand and returned as-is here."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        result = await _synthesize(thesis_id)
        return {"status": "ok", "take": result.get("take"), "deck": _d.get("pitch_deck") or {},
                "competitive": _d.get("competitive") or {}, "findings": result.get("findings", 0)}

    def _host(url: str) -> str:
        try:
            from urllib.parse import urlparse
            return (urlparse(url).hostname or "").replace("www.", "")
        except Exception:      # noqa: BLE001
            return ""

    async def _memo_scan(thesis: str, subject: str) -> list[dict]:
        """Pull a few SIMILAR public VC theses / founder memos from the open web — structure + narrative
        exemplars for the pitch deck (never a fact source; the deck still cites only findings). Returns
        [{title, url, source, snippet}]. Best-effort, time-bounded, never raises."""
        wc = atk._web_client(manifest)
        if wc is None:
            return []
        focus = (subject or thesis[:90]).strip()
        queries = [f"{focus} investment thesis", f"why we invested {focus} VC memo", f"{focus} founder thesis market"]

        async def _one(q: str):
            try:
                return await wc.search(q, max_results=3, open_web=True)
            except Exception:      # noqa: BLE001
                return []
        results = await asyncio.gather(*[_one(q) for q in queries])
        memos, seen = [], set()
        for res in results:
            for x in res or []:
                url = getattr(x, "url", "") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                text = " ".join(filter(None, [*(getattr(x, "highlights", ()) or ()), getattr(x, "snippet", "") or "",
                                              (getattr(x, "body", "") or "")[:600]])).strip()
                if text:
                    memos.append({"title": (getattr(x, "title", "") or _host(url) or "memo")[:160],
                                  "url": url, "source": _host(url), "snippet": text[:400]})
        return memos[:6]

    async def _run_deck(thesis_id: str, run_id: str):
        """Build the Startup Pitch Deck in the BACKGROUND (founder-voice synthesis over the findings, shaped
        by similar public VC/founder memos) so the Pitch Deck CTA never blocks or dangles. Stoppable."""
        pool = await pool_of()
        _reset_llm_error()
        try:
            if _profile() is None:
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="setup",
                                      error={"reason": "no decision profile is configured"})
                return
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            # Source a few SIMILAR public VC theses / founder memos (best-effort, time-bounded). They
            # ride along the deck as "similar theses to check out" cards AND, as plain text, shape the
            # deck's narrative — never a citation source.
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            memos: list[dict] = []
            try:
                thesis = (d or {}).get("thesis") or ""
                subject = " ".join(str(v) for v in ((d or {}).get("subject") or {}).values()).strip()
                memos = await asyncio.wait_for(_memo_scan(thesis, subject), timeout=15)
            except Exception:      # noqa: BLE001 — the deck builds fine without exemplars
                memos = []
            reference = "\n\n".join(f"{m['title']} ({m['source']}): {m['snippet']}" for m in memos).strip()
            res = await syn.synthesize_deck(pool, thesis_id, _profile(), _take_llm_json(),
                                            reference=reference, references=memos)
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":
                return
            # The deck came back empty though findings exist → an LLM/provider failure was swallowed;
            # fail the run with the REAL reason so the CTA shows it instead of a silent "no deck".
            deck = (res or {}).get("deck") or {}
            if res and res.get("findings") and not syn._deck_substantive(deck) and _llm_reason():
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                      error={"reason": _llm_reason(), "detail": "deck synthesis produced nothing"})
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed", state="completed")
        except Exception as exc:      # noqa: BLE001 — fail closed; never corrupt state
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": _llm_reason() or "deck build failed", "detail": str(exc)[:300]})

    @r.post("/thesis/{thesis_id}/deck")
    async def tl_deck(thesis_id: str, authorization: str = Header(default=""),
                      x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Kick off the Startup Pitch Deck build as an async, stoppable background run; the client polls
        status. Founder-voice synthesis over the findings — a separate, on-demand artifact."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if _profile() is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        key = "deck-" + tstore.new_idempotency_key()
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=0.0, approved_usd=1.0,
                                          metadata={"deck": True, "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="drafting", state="running")
        asyncio.create_task(_run_deck(thesis_id, run["id"]))
        return {"status": "running", "run": run}

    async def _run_regenerate(thesis_id: str, run_id: str):
        """Rebuild the Collective Take + Pitch Deck from the current findings in the BACKGROUND — a
        stoppable run so regenerating the read doesn't block or dangle when the user navigates away.
        Competitive stays its own (gated, web-spending) run."""
        pool = await pool_of()

        async def _cancelled() -> bool:
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            return (rn or {}).get("state") == "cancelled"

        try:
            if _profile() is None:
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="setup",
                                      error={"reason": "no decision profile is configured"})
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="take", state="running")
            await _synthesize(thesis_id)                     # rebuild the collective take
            if await _cancelled():
                return
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="deck", state="running")
            await syn.synthesize_deck(pool, thesis_id, _profile(), _take_llm_json())   # rebuild the deck
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed", state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — fail closed; a failed rebuild never corrupts state
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "regenerate failed", "detail": str(exc)[:300]})

    @r.post("/thesis/{thesis_id}/regenerate")
    async def tl_regenerate(thesis_id: str, authorization: str = Header(default=""),
                            x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Rebuild the read (Collective Take) + Pitch Deck from the latest findings as ONE async, stoppable
        background run; the client polls status and can stop it. Competitive is re-researched separately
        (it spends on the open web and is gated)."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if _profile() is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        key = "regen-" + tstore.new_idempotency_key()
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=0.0, approved_usd=1.0,
                                          metadata={"regenerate": True, "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="starting", state="running")
        asyncio.create_task(_run_regenerate(thesis_id, run["id"]))
        return {"status": "running", "run": run}

    # ── Public ThesisBoard: self-publish an anonymized, answered-only snapshot to a global gallery ──────
    @r.post("/thesis/{thesis_id}/publish")
    async def tl_publish(thesis_id: str, authorization: str = Header(default=""),
                         x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Publish (or re-publish) this thesis to the public ThesisBoard as a FROZEN, ANONYMIZED snapshot:
        the submitter's identity is stripped and unanswered lines of inquiry are removed. Owner-only; free
        (no LLM/research spend — a pure snapshot of what already exists). Idempotent per thesis: a stable
        public entry id is kept across re-publishes so shared board URLs never break."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        view = await _inquiries_view(pool, thesis_id, d)
        answered = tboard.answered_inquiries(view.get("inquiries") or [])
        if not answered:
            raise HTTPException(status_code=409,
                                detail="answer at least one line of inquiry before publishing to the board")
        # Also snapshot the Voices (organized founder/investor signal) and Brainstorm threads, so the
        # public entry carries the whole read — self-contained, anonymized, no live search on view.
        voices = tboard.public_voices(await tstore.get_thesis_voices(pool, thesis_id))
        brainstorm = tboard.anonymize_brainstorm(
            await tstore.get_brainstorm_threads_full(pool, thesis_id=thesis_id))
        payload = {"doc": tboard.anonymize_doc(d),
                   "inq": {"inquiries": answered, "deck": view.get("deck") or {},
                           "take": view.get("take") or {}, "competitive": view.get("competitive") or {},
                           "voices": voices, "brainstorm": brainstorm}}
        entry_id = await tstore.publish_board(
            pool, thesis_id=thesis_id, owner_id=str(d.get("owner_id") or ""),
            title=str(d.get("title") or ""), summary=str(d.get("thesis") or ""),
            payload=payload, findings=tboard.answered_count(answered))
        return {"status": "ok", "board_id": entry_id}

    @r.delete("/thesis/{thesis_id}/publish")
    async def tl_unpublish(thesis_id: str, authorization: str = Header(default=""),
                           x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Unpublish: remove this thesis's snapshot from the public board. Owner-only."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        await tstore.board_delete(pool, thesis_id)
        return {"status": "ok"}

    @r.get("/board")
    async def tl_board(limit: int = 60):
        """The public ThesisBoard gallery — every published snapshot, newest first. No auth; cards only
        (no owner or source-thesis identity)."""
        return {"status": "ok", "entries": await tstore.board_list(await pool_of(), limit=limit)}

    @r.get("/board/{entry_id}")
    async def tl_board_entry(entry_id: str):
        """One public board entry — the self-contained, already-anonymized snapshot. No auth."""
        entry = await tstore.board_get(await pool_of(), entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="no such board entry")
        return {"status": "ok", "entry": entry}

    async def _run_competitive(thesis_id: str, run_id: str):
        """Research the competitive landscape (open web) and store it — a background run so the request
        returns immediately and the client polls, like an inquiry run."""
        pool = await pool_of()
        _reset_llm_error()
        try:
            profile = _profile()
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            thesis = (d or {}).get("thesis") or ""
            subject = " ".join(str(v) for v in ((d or {}).get("subject") or {}).values()).strip()
            _thesis_txt, _subj, findings = await syn._load_findings(pool, thesis_id, profile)
            _cdir, cols = profile.competitive_spec()
            land = await compres.research_landscape(
                _strong_llm_json(), atk._web_client(manifest), thesis=thesis, subject=subject,
                findings=findings, columns=[dict(c) for c in cols], startup_search=startup_search,
                reason_llm=_take_llm_json())
            land["generated_at"] = int(datetime.now(timezone.utc).timestamp())
            existing = (d or {}).get("competitive") or {}
            # No players AND the model failed (not just a thin result) → surface the real cause instead of
            # a silent empty landscape.
            if not (land.get("players") or []) and not (existing.get("players") or []) and _llm_reason():
                await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                      error={"reason": _llm_reason(), "detail": "competitive research produced nothing"})
                return
            # A thin re-research that finds no players must not wipe a good landscape — only overwrite when
            # the new run actually produced players, or when there is nothing worth keeping.
            if (land.get("players") or []) or not (existing.get("players") or []):
                await tstore.set_competitive(pool, thesis_id, land)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed", actual_delta=0.0)
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — fail closed; the prior landscape is untouched
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": _llm_reason() or "competitive research failed", "detail": str(exc)[:300],
                                         "tb": _tb.format_exc()[-800:]})

    @r.post("/thesis/{thesis_id}/competitive/research")
    async def tl_competitive_research(thesis_id: str, body: ResearchStartIn,
                                      authorization: str = Header(default=""),
                                      x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Research the competitive landscape from the open web — identify the players and profile each
        across the dimensions that matter. Its own gated spend (projected first), a background run the
        client polls; stores the landscape the UI renders as player cards + a comparison table."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        if _profile() is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        projection = project_competitive_cost(compres.MAX_PLAYERS,
                                               web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected competitive-research cost exceeds the approved maximum."}
        key = body.idempotency_key or ("comp-" + tstore.new_idempotency_key())
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"competitive": True, "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_competitive(thesis_id, run["id"]))
        return {"status": "running", "run": run}

    @r.post("/thesis/{thesis_id}/competitive/candidates")
    async def tl_competitive_candidates(thesis_id: str, authorization: str = Header(default=""),
                                        x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Suggest MORE competitors to add — direct + adjacent — that are not already on the map. Cheap
        (names only, no profiling), so the user picks which to spend on. Backs the '+' expand control."""
        pool, d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        profile = _profile()
        if profile is None:
            raise HTTPException(status_code=409, detail="no decision profile is configured")
        land = d.get("competitive") or {}
        existing = tuple(p.get("name", "") for p in (land.get("players") or []))
        subject = " ".join(str(v) for v in (d.get("subject") or {}).values()).strip()
        cands = await compres.suggest_candidates(
            _strong_llm_json(), atk._web_client(manifest), thesis=d.get("thesis") or "", subject=subject,
            space=land.get("space") or "", existing=existing, startup_search=startup_search,
            reason_llm=_take_llm_json())
        return {"status": "ok", "candidates": cands, "space": land.get("space") or subject}

    async def _run_competitive_add(thesis_id: str, run_id: str, names: list[str]):
        """Profile the chosen candidates and APPEND them to the landscape — a background run, like the
        initial research, so existing players are kept and the map just grows."""
        pool = await pool_of()
        try:
            profile = _profile()
            d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
            land = (d or {}).get("competitive") or {}
            subject = " ".join(str(v) for v in ((d or {}).get("subject") or {}).values()).strip()
            space = land.get("space") or subject or ((d or {}).get("thesis") or "")[:80]
            _cdir, cols = profile.competitive_spec()
            cols = [dict(c) for c in cols]
            players = await compres.profile_players(_strong_llm_json(), atk._web_client(manifest),
                                                    names=names, space=space, columns=cols)
            await tstore.add_competitive_players(pool, thesis_id, players, space=space, columns=cols)
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed", actual_delta=0.0)
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — fail closed; existing players untouched
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "adding competitors failed", "detail": str(exc)[:300],
                                         "tb": _tb.format_exc()[-800:]})

    @r.post("/thesis/{thesis_id}/competitive/add")
    async def tl_competitive_add(thesis_id: str, body: CompetitiveAddIn, authorization: str = Header(default=""),
                                 x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Profile the selected candidate competitors and add them to the landscape — gated per selection,
        a background run the client polls."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        names = [str(n).strip() for n in (body.names or []) if str(n).strip()][:12]
        if not names:
            raise HTTPException(status_code=400, detail="choose at least one competitor to add")
        projection = project_competitive_cost(len(names), web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection, "selected": len(names),
                    "reason": "Projected cost of profiling the selected competitors exceeds the approved maximum."}
        key = body.idempotency_key or ("compadd-" + tstore.new_idempotency_key())
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"competitive": True, "questions": [], "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_competitive_add(thesis_id, run["id"], names))
        return {"status": "running", "run": run, "selected": len(names)}

    async def _run_single(thesis_id: str, run_id: str, qid: str, web: bool):
        """Run ONE question (carrying its full thesis+aspect context) and complete the run."""
        pool = await pool_of()
        try:
            row = next((q for q in await tstore.list_questions(pool, thesis_id) if q["id"] == qid), None)
            if row is not None:
                await _run_question_rows(thesis_id, run_id, [row], web)
            rn = await tstore.get_run(pool, thesis_id=thesis_id, run_id=run_id)
            if (rn or {}).get("state") == "cancelled":      # user stopped it — don't flip to completed
                return
            # A new answer changes the read: rebuild the Collective Take (and its reasoning map) so the
            # Brief always reflects the latest findings — bounded + fallback-guarded, so it stays reliable.
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="synthesizing")
            try:
                await _synthesize(thesis_id)
            except Exception:      # noqa: BLE001 — synthesis is best-effort; the answer is safe regardless
                pass
            await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run_id, stage="completed",
                                     state="completed")
        except tstore.SpendCapError as exc:
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="cap",
                                  error={"reason": "approved cost reached", "detail": str(exc)})
        except Exception as exc:      # noqa: BLE001 — a failed run fails closed, never corrupts
            import traceback as _tb
            await tstore.fail_run(pool, thesis_id=thesis_id, run_id=run_id, stage="error",
                                  error={"reason": "question run failed", "detail": str(exc)[:300], "tb": _tb.format_exc()[-800:]})

    @r.post("/thesis/{thesis_id}/question/{qid}/run")
    async def tl_run_question(thesis_id: str, qid: str, body: ResearchStartIn,
                              authorization: str = Header(default=""),
                              x_thesis_owner: str = Header(default="", alias="X-Thesis-Owner")):
        """Run a SINGLE question against evidence — cost projected + gated, serialized per thesis."""
        pool, _d = await _read(thesis_id, authorization, x_thesis_owner, owner_only=True)
        row = next((q for q in await tstore.list_questions(pool, thesis_id) if q["id"] == qid), None)
        if row is None:
            raise HTTPException(status_code=404, detail="no such question")
        projection = project_research_cost(1, web=body.web, web_available=bool(atk._web_client(manifest)))
        if projection["projected_usd"] > max(0.0, body.max_usd):
            return {"status": "refused", "projection": projection,
                    "reason": "Projected question cost exceeds the approved maximum."}
        key = body.idempotency_key or ("q-" + qid + "-" + tstore.active_question_hash([row]))
        try:
            run = await tstore.create_run(pool, thesis_id=thesis_id, idempotency_key=key,
                                          projected_usd=projection["projected_usd"], approved_usd=body.max_usd,
                                          metadata={"question": qid, "questions": [qid], "web": body.web,
                                                    "tenant": tenant})
        except (ValueError, tstore.ActiveRunError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run.get("state") == "completed":
            return {"status": "completed", "run": run}
        await tstore.advance_run(pool, thesis_id=thesis_id, run_id=run["id"], stage="running", state="running")
        asyncio.create_task(_run_single(thesis_id, run["id"], qid, body.web))
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
