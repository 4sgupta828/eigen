# Beachhead build plan — phased implementation of the new thesis-first client

**Status:** proposed plan of record
**Reference visual (source of truth):** [`beachhead-ux.md`](./beachhead-ux.md) + [`beachhead-ux-prototype.html`](./beachhead-ux-prototype.html) · live: https://claude.ai/artifact/U5xVmWs68Z9E4qY5LFqy2C
**Related:** [`landscape-grounded-questions.md`](./landscape-grounded-questions.md) (question currency — plugs into Phase 4).

We rebuild the thesis experience as a **new, thesis-first client** (React + TS + Vite) against the **unchanged FastAPI API**, at a new route, strangler-fig alongside the classic `/app`. The prototype is the contract for *what it looks like and does*; this document is the contract for *how we get there, in order*.

---

## 0. Locked decisions (confirm before Phase 0)

| Decision | Choice | Note |
|---|---|---|
| Rebuild vs. refactor | **Rebuild** a new client | Panel consensus; the monolith (~14.3k-line single file, no build) is maxed and modes-first. |
| Backend | **Unchanged, locked contract** | API is cleanly JSON-separable (zero server-render coupling). |
| Migration | **Strangler-fig** | New client at a new route; classic `/app` stays as fallback + behavioral **oracle**. |
| Stack | **React + TypeScript + Vite + TanStack Query** | Svelte is a defensible alt (better on dense text); React chosen for typed API contracts, ecosystem, hiring. *Confirm this one.* |
| Styling | **CSS variables (the Eigen tokens) + CSS Modules** (or Tailwind mapped to the tokens) | Kill the global-stylesheet pattern; tokens from `beachhead-ux.md`. |
| Serving | Vite static bundle served by FastAPI at a **new route** (e.g. `/w` or `/workspace`) | Same `_html_response`/static mechanism; add a route. |
| Routing | Client router **hash-compatible** with existing links | Must keep `#thesis/<id>`, `#view/<id>/<token>`, `#board/<entryId>` working. |

### 0.1 Client-only contracts to PRESERVE (a rewrite can silently lose these — it must not)

These live only in today's frontend; port them deliberately and cover with tests:

1. **Owner-token capability scheme.** localStorage `eigen.thesis.owners.v1` = `{thesisId: owner_token}`; sent as `X-Thesis-Owner`; server returns `is_owner`; **all edit/mutate gating is client-side** (`canMutate`). The board "your theses" list derives from these keys. Losing it = losing ownership continuity across sessions.
2. **Share-link hash shapes** (exact): `#thesis/<id>`, `#thesis/<id>?share=<token>` (legacy), `#view/<id>/<token>` (public), `#board`, `#board/<entryId>`. Reproduce or existing shared links die. (Note the *gotcha*: capture the id from the hash **before** any router side-effect rewrites it — the `#board/<id>` bug.)
3. **Run / mutation gating** (client-side): run counters + gate-waive (`eigen_runs`, `eigen_gate_skipped`), owner-only actions.
4. **Poll state machines + concurrency guards:** one active run per thesis; fail-safe miss-counting; never spawn concurrent duplicate polling tasks (this deadlocked before).
5. **Cost discipline:** projection → explicit approval → single end-to-end run ("no partials"); resumable on 502/503.

### 0.2 Reuse-as-spec (port near-verbatim — this is the moat, not a rewrite)

- `findingCiter` + `[[e:<id>]]` marker resolution → numbered footnotes / click-to-source.
- Grounded / **abstain** rendering ("Not established in the record", gap-coverage notes).
- The **answer → footnotes → evidence dossier → coverage-gap CTA → diagnostics** ladder.
- Deck (`deckSpineHtml`/`deckSlideHtml`), Take (`takeSectionHtml`), **Reasoning Map** (`reasoningMapHtml` + the measured-SVG confluence), Competitive (`competitiveHtml`).
- Typed **register** treatment (filed=fact / stated=intent / coverage=signal).

---

## Cross-cutting acceptance gate (every phase)

A phase is done only when its screens **match the prototype reference** (layout, tokens, disclosure behavior), the touched **client-only contracts** are preserved (with a test), and a **contract smoke test** validates the API shapes it consumes. Visual parity is checked against `beachhead-ux-prototype.html` at desktop and ≤400px.

---

## Phase 0 — Foundations & contracts

**Goal:** a deployable empty shell + the primitives every later phase reuses.

