# Beachhead UX — canonical visual reference

**Status:** locked reference for the new thesis-first client (implement to match)
**The visual:** [`beachhead-ux-prototype.html`](./beachhead-ux-prototype.html) — open it in a browser. Live interactive copy: https://claude.ai/artifact/U5xVmWs68Z9E4qY5LFqy2C
**This is the source of truth for the UX.** Build the new client to match it exactly; a deliberate deviation gets written down here first.

The prototype is a static mock. Its content is **real data mapped from the published “Clinical decision support” thesis** (`#board/cwTjITihtvQp1Gkl`) so the feel is faithful — but nothing in it is wired to the backend.

---

## What this replaces

The current client is a single ~14,300-line `apps/web/index.html` with hash-routed "modes" (Q&A, Panel, Startups, Voices, DeepDive, Investors, Test Thesis, Experts). The panel review (Codex + Gemini + a code-grounded check) landed on: **rebuild a new thesis-first client, don't refactor the monolith**; keep the FastAPI API as a locked contract; strangler-fig at a new route; React + TS + Vite (Svelte acceptable); port the provenance/citation UI near-verbatim, rebuild the mode shell.

The organizing idea: **the thesis is the unit of work and the shareable artifact.** The old "modes" become either lifecycle stages or in-thesis evidence, never separate destinations. Everything is **memo-first and progressively disclosed** — never all at once.

---

## The lifecycle IA (the stepper)

`⌂ My theses → 1 State → 2 Plan → 3 Run → 4 Brief → 5 Brainstorm → 6 Experts → 7 Share`

| Stage | Screen intent | Backs onto |
|---|---|---|
| **⌂ My theses** | Home. A list of theses as workspaces (Tested / Running / Draft) + "Test a new thesis" + "Browse the ThesisBoard". No generic search box. | `GET /theses`, `GET /board` |
| **1 · State** | Genesis: state it → agent sharpens (conversation) → a "landed thesis" card + "Use this thesis". Sample + "discover a published thesis to start from". | `/genesis`, `/improve`, `/confirm`, `/sample`, `/discover/theses` |
| **2 · Plan** | Thesis-native lines of inquiry as editable cards with **P0/P1/P2** priority chips + add/edit question. Opens with a **"🛰 Scanned the current landscape · as of today"** strip (dated chips) + a **Re-scan landscape** action — see the landscape spec. | `/inquiries/generate`, `/prioritize`, question CRUD; landscape scan (to build) |
| **3 · Run** | The **cost gate**: projected $ + breakdown (questions / lines / legs / time), "Approve & run" or "Run P0 crux only". Then a resumable running state ("5 of 9 · then synthesizing"). No partials. | `/research/start` → `/research/run`, `/research/status` |
| **4 · Brief** | The tested reading room, **memo-first**: verdict + the read (BLUF), an **Established vs. Crux** split, then tabs — The read / Reasoning map / Lines of inquiry / Competitive / **Pitch deck**. A right **evidence drawer** (typed by register) where clicking any `[n]` shows the exact source. | `/thesis/{id}`, `/inquiries`, `/synthesize`, `/deck`, `/competitive/*` |
| **5 · Brainstorm** | Thesis-native Q&A reframed as *poking holes* — proactively surfaces "💡 weak points to probe"; answers cited in the drawer; gaps hand off to Experts. | `/thesis/{id}/turn` |
| **6 · Experts** | Two parts: **Seek experts** (economic buyer / operator / advisor, each tied to a gap, "Find people") and **Integrate expert knowledge** (paste a transcript → verbatim validates/invalidates/context, folded into a line as *stated* evidence). | `/experts*`, `/transcripts` |
| **7 · Share** | Publish an anonymized, answered-only snapshot to the **ThesisBoard** (+ "Copy link"), or a private read-only `#view` link. Board gallery preview. | `/publish`, `/share`, `/board` |

---

## Non-negotiable design principles (visible in the prototype)

1. **Memo-first, then disclose.** The verdict + read lead; lines of inquiry, reasoning map, competitive, deck and evidence are all behind tabs/accordions/a drawer — never dumped at once.
2. **Click-to-source, everywhere.** Any `[n]` in prose reveals the exact typed source (quote + provenance) in the drawer. This is the 60-second differentiation.
3. **Typed evidence, honestly.** Sources carry a register (filed = fact, stated = intent, coverage = **signal**). Coverage is labeled signal, **never laundered into fact** (the CDS example is grounded almost entirely in coverage — the workspace says so).
4. **Hide the machinery / the jargon.** No "modes", no "feeders". Feeders are *evidence by source type*; "thesis-native Q&A" is just "Brainstorm / Ask".
5. **Current, not remembered.** Questions are grounded in a dated landscape scan ("as of today"), per [`landscape-grounded-questions.md`](./landscape-grounded-questions.md).
6. **Cost is explicit.** Every run is projected and gated before spend.

## Design language (match these)

- **Theme:** Eigen editorial (warm), full dark support. Tokens: ground `#F4F1E7` / panel `#FDFBF5` / ink `#221D12` / gold `#8A6A1F` / hair `#DBD3BF`; register colors — fact `#2E6B4F`, intent/stated `#A5641E`, signal `#3F5E86`; P0 `#B23B3B`. (Dark values in the prototype `:root[data-theme="dark"]`.)
- **Type:** display/serif **Source Serif 4**; body **IBM Plex Sans**; labels/data/citations **IBM Plex Mono**.
- **Layout:** sticky top bar + a horizontal **stepper**; ≤900px collapses two-column → one; the evidence drawer stacks under the memo on mobile.

---

## Cross-references

- Backend contract & rebuild-vs-refactor rationale: the panel outputs (this session) + the endpoint map in `apps/api/thesis/routes.py`.
- Question currency: [`landscape-grounded-questions.md`](./landscape-grounded-questions.md).
- **Next:** a Phase 0 build spec (route, stack, API contract surface, the client-only contracts to preserve — the localStorage owner-token scheme, the `#thesis`/`#view/<id>/<token>`/`#board` hash shapes, run-gating, poll concurrency guards — and the component list to port).
