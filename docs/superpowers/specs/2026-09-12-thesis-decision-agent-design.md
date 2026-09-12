# Design: Test Thesis — Decision Agent, Async Test, One Follow-up Agent

**Date:** 2026-09-12
**Status:** Draft for panel review (no code yet)
**Feature:** `apps/api/thesis/` (flag `EIGEN_THESIS=1`, live in prod) + `apps/web/index.html` (`body[data-mode="thesis"]`, the `TH` IIFE)
**Supersedes the flow of:** `docs/superpowers/specs/2026-09-11-test-thesis-lean-design.md` (the decision brief, gates, auth, and run ledger all stay; the *interaction shape* changes).

---

## 1. Intent

Test Thesis today jumps a messy one-liner straight into a fixed 10-rung decomposition, then the
browser drives the evidence run claim-by-claim with partial results painting in as they land, and the
follow-up conversation is bolted to a single "focus rung." The owner wants three concrete changes:

1. **A decision agent that converses to a thesis.** Take the user's messy input, ask *neutral*
   clarifying questions when — and only when — something load-bearing is missing, and converge with
   the user on a concrete, falsifiable one-sentence thesis (a *decision to be informed against*). The
   **human owns the final statement**; the agent only sharpens.
2. **One explicit "Test this thesis" that runs everything asynchronously — no partial.** The user
   triggers the whole run; it executes server-side to completion; the UI shows progress but **never a
   half-painted decision brief**. When it finishes, the user sees the complete result at once.
3. **One follow-up conversation agent.** After results, a single agent the user talks to. The user
   **picks a claim or a set of claims** as context and asks follow-up questions about them. It
   *explains* the evidence; it does **not** re-grade verdicts or move the recommendation.

This mirrors the pattern proven in `~/factra` (the gated clarifier + the decision-sharpening agent):
**Rule 18 — the LLM owns meaning/wording; code owns structure, the gate, and what gets recorded; the
human owns the decision.** It also reuses eigen's own guided-analyst discipline
(`apps/api/startups/intake.py`): a question must be **missing, critical, AND answerable**, the model
may only *choose and phrase* from a measured shortlist, one small JSON call per turn, and every
failure mode falls back to a deterministic gate.

## 2. Contract

### User-visible behavior

- **Genesis (draft) phase.** The user types a rough idea. The agent replies briefly, shows its best
  **proposed one-sentence thesis** (product · buyer/segment · substitute it displaces), and asks up to
  ~2 neutral clarifying questions **only if** the thesis is missing a load-bearing element it cannot
  reasonably infer. The proposed thesis is always visible with **"Use this thesis →"** and is
  **editable** — the user can accept, tweak, or keep talking. Nothing is decomposed until the user
  confirms.
- **Claims phase.** On confirm, the thesis decomposes into the fixed ladder (existing `decompose.py`),
  claims render, and a single **"Test this thesis"** action appears with an upfront projected cost and
  one approval (existing projection + cap).
- **Testing phase (async, no partial).** On approval, the whole run executes server-side. The UI
  shows a single derived progress line (e.g. "testing 4 of 10 claims · then writing the cases") and a
  **Stop**. The decision brief, verdicts, and per-claim evidence are **hidden or shown as "testing…"**
  the entire time — no verdict, no case, no recommendation paints until the run completes.
- **Tested phase.** When the run completes the client renders the full brief + claims + evidence at
  once. If the run fails or a deploy interrupts it, the user sees a clear "the run stopped — resume"
  and can resume idempotently (no duplicate evidence, no double-charge for completed claims).
- **Follow-up (one agent).** A single discussion agent. A **claim context selector** (checkboxes /
  chips over the claims) sets which claim(s) are in scope; the composer asks about *those* claims. The
  agent answers grounded in the selected claims' evidence and the thesis, and says so when the
  evidence does not answer. It **never** changes a verdict, a case, or the recommendation.

### Success criteria

