# Test Thesis Lean Decision Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Test Thesis into a secure, evidence-gated investor workflow with a deterministic Fund, Pass, or Continue diligence brief.

**Architecture:** Preserve the thesis ledger and routes. Add one generic kernel evidence-binding seam, one tech-vertical policy, and one minimal research-run record; keep orchestration in `apps/api/thesis` and simplify the existing vanilla web view around the decision brief.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, asyncpg/PostgreSQL, pytest, vanilla HTML/CSS/JavaScript, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-11-test-thesis-lean-design.md`

## Global Constraints

- Recommendation is exactly `fund`, `pass`, or `continue_diligence`; no probabilities or investment-advice score.
- Kernel mechanics remain domain-free; technology-investing vocabulary and admissibility live in `eigen_vertical_tech`.
- Search direction never determines evidence relationship. Sentiment is always a non-controlling signal.
- No paid calls, ingest, deployment, production mutation, or new frontend framework.
- The 390 px layout is single-column with 40–44 px targets, visible focus, and live progress/errors.

---

### Task 1: Deterministic Vertical Policy

**Files:**
- Create: `packages/vertical_tech/eigen_vertical_tech/thesis_policy.py`
- Create: `packages/vertical_tech/eigen_vertical_tech/test_thesis_policy.py`
- Modify: `packages/kernel/eigen_kernel/contract/manifest.py`
- Modify: `packages/vertical_tech/eigen_vertical_tech/manifest.py`

**Interfaces:** `TechThesisPolicy.qualify(evidence, *, settleable) -> tuple[str, str]`; `TechThesisPolicy.decide(claims) -> dict`; optional `VerticalManifest.thesis_policy`.

- [ ] Write literal failing tests: a critical contradiction returns `pass`; all critical claims supported returns `fund`; open, conflicted, under-tested, unavailable, failed, or primary-research-needed critical claims return `continue_diligence`; one call note never qualifies a critical claim.
- [ ] Run `/Users/sgupta/eigen/.venv/bin/python -m pytest packages/vertical_tech/eigen_vertical_tech/test_thesis_policy.py -q` and confirm the missing policy fails.
- [ ] Implement the smallest frozen policy and manifest seam. The policy consumes dictionaries; app and kernel import no tech nouns.
- [ ] Run the policy tests plus `packages/kernel/eigen_kernel/eval/test_eval_and_conformance.py`.
- [ ] Commit as `feat(thesis): add deterministic tech decision policy`.

### Task 2: Evidence Binding and Provenance

**Files:**
- Create: `packages/kernel/eigen_kernel/research/evidence_binding.py`
- Create: `packages/kernel/eigen_kernel/research/test_evidence_binding.py`
- Modify: `apps/api/thesis/attack.py`
- Modify: `apps/api/thesis/test_thesis.py`

**Interfaces:** `EvidenceCandidate`; `bind_candidates(claim, candidates, judge_llm) -> list[dict]`; `attack_claim(..., evidence_policy=None, tenant="demo")` returns `research_status`, `attack_attempted`, and qualified evidence.

- [ ] Write failing fixtures for wrong subject, wrong evidence kind, intent-as-fact, stale period, sentiment-as-fact, and an against-query result that actually supports the claim.
- [ ] Run the two focused test files and confirm current query-side labeling fails.
- [ ] Implement one closed-shape batch judgment per claim. Compute exact-span presence/hash locally; retain document ID, block ID, facets, subject, kind, and period. Missing/malformed judge output fails closed to `context`.
- [ ] Count only fully gated `supports`/`contradicts`; make no-refuter `attack_unavailable`, completed empty attack `under_tested`, and transport error `failed`.
- [ ] Re-run focused tests and commit as `fix(thesis): gate evidence relationships and provenance`.

### Task 3: Secure Storage and Research Runs

**Files:**
- Modify: `apps/api/thesis/store.py`
- Create: `apps/api/thesis/test_store.py`

**Interfaces:** `create(...) -> {id, owner_token}` with only its SHA-256 hash stored; `get(..., owner_id="", owner_token="", share_token="")`; `create_run`, `get_run`, `advance_run`, `fail_run`.

- [ ] Write failing recording-connection tests for authenticated and anonymous owners, missing/wrong capabilities, valid read-only share, empty anonymous recent, owner-scoped recent, evidence uniqueness, idempotent run creation, and one-active-run enforcement.
- [ ] Run `apps/api/thesis/test_store.py` and confirm the current IDOR and empty-owner query fail.
- [ ] Add additive columns for owner hash, decision/research state, claim critical/falsifier/status, and evidence provenance/gates/run; add one `ts_run` table and database uniqueness constraints.
- [ ] Implement fail-closed authorization, run stage/cost tracking, evidence idempotency, and latest-completed-decision preservation.
- [ ] Re-run store and thesis tests and commit as `fix(thesis): secure ownership and research runs`.

### Task 4: Authorized, Cost-Gated Routes

**Files:**
- Modify: `apps/api/thesis/routes.py`
- Create: `apps/api/thesis/test_routes.py`
- Modify: `apps/api/app.py`

**Interfaces:** owner header `X-Thesis-Owner`; share query `?share=<token>`; owner-only `POST`/`DELETE /thesis/{id}/share`; `PATCH /thesis/{id}/claim/{rung}`; `POST /thesis/{id}/research/start`; approved `run_id` on attack/argue.

- [ ] Write failing real-FastAPI route tests for owner/share authorization and revocation, anonymous recent, claim editing, invalid rung, explicit decomposition failure, complete creation/research projections, pre-spend cap refusal, run idempotency, and synthesis failure fallback.
- [ ] Run the route tests and confirm unauthorized mutation and incomplete projection fail.
- [ ] Add one route authorization helper; require owner on every mutation; return read-only share views; make decomposition failure explicit rather than saving a generic ladder; pass the deployment tenant instead of hard-coded `demo`.
- [ ] Project refuter, batched relationship judgment, optional web ceiling, and final synthesis up front. Require one approval and persist actual progress/cost on the run.
- [ ] Persist author/interview evidence as context and `primary_research_needed`; never auto-settle from one account. Persist the vertical policy's deterministic decision after completed research.
- [ ] Re-run all thesis API tests and commit as `feat(thesis): enforce authorization and upfront research caps`.

### Task 5: Stable Cases

**Files:**
- Modify: `apps/api/thesis/argue.py`
- Modify: `apps/api/thesis/test_thesis.py`

**Interfaces:** case citations are `[[e:<evidence_id>]]`; `sanitize_case(text, allowed_ids) -> str` removes unresolved markers and unsupported factual sentences fail closed.

- [ ] Write failing tests proving reordering does not retarget a citation, invented IDs vanish, and prompts retain source identity, kind, period, and gate metadata.
- [ ] Run the focused tests and observe numeric citation failure.
- [ ] Emit immutable evidence-ID markers, validate model output against allowed IDs, and keep empty-side copy deterministic. Case prose cannot change claim status or recommendation.
- [ ] Re-run and commit as `fix(thesis): make case citations stable`.

### Task 6: Decision-First Web Workflow

**Files:**
- Modify: `apps/web/index.html`
- Replace: `apps/web/tests/test_thesis_mode.mjs`

**Interfaces:** local owner map `eigen.thesis.owners.v1`; `window.TH.enter/submit/reset`; share URLs contain only a read-only token.

- [ ] Replace regex-only checks with executable controller/render behavior tests using the Node runner and a minimal real DOM fixture: owner headers, read-only sharing, reset/hash clearing, local recent, durable errors, stable evidence links, and recommendation-first ordering.
- [ ] Run the web tests and confirm the current behavior fails.
- [ ] Render recommendation, decisive reasons, both cases, unresolved cruxes, then critical-first claim disclosures. Add pre-run claim editing, one full-cost approval, run-scoped progress/retry, a simple interview-note form, owner-only Share, visible Recent, and correct New behavior.
- [ ] Add a `max-width:560px` single-column pass, 44 px controls, `aria-live`, unique names, `:focus-visible`, wrapping, and reduced-motion support.
- [ ] Re-run web tests and commit as `feat(thesis): deliver decision-first investor workflow`.

### Task 7: Free Verification and Review

**Files:** Modify only files implicated by verified regressions from Tasks 1–6.

- [ ] Run `/Users/sgupta/eigen/.venv/bin/python -m pytest packages -q`, all thesis API tests, both kernel guardrail commands, the app construction smoke test, and both web test files.
- [ ] Run the app without paid providers and inspect desktop plus 390 px loading, success, empty, shared, attack-unavailable, and error states; verify focus order and touch sizing.
- [ ] Check every spec acceptance criterion against code and tests; report unrelated baseline failures rather than normalizing them.
- [ ] Request independent code review; reproduce each valid finding with a failing test before fixing it.
- [ ] Re-run the complete free suite and use `superpowers:finishing-a-development-branch`. Do not deploy, ingest, push, merge, or spend API credit without separate authorization.
