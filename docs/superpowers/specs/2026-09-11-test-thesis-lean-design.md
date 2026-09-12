# Test Thesis: Lean Investor Decision Workspace

**Status:** Approved product direction; implementation pending

**Date:** 2026-09-11

## Outcome

Test Thesis helps an investor turn an investable idea into a defensible decision brief. The user states a thesis, checks and edits its critical claims, approves the projected research cost, reviews verified evidence for and against each claim, and receives one explicit recommendation:

- **Fund** — every critical claim has qualified support and no critical blocker remains.
- **Pass** — at least one critical claim has qualified contradictory evidence.
- **Continue diligence** — the evidence is incomplete, conflicted, unavailable, or depends on unresolved primary research.

The recommendation is a transparent rule over evidence states, not a probability or investment-advice score. The model may explain the result, but may not override it.

## Product Principles

1. **Decision first.** Show the recommendation, decisive reasons, case for, case against, and unresolved cruxes before implementation detail.
2. **Evidence must earn its label.** A search query can find a candidate; only a verified relationship between the claim and the cited span can make it supporting or contradicting evidence.
3. **Failure is visible.** Missing refutation, failed decomposition, thin coverage, or failed synthesis must never masquerade as completed diligence.
4. **User control before spend.** Show one complete projected cost and require approval before any paid research stage begins.
5. **Small surface area.** Reuse the existing thesis records, kernel retrieval and provenance gates, and tech-vertical policy. Add only the storage and UI needed for a reliable first-value loop.

## The First-Value Loop

1. The user states a thesis.
2. Eigen proposes a small claim ladder and marks the decision-critical claims.
3. The user edits or confirms those claims and their falsifiers.
4. Eigen shows a single projected maximum cost for the complete research run.
5. After approval, Eigen searches both supporting and refuting directions, verifies candidate evidence, and records the research outcome per claim.
6. Eigen produces a decision brief backed by stable evidence references.
7. The user can inspect evidence, add interview notes, refine claims, and rerun only when useful.

Decomposition must remain compact: normally three to five claims. If decomposition fails, the UI reports the failure and offers retry/editing; it does not silently create a generic claim ladder.

## Scope

### Build now

- Owner-only mutation and explicit read-only sharing.
- Stable document, block, span, and gate provenance for evidence.
- Evidence relationships `supports`, `contradicts`, `context`, and `signal`.
- Claim/evidence congruence checks for entailment, subject, evidence kind, and period.
- Explicit research states, including attack unavailable, attack failed, and under-tested.
- One upfront research cost projection, backend spend cap, approval record, and actual-cost record.
- Deterministic `fund`, `pass`, or `continue diligence` recommendation.
- A compact decision-brief UI with expandable claim and evidence detail.
- Interview-note capture that cannot automatically settle a claim.
- Route, persistence, decision-policy, browser-behavior, accessibility, and mobile tests.

### Deliberately defer

- A new kernel thesis subsystem.
- Thesis revision history and frozen share snapshots.
- Automated expert discovery, outreach, calling, or transcript ingestion.
- Automatic interview cross-checking.
- Background-job infrastructure beyond a minimal idempotent run record.
- Portfolio analytics, probabilistic conviction, weighted scores, and scenario simulation.
- Rich report builders or presentation export.

## Architecture

The current layering remains intact:

- `eigen_kernel` owns domain-free mechanics: candidate retrieval, stable provenance, span verification, and generic evidence-to-claim relationship checks.
- `eigen_vertical_tech` supplies tech-investing vocabulary and judgment: claim-ladder guidance, admissible evidence kinds, authority rules, independence requirements, sentiment treatment, and decision policy.
- `apps/api/thesis` remains a thin orchestration, authorization, and persistence layer.
- `apps/web` presents the workflow without embedding evidence or investment-policy logic.

No standalone thesis engine is introduced. If existing kernel gates cannot return all required congruence facts, add one small domain-free evidence-binding seam. Its input contains a claim, candidate source identity, exact candidate span, source subject, evidence kind, and period. Its output contains:

```text
relation: supports | contradicts | context | signal
span_ok: boolean
entailed: boolean
on_subject: boolean
kind_ok: boolean
period_ok: boolean
reason: short string
```

The tech vertical configures which evidence kinds and authority levels are admissible for each tech claim type. Market sentiment is always `signal`; it cannot support or contradict a factual claim or control the recommendation. Stated intent remains distinct from realized fact.

## Minimal Data Model