- A vague input ("something for logistics scheduling") yields ≤2 neutral questions and a proposed
  thesis; a already-concrete input ("mid-market logistics firms will pay for automated route
  re-planning, replacing manual dispatch") yields **zero** questions and goes straight to a proposed
  thesis (the gate skips clarification — no friction).
- The confirmed thesis is exactly what the **user** accepted/edited — never a statement the agent
  committed on its own.
- "Test this thesis" produces **no partial UI**: an automated check asserts the brief/verdicts are not
  rendered while `run.state ∈ {approved, running}`.
- A run interrupted mid-flight (process restart) is **detectable and resumable**; re-running writes no
  duplicate evidence (the existing `ux_ts_evidence_run_span` unique index) and does not re-charge a
  completed claim.
- A follow-up turn scoped to two selected claims answers from *their* union of evidence and writes
  **no** change to any verdict/case/decision (deterministic integrity test).

### Invariants that must not break (the integrity core)

- **The human owns the thesis and the decision.** Genesis proposes; the user confirms/edits. The
  recommendation comes only from the deterministic vertical policy (`thesis_policy.py`) over gated
  evidence, exactly as today. The follow-up agent is **read-only to the ledger** (verdicts, cases,
  decision) — a departure from today's `/turn`, which mutates the ladder via `_apply_effect`
  (`routes.py`). That mid-conversation grading moves into the explicit Test step and is removed from
  the follow-up path.
- **Clarifying questions are neutral and gated.** Missing · critical · answerable. The agent surfaces
  what it needs and asks; it never argues for a framing or leads the user to a favorable thesis. The
  gate (is a question warranted?) is code's; the wording is the model's.
- **Grounding discipline unchanged.** Sentiment stays a non-controlling signal; evidence stays typed
  (subject/kind/period/register); span-check + congruence gates + authority all unchanged. The async
  runner calls the *same* `attack.attack_claim` / `argue.cases_for` / `policy.decide` — only the
  *driver* moves from browser to server.
- **Cost stays projected + gated + capped.** One approval before the run; the server stops and
  fail-safes if the approved cap would be exceeded; never launch a second run while one is active
  (existing `ux_ts_run_one_active`).
- **Additive migrations only; per-step fail-safe; degrade, never corrupt.**

## 3. Architecture

Three parts. Each reuses an existing seam; the net-new is deliberately small.

### 3.A Genesis — converse to a concrete thesis

**Draft thesis = a `ts_thesis` row with zero claims.** No new table: a thesis whose `ts_claim` set is
empty is a draft in genesis; once decomposed it has claims. This reuses ownership, auth, sharing, and
`ts_turn` for the genesis conversation.

- `POST /thesis` gains a `draft: true` mode: creates the row with the raw input as the working
  `thesis` text and **does not decompose**. Returns `{id, owner_token, thesis}`.
- `POST /thesis/{id}/genesis` (new; or fold into `/turn` while `claims == []`): one analyst turn.
  Input: the user's latest message. Output (closed shape, one `llm_json` call):
  `{reply, proposed_thesis, questions[], ready}` where `questions` is **0–2** neutral clarifiers and
  `proposed_thesis` is the agent's best one-sentence formalization so far.
  - **The gate is code's, over the model's OWN structured output — not a second `decompose` call.**
    (Panel fix: the earlier draft reused `decompose.py`'s subject extraction as the readiness probe;
    `decompose.py:46` is itself an `llm_json` call, so probing it per turn would be a second round-trip
    and circular. Rejected.) Instead the genesis turn emits its readiness fields **natively** in its
    one JSON object: `subject_present:{product,buyer,substitute}` (booleans) alongside `proposed_thesis`.
    Code then decides: all three present → `ready=true`, questions suppressed; each missing element →
    at most one neutral question, capped at 2. **Budget:** a genesis budget (default 3 turns) caps the
    model; spent budget or no model → `ready=true` with the raw input as the proposed thesis (never
    trap the user — the guided-analyst rule, `intake.py`).
  - Persisted to `ts_turn` (role user/agent) so the draft survives reload. `proposed_thesis` is stored
    on the row (additive column, below) so "Use this thesis" has a target.
- `POST /thesis/{id}/confirm {thesis}`: the user's accepted/edited sentence. Decomposes via existing
  `decompose.py`, writes claims, sets the row's `thesis` to the confirmed text. **This is the only
  write of the committed thesis.**

**Kernel/vertical note.** The clarifier *mechanic* (gate + budget + fail-open loop) is domain-free and
mirrors the kernel-shaped guided-analyst; the *vocabulary* (product/buyer/segment/substitute, the
ladder) is tech-specific and already lives in `apps/api/thesis` + `schema.py`. This spec keeps genesis
in `apps/api/thesis` alongside the existing tech-specific ladder — consistent with how the mode is
built today — and notes it as a known vertical-coupled surface (not kernel).

### 3.B "Test this thesis" — async, no partial

Replace the browser-driven `attack()` loop with a **server-driven run** over the existing `ts_run`
state machine.

- `POST /thesis/{id}/research/start` (existing) still projects + creates the approved `ts_run` (cap,
  idempotency, one-active).
- `POST /thesis/{id}/research/run {run_id}` (new): kicks off the whole run **in the background** and
  returns immediately (`202`, `{run: …}`). The background coroutine, for the approved run:
  1. For each settleable claim not yet done **on this run**: `attack_claim` → `add_evidence` (tagged
     `run_id`) → `set_verdict` → `advance_run(stage="claim:<rung>", actual_delta=…)`. Skips a claim
     whose evidence for this `run_id` already exists (idempotent resume). Stops + fail-safes if the
     approved cap would be exceeded.
  2. `argue` → `set_cases` + `set_overall` + `policy.decide` → `set_decision(research_status="completed")`
     → `advance_run(stage="completed", state="completed")`.
  3. Any failure → `fail_run(stage, error)`; partial evidence already written stays (a completed claim
     is durable), and resume continues from the first unfinished claim.
- `GET /thesis/{id}/research/status` (new; or read `run` off `GET /thesis`): returns
  `{state, stage, done, total, actual_usd, error}`. **Progress is derived from `ts_run` + the count of
  claims with evidence for this run — not a hand-managed flag** (the DeepDive lesson:
  progress must be derived from real state, or a spinner leaks).
- **Client**: on approval, `POST …/research/run`, then poll `…/status` every ~2.5s. While
  `state ∈ {approved, running}`: render **only** the derived progress line + Stop; the decision brief
  and claim verdicts stay hidden/"testing…". On `state == completed`: fetch the full thesis and render
  everything at once. **Auto-resume (panel fix — the load-bearing UX change):** if a poll returns a
  502/503 or the run is `failed(stage="stalled")` or `updated_at` has not advanced past the stale
  timeout, the client **silently re-POSTs `…/research/run` with the same `run_id`** and keeps polling —
  it does not surface a manual "Resume" button first. Because the run is idempotent, auto-resume masks
  an API restart (deploy) from the user instead of freezing the progress bar for minutes. Only a run
  that fails to make progress across several auto-resumes surfaces a hard error.

**Execution mechanism (the load-bearing risk).** MVP runs the coroutine **in-process**
(`asyncio.create_task`) inside `eigen-api`, because that is where the thesis feature and its
LLM/judge/web clients already live. Known hazard (memory `startup-search-feature`, `deepdive-mode`): a
`railway up` restarts the API and **kills in-flight in-process work** — the run would be left
`running` forever. Mitigations, all required for MVP:
- **Stale detection (short)**: `…/status` marks a run whose `updated_at` has not advanced in **> ~30s**
  (panel fix: not minutes — a multi-minute wait reads as broken) as `failed(stage="stalled")`, freeing
  the one-active slot so an auto-resume can take over.
- **Idempotent resume — claim-level, not span-level.** The runner skips a claim that **already has a
  verdict set by this `run_id`** (the durable per-claim checkpoint), re-driving only from the first
  unfinished claim. The evidence unique index is the backstop against a double-insert, but the resume
  DECISION is claim-level, because that index is keyed on the full tuple
  `(thesis_id, rung, run_id, span_hash, relation)` — **not** `(run_id, span_hash)` (panel correction) —
  so it must not be used as the "is this claim done?" signal. `actual_usd` only advances via
  `advance_run`, whose in-SQL cap (`WHERE actual_usd+delta <= approved_usd`, raising `SpendCapError`)
  already fail-safes an over-cap resume.
- The run is a **sequence of durable steps** (each claim's verdict + evidence committed before the
  next), so an interruption loses at most the in-flight claim.

Panel question flagged in §8: in-process asyncio + stale/resume vs. handing the run to the existing
`eigen-worker` service. MVP proposes in-process + resume (smallest, no cross-service wiring); worker
offload is the Phase-2 escape hatch if interruptions prove common.

### 3.C One follow-up agent over selected claims

- `TurnIn` gains `rungs: list[str]` (the selected claims); single `rung` stays accepted for
  back-compat (treated as `[rung]`). `converse.reply` takes the **union** of the selected claims + the
  thesis + each claim's evidence as context, and answers the user's question grounded in that set.
- **Read-only to the ledger.** In the tested phase the follow-up path does **not** call
  `_apply_effect` / `set_verdict` / `set_cases` / `set_decision`. It appends `ts_turn` rows and returns
  the reply. (Genesis, §3.A, is where the thesis text is shaped; testing, §3.B, is where verdicts are
  set. Follow-up only explains.) This is the factra integrity invariant made concrete for eigen.
- **UI**: the visible discussion thread (just shipped) becomes the single agent surface. A compact
  **context row** of claim chips (multi-select; default = the decisive/critical claims) sits above the
  composer; the composer placeholder reflects scope ("Ask about the 2 selected claims…"). The
  per-claim inline Ask (just shipped) routes through the same endpoint with `rungs=[that_rung]`, so
  there is **one** agent, reachable two ways.

## 4. Data model (additive only)

- `ts_thesis`: `+ proposed_thesis text NOT NULL DEFAULT ''` (the genesis agent's current best sentence,
  so "Use this thesis" has a target and the draft survives reload). Lifecycle is otherwise **derived**:
  no claims → draft; claims + no completed run → ready; run completed → tested. No status enum column.
  **Panel fix (required):** the recent-list query at `store.py:335` counts claims with `count(*)` over a
  `LEFT JOIN ts_claim`, which returns **1 for a zero-claim draft** (a null row), so a draft would render
  "0 of 1 tested". Change to `count(c.rung)` so a draft correctly shows "0 of 0" (and drafts may be
  filtered out of the recent list entirely — TBD in implementation).
- `ts_run`: no schema change. Reuse `state/stage/actual_usd/approved_usd/updated_at/error`. Add the
  stale-detection read in the status route (no DDL).
- `ts_turn`: `+ rungs jsonb NOT NULL DEFAULT '[]'` (the claim set a follow-up turn was scoped to;
  single `rung` still written for back-compat).
- API/Pydantic (additive): `NewThesis.draft: bool=False`; new `GenesisIn{text}`,
  `ConfirmIn{thesis}`, `ResearchRunIn{run_id}`; `TurnIn.rungs: list[str]=[]`; status response shape.

## 5. Reuse vs net-new

- **Reuse:** `decompose.py` (unchanged), `attack.attack_claim` + gates, `argue.cases_for`,
  `thesis_policy.decide`, the whole `ts_run` state machine + `create_run/get_run/advance_run/fail_run`,
  `add_evidence` uniqueness, ownership/auth/share, the just-shipped visible thread + inline-answer UI,
  and the guided-analyst discipline as the template for the genesis loop.
- **Net-new (small):** the genesis analyst turn (one closed-shape call + code gate + budget +
  fail-open); `confirm`; the background runner + `/research/run` + `/research/status` + stale
  detection; `rungs` multi-claim context in `converse.reply` + `TurnIn`; the client's poll-and-render
  (replacing the partial-paint loop) and the claim context selector; three additive columns/fields.
- **Removed:** the browser `attack()` per-claim paint loop; `/turn`'s ledger mutation in the tested
  phase.
- **Deferred (Phase 2):** worker-offloaded runs; mid-genesis alternative theses; streaming the
  follow-up; a structured in-loop `ask_human`.

## 6. Verification / eval plan (free-first, per API-credit discipline)

- **No-partial (the ship gate, deterministic):** a web test asserting the render path shows no
  brief/verdict while `state ∈ {approved, running}`, and renders the full brief exactly once on
  `completed`.
- **Follow-up is read-only (deterministic):** an API test that a `/turn` with `rungs` in the tested
  phase writes zero verdict/case/decision rows — the load-bearing integrity test.
- **Genesis gate:** unit tests — concrete input ⇒ 0 questions + a proposed thesis; vague input ⇒ ≤2
  neutral questions; no-model / spent-budget ⇒ `ready` with the raw input (never traps).
- **Resume idempotency:** a store/route test that re-running a run over a claim with existing
  `(run_id, span_hash)` evidence adds nothing and does not advance `actual_usd`; stale detection flips
  a stuck `running` run to `failed` and frees the active slot.
- **Multi-claim context:** `converse.reply` given two claims includes both claims' evidence in its
  prompt and binds its answer to that set (structural test on the prompt; the existing fake-LLM
  harness).
- **Free integration:** TestClient drive of genesis → confirm → start → run → status → tested, with a
  fake LLM/judge (no spend). One **gated** real-LLM smoke (projected + approved) only after the free
  suite is green: a vague thesis reaches a decomposable statement in ≤3 turns and the async run
  completes with a decision — record model + cost.
- **Guardrails stay green:** `check_kernel_invariant.sh` + `check_kernel_imports.py` (no domain noun
  leaks into the kernel; genesis stays in the app/vertical layer).

## 7. Phasing

- **Phase 1 (this spec):** genesis draft + analyst turn + confirm; async runner + start/run/status +
  stale/resume; `rungs` follow-up + read-only tested-phase conversation; the client poll-and-render;
  the deterministic ship-gate tests. In-process execution.
- **Phase 2 (deferred):** `eigen-worker` offload if interruptions bite; richer genesis (alternatives,
  streaming); structured `ask_human`.

## 8. Open questions / risks (for the panel)

1. **Async execution model.** In-process `asyncio` + stale-detection + idempotent resume (MVP) vs.
   `eigen-worker` offload. The memory is explicit that `railway up` kills in-process work and jobs must
   resume idempotently — is stale+resume enough for a *user-facing* run, or does the first version need
   the worker? (Leaning MVP-in-process; want the panel's read on the failure surface.)
2. **Draft-as-empty-claims** vs. an explicit `status` column. Deriving the lifecycle avoids an enum but
   makes "draft" implicit — does any query rely on claims-present meaning "real thesis"? (Checked:
   `/theses` recent list counts claims; a draft would show "0 of 0 tested," acceptable, but confirm.)
3. **Removing `/turn` ledger mutation.** Today a follow-up can settle/revise a claim. Moving all grading
   into the explicit Test step is cleaner and safer (no silent re-grade), but it *is* a behavior change
   — confirm the owner wants the conversation to be explain-only post-test.
4. **Neutrality of the genesis agent.** The biggest fabrication risk is an agent that leads the user to
   a flattering thesis. Mitigation: neutral-question directive + human-confirms + the proposed thesis is
   always editable + genesis writes no verdicts. Is a held-out "does it lead?" smoke worth the spend?
5. **Poll vs. stream.** Polling `…/status` every ~2.5s is simple and robust behind Railway; SSE would
   be tighter but adds a streaming surface. MVP polls.

## 9. Cost

No change to per-run spend (same attacks + one argue; projected + capped as today). Genesis adds ≤3
small `llm_json` calls per draft (~$0.002 each), gated by the genesis budget and fully free when no
model is configured. The eval is free-first; the single real-LLM smoke is projected + approved.

---

## 10. Panel review (2026-09-12)

Per CLAUDE.md ("convene a panel for big calls"): Codex (gpt-5.1), Gemini 3 Pro, and a code-grounded
subagent that verified every file:line premise. Relayed honestly.

**Gemini (substantive).** (1) In-process async as first drafted is a UX trap — a multi-minute stale
timeout leaves the user staring at a frozen bar on a deploy restart; and `eigen-worker`
(`apps/worker/main.py:31`) is **not** a generic queue (it blocks forever on the corpus-ingest drain),
so the Phase-2 offload is more work than implied. Smallest de-risk: keep in-process, **30s stale +
client auto-resume** (re-POST same `run_id`), idempotency masks the restart. (2) Removing `/turn`'s
`_apply_effect` mutation to make follow-up read-only — **correct**, matches intent. (3) Genesis gate
reusing `decompose` is **circular/expensive** (it's an LLM call) — the genesis turn must emit readiness
fields natively. (4) draft-as-empty-claims **will bite**: `store.py:335` `count(*)` shows "0 of 1", fix
to `count(c.rung)`. → **All four adopted** (§3.A, §3.B, §4 above).

**Code-grounded subagent (verification).** Premises 1–6, 8, 9, 10 TRUE at file:line. Two precision
defects, both fixed above: (a) `ux_ts_evidence_run_span` is keyed on
`(thesis_id, rung, run_id, span_hash, relation)`, **not** `(run_id, span_hash)` — so resume must be
claim-level (skip a claim with a verdict from this run), not span-level; (b) the deterministic fallback
in the guided-analyst loop is `_next` (`intake.py:334`, docstring "the deterministic floor"), not
`_floor`. Confirmed real and reused: `advance_run`'s in-SQL cap + `SpendCapError`, `create_run/get_run/
advance_run/fail_run`, the `/attack` approved-run guard + `run_id` tagging, `converse.reply(claim: dict)`
single-claim signature, `TurnIn.rung` single field, `decompose` subject extraction. Confirmed net-new:
`research/run`, `research/status`, `proposed_thesis`, `ts_turn.rungs`, `NewThesis.draft`.

**Codex.** Flaky this run (explored the tree but never emitted a clean final verdict; a second tighter
run produced nothing — the known codex-cli behavior noted in memory). Its partial reasoning did
independently corroborate the core: no genesis clarifier exists today, the missing columns, and the
"async task killed by a restart" risk. Not counted as an independent verdict; Gemini + the subagent
carry the review.

**Synthesized call.** The three-part shape holds. Ship-blocking deltas, all folded in: genesis emits
its own readiness fields (no second decompose); async stays in-process for Phase 1 but with a 30s stale
window + **client auto-resume** as the real resilience (not a manual button), resume decided
claim-level; `count(c.rung)` for the draft count. Proceed to implement Phase 1 test-first, free-first.