**In scope**
- Scaffold `apps/web-thesis/` (Vite + React + TS). One Vite pipeline → static assets; FastAPI serves it at the new route (add `@app.get("/w")` → the bundle's `index.html`, mirroring `_html_response`).
- **Typed API client**: generate TS types from FastAPI's OpenAPI (or hand-write against `apps/api/thesis/routes.py`); a thin fetch layer that injects `authorization` + `X-Thesis-Owner` (port `ownerHeaders`) and forwards `?share=`.
- **Design system as code**: the tokens + 3 fonts from `beachhead-ux.md` as CSS variables with the light/dark/`data-theme` structure; base type scale.
- **Shared primitives** (the reused UI, as components): `<Citer>`/`useCiter` (finding-id resolution), `<RegisterChip>`, `<EvidenceDrawer>` (Evidence → Source → Answer states), `<SourceView>`, `<Disc>` (accordion), `<Verdict>`, `<Stepper>`.
- **Router** with the hash-compatible routes (0.1 #2), including the capture-id-before-side-effects rule.
- **Client-only-contracts module**: the owner-token store (localStorage, try/catch), the run-gating store, typed.
- CI: typecheck + build; a `contracts.test.ts` hitting a few `/thesis/*` and `/board/*` endpoints for shape.

**Out:** any real screen content.

**Acceptance:** `/w` serves the bundle; renders "My theses (empty)"; tokens/fonts match; TS types compile; owner-token round-trips; contract test green.

---

## Phase 1 — The Brief (read-only) + My theses + public views

**Goal:** the demo-able differentiation — open a **tested** thesis and read a memo-first, click-to-source brief. Highest value, mostly a port of the provenance UI.

**In scope**
- **My theses** (home): list from `GET /theses` (signed-in) or reconstructed from owner tokens; status chips (Tested / Running / Draft); "Test a new thesis" (stub → Phase 3); "Browse ThesisBoard".
- **Brief** screen: `GET /thesis/{id}` + `GET /thesis/{id}/inquiries`. Memo-first: `<Verdict>` + the read (BLUF) + **Established vs. Crux**; tabs — **The read / Reasoning map / Lines of inquiry / Competitive / Pitch deck** (port take/reasoning-map/competitive/deck renderers).
- **Evidence drawer** with **click-to-source**: `[n]` → the exact typed source; register discipline (coverage=signal).
- **Public surfaces (read-only)**: board entry `GET /board/{entryId}` (anonymized), `#view/<id>/<token>` via `?share=` (the `/inquiries?share=` param already exists); the "clean public page" chrome; ThesisBoard gallery `GET /board`.

**Contracts touched:** share-link hashes (#thesis/#view/#board), owner-token (for is_owner → owner actions visibility), the anonymized-board read path.

**Acceptance:** the real CDS thesis (`#board/cwTjITihtvQp1Gkl`) renders like the prototype Brief; every `[n]` resolves; deck/take/reasoning-map/competitive match; board + `#view` links open with no login; owner sees owner-only affordances, public viewer does not.

---

## Phase 2 — Brainstorm (thesis-native Q&A)

**Goal:** the interactive proof — ask/poke over the thesis, cited.

**In scope**
- **Brainstorm** screen: `POST /thesis/{id}/turn` (read-only "explain the evidence, never re-grade"). Answer renders in the drawer with the full answer→footnotes→evidence→diagnostics ladder + click-to-source + gap flags.
- Proactively surfaced **"weak points to probe"**; a gap hands off to Experts (Phase 5).
- Reuse Phase-0 `<EvidenceDrawer>`/`<Citer>`.

**Acceptance:** ask a question → cited answer; clicking a citation opens the source; unprovable claims show a gap and route to Experts; matches the prototype Brainstorm.

---

## Phase 3 — Intake & Genesis (the do-side begins)

**Goal:** create and shape a thesis in the new client.

**In scope**
- **State** screen: genesis conversation — `POST /thesis` (create), `POST /thesis/{id}/genesis` (turn), the "landed thesis" card, `POST /thesis/{id}/confirm` (decompose). Sample (`/thesis/sample`, `/sample/simple`), discover-to-start (`POST /discover/theses`).
- **Improve / versions**: `POST /improve`, `GET /versions`, `POST /revert`, shaping memory.
- Phase derivation (`phaseOf`) so a thesis routes to State (draft) vs Brief (tested).

**Contracts touched:** owner-token creation flow (server returns `owner_token` on create → store it — critical, this is how anonymous ownership is established).

**Acceptance:** create → sharpen → confirm end-to-end; sample + discover seed a thesis; version backtrack works; the new owner token is persisted so the thesis is editable next session.

---

## Phase 4 — Plan & Run (the money path)

**Goal:** generate the research plan and run it under the cost gate. The **highest-risk** phase (concurrency + spend).

**In scope**
- **Plan** screen: `POST /thesis/{id}/inquiries/generate`, `POST /prioritize` (P0/P1/P2), per-question CRUD, redraft. The **landscape-scan strip** (from `landscape-grounded-questions.md`) sits above the questions with a "Re-scan" action once that backend step lands.
- **Run** screen: the **cost gate** — projection + breakdown; `POST /research/start` → `POST /research/run`; resumable **polling** `GET /research/status` (+ `/inquiry/status`); run-all / run-critical / run-one (`/inquiries/run`, `/run_critical`, `/inquiry/{key}/run`). Synthesis kicks off the Take/Reasoning/Competitive/Deck.

**Contracts touched (all of them):** cost projection→approve→single-run "no partials"; **one-active-run** guard; **poll concurrency guards** (miss-counting, no duplicate tasks); run-gating counters.

**Acceptance:** approve a projected run → single end-to-end run with a stable, resumable progress bar → lands on the Brief; killing/resuming mid-run doesn't double-spend or spawn duplicate polls; P0-only run works; matches the prototype Plan + Run.

---

## Phase 5 — Experts (seek + integrate)

**Goal:** find the people who settle undocumentable gaps, and fold their words in.

**In scope**
- **Seek experts**: `POST /experts/search`, `/thesis/{id}/experts`, `/roster` — buyer/operator/advisor, each tied to a gap.
- **Integrate expert knowledge**: transcript upload → verbatim-gated insights (validates/invalidates/context) tied to a line — `POST`/`GET /thesis/{id}/transcripts`. Expert opinion is **stated**, never controlling (authority discipline preserved).

**Acceptance:** find-people query returns candidates; a pasted transcript yields verbatim insights tied to the right line and rendered as stated evidence; matches the prototype Experts.

---

## Phase 6 — Share/Board in the new client + cutover

**Goal:** owner sharing/publishing in the new client, then flip the default.

**In scope**
- **Share** screen: `POST`/`DELETE /thesis/{id}/publish` (anonymized, answered-only), `POST`/`DELETE /thesis/{id}/share`, board gallery, "Copy link" for board + `#view`. Owner-edit vs read-only distinction.
- **Cutover:** point new share/board links at the new client; keep old links working (route-compat). When at parity, make the new client the default for thesis; the classic `/app` remains for the non-thesis modes (Q&A, Panel, etc.) or is retired per product call.

**Acceptance:** publish/unpublish/share round-trip; anonymized snapshot identical to today's; every historical `#thesis`/`#view`/`#board` link still resolves.

---

## Testing & quality strategy

- **Visual parity:** each screen diffed against `beachhead-ux-prototype.html` (desktop + ≤400px), both themes.
- **Contract tests:** typed smoke tests over every consumed endpoint's shape; run in CI so backend drift is caught.
- **Client-only-contract tests:** owner-token persistence, hash-link parsing (incl. the capture-before-side-effect rule), poll single-flight, cost-gate "no partials".
- **The classic client is the oracle:** for any ambiguous edge case, check `/app`'s behavior before changing it.
- **No LLM spend in CI:** all tests use fixtures / recorded responses (provider replay mode).

## Risks register

| Risk | Mitigation |
|---|---|
| Losing undocumented client-only contracts (§0.1) | Enumerated + test-covered in Phase 0; oracle the classic client. |
| Regressing the provenance/citation UI (the moat) | Port near-verbatim as components (§0.2); visual parity gate. |
| Poll/concurrency deadlocks on the run path | Single-flight guards ported + tested in Phase 4 before shipping run. |
| Cognitive overload / "cockpit" (panel's #1 product risk) | Memo-first + progressive disclosure enforced by the reference; the 60-sec click-to-source is Phase 1. |
| Stale questions (parametric generation) | Tracked separately in `landscape-grounded-questions.md`; UI hook in Phase 4. |
| Framework choice churn | Lock React+TS in §0 before Phase 0; Svelte only if re-decided up front. |

## Sequencing rationale

Front-load **read-only Brief + Brainstorm** (Phases 1–2): fastest path to a demo-able, cited, checkable memo — validates the provenance-UI port, the highest-value differentiation, at lowest risk. Then the **do-side** (Genesis → Plan/Run, Phases 3–4), which is larger and carries the concurrency/spend risk. Then **Experts** and **Share/cutover** (5–6). The landscape-scan backend work runs in parallel and lands into Phase 4's Plan.