Keep the existing thesis, claim, evidence, and conversation tables. Add fields through the existing migration/compatibility mechanism instead of replacing them.

### Thesis

- Persist the current deterministic decision and its decisive claim IDs.
- Persist research status separately from recommendation.
- Persist an owner credential hash for anonymous sessions when accounts are disabled.
- Retain a separate, revocable read-only share token.

### Claim

- `critical`: whether failure changes the investment decision.
- `falsifier`: what observation would refute the claim.
- `what_would_change`: the next evidence most likely to change the decision.
- `research_status`: not-run, researching, supported, contradicted, conflicted, under-tested, primary-research-needed, attack-unavailable, or failed.

### Evidence

- Stable `evidence_id`, `document_id`, `block_id`, optional atom ID, and exact-span hash.
- Source subject, evidence kind, period/as-of date, authority register, source facets, and source URL.
- Relationship and all gate outcomes.
- Research-run ID and source independence key.
- Interview notes use the same record shape with an explicit primary-research source kind.

Generated case text refers to evidence by immutable evidence ID, not by display-order numbers. The UI assigns display numbers at render time, so adding or reordering evidence cannot retarget a citation.

### Research run

Add one small run table because cost control, idempotency, and failure recovery cannot be represented safely on the thesis row. It stores:

- thesis and run IDs plus an idempotency key;
- state, projected maximum cost, approved maximum cost, and actual cost;
- start and finish timestamps plus a structured error;
- corpus/version, query, provider/model, and policy metadata sufficient to understand the run;
- the latest successfully completed stage.

Only one run may be active for a thesis. Retrying resumes after the last completed stage where safe, rather than duplicating evidence or repeating paid work.

## Authorization and Sharing

A thesis ID grants no authority.

- Authenticated deployments bind ownership to the authenticated user ID.
- When accounts are disabled, creation returns a high-entropy owner capability once. The server stores only its hash; the browser stores the capability locally by thesis ID and sends it in a header for owner reads and writes.
- A separate high-entropy share token grants read-only access to the current thesis view. It never grants mutation, cost approval, interview-note access beyond what is explicitly shared, or access to owner credentials.
- All write routes require owner authorization. All read routes require owner authorization or a valid share token.
- Server-side “recent theses” is owner-scoped. In anonymous mode, the browser constructs recent items only from locally held owner capabilities; an empty owner never means “all rows.”
- Sharing uses a dedicated read-only URL. Copying the mutable thesis URL is not presented as sharing.

The API applies the deployment tenant consistently instead of hard-coding a demo tenant.

## Research and Evidence Pipeline

### Cost gate

Before starting, the backend projects the maximum cost of decomposition (if needed), supporting/refuting retrieval, relationship judging, and case synthesis. The UI shows the total and the main components. The user approves that maximum once. The backend rejects work that would exceed the approved cap and records actual cost. Free structural and retrieval checks run before paid stages.

### Candidate discovery

Corpus retrieval runs first. Supporting and refuting queries are discovery hints only; they do not determine evidence polarity. Web retrieval is reserved for current or non-downloadable material and must enter the same materialization, source-identity, exact-span, and congruence gates before use.

### Evidence qualification

For every candidate:

1. Bind the exact span to immutable source identity.
2. Verify that the span exists.
3. Determine whether it entails support, entails contradiction, or only supplies context.
4. Verify that source subject matches claim subject.
5. Verify that evidence kind can establish the asserted fact.
6. Verify that the period is applicable.
7. Apply authority and independence policy from the vertical.

Failed span, entailment, or subject gates exclude the candidate from the case. Kind or period mismatch is excluded or displayed as context according to vertical policy. Sentiment is shown only as a market signal. Raw search snippets never affect claim status or recommendation.

The absence of a refuter is `attack-unavailable`, not `under-tested`. A completed attack that finds no qualified evidence can be `under-tested`. Transport/provider errors are `failed` and remain retryable.

### Claim qualification

The vertical policy defines the smallest defensible support threshold. The initial tech policy uses:

- one controlling, directly congruent source; or
- two independent, admissible sources whose verified spans directly support the claim.

Contradiction uses the same standard. Qualified evidence on both sides produces `conflicted`. One uncorroborated interview note cannot settle a critical claim. It can mark the claim `primary-research-needed` or contribute to support only when the policy's independence and corroboration requirements are met.

### Recommendation rule

Evaluation order is deterministic:

1. If any critical claim is contradicted, recommend **Pass**.
2. Otherwise, if every critical claim is supported and none is conflicted, failed, attack-unavailable, or primary-research-needed, recommend **Fund**.
3. Otherwise recommend **Continue diligence**.

The decision brief identifies the exact critical claims that caused the result and the next evidence that could change it. Case synthesis may improve wording but cannot change claim states or the recommendation. If synthesis fails, the deterministic brief and verified evidence still render with an explicit explanation failure.

## User Experience

### Main view

After a run, the first screen is a compact decision brief:

1. recommendation and research-state badge;
2. two or three decisive reasons linked to claims and evidence;
3. case for;
4. case against;
5. unresolved cruxes and “what would change this decision?”;
6. expandable claim cards, ordered critical-first.

Each claim card shows its state, why it has that state, and a small number of strongest evidence items. Evidence expands to show the exact quote, source, subject, kind/register, period, and gate result. More detail stays collapsed by default.

### Before and during research

- Claims are editable before the cost approval step.
- The research action displays the projected maximum and requires explicit approval.
- Progress names the current stage and is announced through an `aria-live` region.
- Errors remain visible with a scoped retry action; rendering another panel does not erase them.
- A rerun explains what changed and preserves already completed safe stages.

### Secondary actions

Conversation remains secondary and claim-scoped. A simple form lets an owner add an interview note to a selected claim, source identity, date, and whether it is firsthand. There is no expert-discovery or calling workflow in this release.

Recent theses appear in a visibly open panel. “New thesis” clears the old thesis URL and local selection. Shared views clearly say read-only and hide every mutating action.

### Mobile and accessibility

At widths of 400 px and below, the view is single-column, quotes wrap without horizontal page overflow, and dense metadata collapses behind disclosure controls. Interactive targets are at least 40–44 px. Keyboard focus is visible, controls have distinct accessible names, status changes use live regions without stealing focus, and reduced-motion preferences are honored.

## Failure and Consistency Rules

- Invalid claim-rung or state transitions return a client error; they do not become server errors.
- Decomposition failure is explicit and never saved as convincing generic output.
- Repeated start requests with the same idempotency key return the same run.
- Concurrent run creation is rejected by a database constraint or lock, not only by an in-process check.
- Evidence is unique within a run by stable source/span/claim identity.
- A failed rerun does not replace the latest completed decision brief.
- Case references are resolved from immutable evidence IDs and visibly fail closed if evidence is unavailable.
- Provider/refuter unavailability cannot produce a completed-attack timestamp or a success message.

## Testing and Verification

Implementation follows red-green-refactor. The required checks are:

- Decision-policy matrix covering every critical/noncritical claim state.
- Evidence-gate fixtures designed to look plausible while being wrong: wrong company, wrong evidence kind, intent-as-fact, sentiment-as-fact, stale period, and query-polarity mismatch.
- No-refuter, provider-error, synthesis-error, and zero-qualified-evidence states.
- Route and database authorization matrix for owner, anonymous capability, share token, wrong owner, missing owner, and revoked share.
- Cost-cap, idempotency, concurrency, retry, and duplicate-evidence behavior.
- Behavioral web tests for creation, claim editing, approval, progress, failure recovery, read-only sharing, reset, recent items, stable citations, and keyboard use. Static source-pattern tests are not sufficient.
- Visual verification in the running app at desktop width and at 390 px, including loading, success, empty, shared, and error states.
- Existing kernel/vertical tests, kernel invariants, import guardrails, and app tests.

All deterministic tests and retrieval-only probes run before any paid model call. No paid eval, corpus ingest, or production verification is part of implementation without a separate projected budget and explicit approval.

## Acceptance Criteria

The first release is complete when:

- A user can create, edit, cost-approve, research, reopen, and securely share a thesis.
- An unauthorized reader cannot discover or mutate any thesis, including in accounts-disabled mode.
- Search direction alone can never label evidence for or against.
- Every decisive evidence item exposes stable source/span identity and passing congruence gates.
- Attack failure, attack unavailability, and under-testing are visibly different states.
- Interview notes cannot single-handedly flip a critical claim or recommendation.
- The recommendation is reproducible from stored claim states and points to the claims that determined it.
- A synthesis failure still leaves a usable, evidence-backed deterministic brief.
- The primary workflow works by keyboard and is visually usable at 390 px.
- The feature's new tests and the repository's thesis-related guardrails pass without paid API calls.

Deployment and production data changes are outside this design's authorization and require a separate user request.
