"""ResearchService — the runnable multi-source research agent.

Composes an LLM + embedder + a set of named RetrievalSources (corpus, web,
workspace, …) and answers a question over any chosen combination, with the
vertical's gating policy + persona driving the loop. This is what the API calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from eigen_kernel.contract.protocols import Connector, GatingPolicy, RetrievalSource
from eigen_kernel.providers.embeddings import Embedder
from eigen_kernel.providers.llm import LLMClient
from eigen_kernel.research.budget import BudgetState
from eigen_kernel.research.react import AnswerResult, run_react
from eigen_kernel.retrieval.multi import MultiSourceRetriever
from pydantic import BaseModel


class _PlainAnswer(BaseModel):
    text: str


_DERIVE_LABEL_UI = {"inference": "Inference", "hypothesis": "Hypothesis", "speculation": "💡 Idea"}


def _render_derivations(ds: list) -> str:
    """Render gated derivations as a compact, labeled 'Reasoning & ideas' section. Each line shows the
    epistemic label, the conclusion, the finding basis (auditable), and the falsifier when present."""
    lines = []
    for d in ds:
        label = _DERIVE_LABEL_UI.get(getattr(d, "label", ""), getattr(d, "label", ""))
        basis = ", ".join(str(b) for b in getattr(d, "basis", ()) or ())
        tail = f"  _(from {basis})_" if basis else ""
        fals = (getattr(d, "falsifier", "") or "").strip()
        if fals and getattr(d, "label", "") != "inference":
            tail += f" — wrong if: {fals}"
        lines.append(f"- **{label}:** {getattr(d, 'conclusion', '').strip()}{tail}")
    if not lines:
        return ""
    return ("## Reasoning & ideas\n"
            "_Derived from the findings above — each step is labeled by confidence, cites the findings "
            "it rests on, and says what would make it wrong._\n\n" + "\n".join(lines))


def build_history_context(history, *, answer_focus: bool = False) -> str | None:
    """Prior conversation turns → a compact context block (a follow-up can be elliptical). Context ONLY —
    it frames search/interpretation and NEVER becomes a citable claim. Shared by ask() and ask_panel() so
    both thread history identically. `history` is a list of {question, answer, claims?}."""
    if not history:
        return None
    turns = []
    for t in history:
        qy = (t.get("question") or "").strip()
        an = (t.get("answer") or "").strip()
        if not qy:
            continue
        block = f"Q: {qy}\nA: {an[:1200]}" if an else f"Q: {qy}"
        if answer_focus:   # EPISODIC MEMORY: surface prior structured findings so the loop builds on them
            cl = t.get("claims") or []
            estab = "; ".join((c.get("text") or "").strip()
                              for c in cl[:8] if isinstance(c, dict) and c.get("text"))
            if estab:
                block += f"\n[already established: {estab[:1000]}]"
        turns.append(block)
    return "\n\n".join(turns) or None


@dataclass
class FollowupResolution:
    """Structured resolution of a conversational follow-up (the Conversation-Manager output)."""
    core_query: str                     # the follow-up rewritten as a self-contained question
    subject: str = ""                   # the carried subject/entity (transparency)
    needs_clarification: bool = False   # the follow-up is genuinely ambiguous → ask, don't guess
    clarification: str = ""             # the clarifying question to put to the user
    operate_on_prior: bool = False      # transform the PREVIOUS answer (summarize/shorten/…), not new research


@dataclass
class ResearchService:
    llm: LLMClient
    embedder: Embedder
    sources: dict[str, RetrievalSource]
    planner_llm: LLMClient | None = None     # fast model for ReAct planning steps (compose uses llm)
    gating: GatingPolicy | None = None
    persona_prompt: str = "You are an evidence-grounded research agent."
    panel_selection_prompt: str | None = None  # vertical panel auto-selection chair prompt (opaque)
    answer_format: str | None = None        # vertical answer-structure directive (opaque, clinician)
    patient_answer_format: str | None = None # vertical PATIENT-audience compose directive (opaque)
    vision_prompt: str | None = None        # vertical image-description directive (opaque)
    report_prompt: str | None = None        # vertical NATIVE document-reading directive (opaque)
    layman_prompt: str | None = None        # vertical layman-rephrasing directive (opaque)
    gap_prompt: str | None = None           # vertical gap-fill-planner directive (opaque)
    suggest_prompt: str | None = None       # vertical suggested-follow-ups directive (opaque)
    terms_prompt: str | None = None         # vertical key-term-explanation directive (opaque)
    visuals_prompt: str | None = None        # vertical post-hoc answer-visualization directive (opaque)
    refine_prompt: str | None = None         # vertical pre-answer question-refinement directive (opaque)
    triage_prompt: str | None = None         # vertical guided-intake/triage directive (opaque)
    triage_prompt_v2: str | None = None      # vertical intake-v2 directive (opaque; None → v2 falls back to v1)
    reasoned_scaffold_prompt: str | None = None  # alternate-engine scaffold directive (coverage as QUESTIONS)
    reasoned_answer_format: str | None = None    # alternate-engine compose directive (decision-gated answer)
    integrative_prompt: str | None = None        # opt-in complementary/integrative answer-section directive
    integrative_query_hint: str | None = None    # retrieval-steering hint appended when the user opts in
    alt_directive: str | None = None             # Alternative-modality compose directive (CAM-centered + labeling)
    alt_query_hint: str | None = None            # retrieval-steering hint for Alternative mode
    understanding_answer_format: str | None = None  # UNDERSTANDING engine: causal-model compose contract
    understanding_query_hint: str | None = None     # UNDERSTANDING engine: mechanism-steering hint
    source_routing: bool = False                     # SOURCE ROUTING (flag EIGEN_SOURCE_ROUTING): let the
    #                                                 agent name source TYPES to ALSO target per query
    #                                                 (additive scoped leg, never a filter). False → off.
    retrieval_source_cap: float | None = None       # source-diversity cap (flag EIGEN_RETRIEVAL_DIVERSITY):
    #                                                 cap any one source_key to ceil(k*frac) of the top-k
    #                                                 fused pool so a volume-skewed source can't crowd out
    #                                                 others on broad queries. None → byte-identical.
    max_calls: int = 80                     # 40 → 80: stage-2 BudgetState-honesty re-plan — the
    #                                         claims-first/binding/fallback/frame-repair calls are
    #                                         now charged (see budget.py DEFAULT_MAX_LLM_CALLS)
    vertical_name: str = ""
    ui: object | None = None                # the vertical's UIContract (for /config)
    connectors: dict[str, Connector] = field(default_factory=dict)  # for /ingest
    corpus_source_key: str = ""             # the pg-backed corpus key (if any)
    aux_source_keys: tuple[str, ...] = ("web",)   # queried once/step (no variant fan-out) — e.g. web
    claims_first: bool = False              # run the comprehensive extraction pipeline (flag)
    extraction_lenses: tuple[str, ...] = () # vertical lenses for claims-first extraction
    evidence_select: bool = False           # rank claims by relevance before the cap + wider atom window (flag)
    atom_cap: int = 1600                    # per-atom char window for the extractor (raised under evidence_select)
    reasoning_read: bool = False            # surface the validated interpretation + confidence layer (flag)
    readable_prose: bool = False            # EIGEN_READABLE_PROSE: plain-language style over compose (flag)
    axis_complete: bool = False             # EIGEN_ANSWER_AXES: compose addresses each asked aspect + synthesizes
    tech_synthesis: bool = False            # EIGEN_TECH_SYNTHESIS: add a strategic 'how it works' technical synthesis
    derive: bool = False                   # EIGEN_DERIVE: gated, labeled derivations over verified claims
    derive_ideas: bool = False              # EIGEN_DERIVE_IDEAS: also generate grounded 'opportunity' ideas
    derive_judge_llm: object | None = None  # optional cross-family validity judge (else reuses self.llm)
    collect_diagnostics: bool = False       # capture a troubleshooting trace (turns/tools/retries/failures) (flag)
    classify_evidence: object | None = None # vertical structural evidence-tier classifier (source_key, facets) -> kind
    evidence_fitness: bool = False          # boost stronger evidence tiers into the compose cap (flag)
    evidence_ranker: object | None = None   # vertical authority pyramid: evidence_kind -> int rank
    freshness: dict | None = None           # vertical freshness policy {min_rank,weight,horizon_years}
    #                                         (flag EIGEN_FRESHNESS_RANKING): recency re-order + as-of
    #                                         disclosure. None → byte-identical to today.
    answer_profiles: dict | None = None     # ANSWER-CONTRACT (flag EIGEN_ANSWER_CONTRACT): {stance:
    #                                         profile} — one classification customizes retrieval+
    #                                         ranking+compose per question. None → byte-identical.
    evidence_identity: bool = False         # render each atom's document identity ⟨title — source⟩ on
    #                                         every LLM-visible surface (Evidence Contract stage 1, flag)
    claim_congruence: bool = False          # unified batched BINDING judge over loop/claims-first/
    #                                         fallback claims: {entailed, on_subject, kind_ok} per
    #                                         claim (Evidence Contract stage 2, flag)
    question_contract: str = ""             # Evidence Contract stage 3 (flag MODE): "" off;
    #                                         "shadow" → derive + log the QuestionContract/legs,
    #                                         change nothing; "steer" → per-entity legs late-merged
    #                                         + slot-aware compose selection + loop coverage gaps
    contract_prompt: str | None = None      # vertical QuestionContract derivation directive
    #                                         (opaque — ALL domain vocabulary lives in the vertical)
    explore_legs: bool = False              # exploratory-legs extension (flag): EXPLORATORY
    #                                         contracts' axes become axis-only retrieval legs
    #                                         (cap 4, steer-gated, late-merged); OFF → exploratory
    #                                         behavior byte-identical to today
    answer_mode_routing: bool = False       # Evidence Contract stage 4 (flag): append the vertical's
    #                                         enumerative-compose addendum when the derived contract
    #                                         is enumerative AND ≥2 entities hold slot-matched claims
    enumerative_compose_addendum: str | None = None  # vertical enumerative-compose addendum (opaque)
    graph_expander: object | None = None    # A9: async (question) -> {"legs":[{query,note}],"shadow":bool}|None
    #                                         — app-injected relationship-graph hook; None → byte-identical
    panel_specialists: tuple = ()           # Ask-Panel roster (vertical-supplied specialist configs)
    panel_default_ids: tuple = ()           # ids the default panel runs
    panel_synthesis_directive: str | None = None
    panel_examples: tuple = ()              # sample multi-specialty cases seeded into the panel intake
    panel_dedup: bool = False               # P2 (flag): dedup pooled panel claims by (atom_id,
    #                                         normalized quote); survivors carry lens_count + names
    panel_contract: bool = False            # P3+P1 (flag): ONE shared QuestionContract per panel run
    #                                         (+1 call) → scoped lens coverage, pooled slot-matching,
    #                                         panel coverage_gaps, decision-synthesis routing
    panel_enumerative_addendum: str | None = None  # vertical panel enumerative addendum (opaque)
    panel_decision_addendum: str | None = None     # vertical panel decision-grid addendum (opaque)

    def _retriever(self, source_keys: list[str] | None) -> MultiSourceRetriever:
        chosen = {k: v for k, v in self.sources.items()
                  if source_keys is None or k in source_keys} or self.sources
        return MultiSourceRetriever(chosen)

    def _split_retriever(self, source_keys, extra_sources: dict | None = None):
        """Corpus (vector, multi-query) and AUX (web, single-query per step) retrievers. Web is
        split out so it's queried ONCE per step on the original query — not fanned out per
        reformulation — which keeps web latency bounded while still adding breadth.
        `extra_sources` are PER-REQUEST additions (e.g. the user's uploaded report as a citable
        in-memory source) — merged into the corpus leg, never into the shared service dict."""
        chosen = {k: v for k, v in self.sources.items()
                  if source_keys is None or k in source_keys} or self.sources
        chosen = {**chosen, **(extra_sources or {})}
        aux = {k: v for k, v in chosen.items() if k in self.aux_source_keys}
        corpus = {k: v for k, v in chosen.items() if k not in self.aux_source_keys}
        if not corpus:                       # web-only selection → treat it as the primary source
            return MultiSourceRetriever(chosen), None
        return MultiSourceRetriever(corpus), (MultiSourceRetriever(aux) if aux else None)

    async def ask_reasoned(self, route: bool = True, force_kind: str | None = None, **kw):
        """REASONED engine with DYNAMIC per-question routing. The single scaffold call does double duty
        (zero extra LLM calls): it first CLASSIFIES the question — management/case (differential, workup,
        treatment choice) vs pure evidence LOOKUP (trial results, pharmacokinetics, definitions) — then:
          - management → coverage scaffold (QUESTIONS only, never conclusions — grounding-safe) steers
            retrieval + the decision-gated compose directive;
          - lookup → falls through to the STANDARD adaptive engine (a decision frame is the wrong shape
            for an evidence summary).
        `route=False` (the duel's explicit "reasoned" arm) FORCES the reasoned pipeline so A/B contrast
        stays honest. Follow-ups run the standard adaptive compose (narrower asks; the scaffold's brief
        would interfere with follow-up resolution). Fail-open everywhere — errors → reasoned-no-brief."""
        if not (self.reasoned_scaffold_prompt and self.reasoned_answer_format):
            return await self.ask(**kw)
        if force_kind == "understanding" and self.understanding_answer_format:
            # EXPLICIT hop to the understanding engine (interlock chip) — no classification needed;
            # works mid-thread too (the causal lens on the same question).
            kw = dict(kw)
            if self.understanding_query_hint:
                kw["graph_question"] = kw.get("question", "")
                kw["question"] = (kw.get("question", "") + "\n\n[" + self.understanding_query_hint + "]")
            kw["answer_format_override"] = self.understanding_answer_format
            oe = kw.get("on_event")
            if oe is not None:
                try:
                    await oe({"type": "engine", "engine": "understanding", "why": "user-selected"})
                except Exception:
                    pass
            return await self.ask(**kw)
        # History counts as a CONVERSATION only if some prior turn was actually ANSWERED — a thread of
        # error/retry turns is a fresh question (else a retry-after-failure silently demoted the engine
        # to the standard format: the "where did Do-now go?" bug).
        _hist = kw.get("history") or []
        if any((t.get("answer") or "").strip() for t in _hist if isinstance(t, dict)):
            if not route:   # explicitly forced reasoned (duel arm / hop chip) → keep the decision-gated format
                kw = dict(kw)
                kw["answer_format_override"] = self.reasoned_answer_format
            return await self.ask(**kw)
        question = kw.get("question", "")
        on_event = kw.get("on_event")
        from typing import Literal
        from pydantic import BaseModel, Field

        class _Scaffold(BaseModel):
            # kind = the routing judgment (LLM-owned, Rule 18). Lists are QUESTIONS/topics to cover.
            kind: Literal["management", "lookup", "understanding"] = "management"
            likely_causes: list[str] = Field(default_factory=list)
            cant_miss: list[str] = Field(default_factory=list)
            key_decisions: list[str] = Field(default_factory=list)
            explicit_asks: list[str] = Field(default_factory=list)   # the audit contract: what was literally asked

        async def _emit(ev):
            if on_event is not None:
                try:
                    await on_event(ev)
                except Exception:
                    pass
        try:
            comp = await self.llm.complete(
                system=self.reasoned_scaffold_prompt,
                messages=[{"role": "user", "content": question}],
                response_format=_Scaffold, max_tokens=1200)
            s = comp.parsed
            if route and s.kind == "lookup":
                # pure evidence lookup → the standard adaptive engine fits better; say so in the trace
                await _emit({"type": "engine", "engine": "standard", "why": "evidence lookup"})
                return await self.ask(**kw)
            if route and s.kind == "understanding" and self.understanding_answer_format:
                # WHY/HOW question → the UNDERSTANDING engine: mechanism-steered retrieval + the
                # causal-model compose contract (per-link evidence-status labels)
                kw = dict(kw)
                if self.understanding_query_hint:
                    kw["graph_question"] = question
                    kw["question"] = question + "\n\n[" + self.understanding_query_hint + "]"
                kw["answer_format_override"] = self.understanding_answer_format
                await _emit({"type": "engine", "engine": "understanding", "why": "why/how question"})
                return await self.ask(**kw)
            lines = ([f"- explicitly asked: {x}" for x in s.explicit_asks[:8]]
                     + [f"- likely/common: {x}" for x in s.likely_causes[:6]]
                     + [f"- can't-miss: {x}" for x in s.cant_miss[:6]]
                     + [f"- decision: {x}" for x in s.key_decisions[:6]])
            if lines:
                kw = dict(kw)
                kw["graph_question"] = question     # expander anchors on the ASKED subject, not brief branches
                kw["question"] = (question + "\n\n[Coverage brief — branches this answer must "
                                  "INVESTIGATE and address (these are questions to research, not facts):\n"
                                  + "\n".join(lines) + "\n]")
                await _emit({"type": "engine", "engine": "reasoned", "why": "management question"})
                await _emit({"type": "scaffold", "branches": len(lines)})
        except Exception:   # noqa: BLE001 — scaffold is an enhancer; its failure never blocks the answer
            pass
        kw["answer_format_override"] = self.reasoned_answer_format
        return await self.ask(**kw)

    async def ask(
        self,
        *,
        question: str,
        tenant_id: str,
        workspace_id: str | None = None,
        source_keys: list[str] | None = None,
        images: list[dict] | None = None,
        documents: list[dict] | None = None,
        pdf_docs: list[dict] | None = None,  # raw PDFs → NATIVE model reading (layout-faithful digests)
        history: list[dict] | None = None,
        on_event=None,                       # async callback(dict) for live progress (SSE)
        facets: dict | None = None,          # hard retrieval facet filter (e.g. source_country scope)
        exclude_facets: dict | None = None,  # EXCLUSION filter (e.g. keep modality=alternative out of default)
        country_boost=None,                  # set of country codes to BOOST (surface region evidence, no filter)
        max_steps: int = 8,
        effort: float = 1.0,                 # research-effort multiplier (1.0 = baseline no-op)
        audience: str = "clinician",         # "clinician" (default) | "patient" — selects the compose directive ONLY
        answer_focus: bool = False,          # condense elliptical follow-ups + ANSWER-scope compose (flag)
        clarify: bool = False,               # ask a clarifying question when a follow-up is ambiguous (flag)
        answer_format_override: str | None = None,   # per-call compose directive (alternate engine); None → default
        extra_directive: str | None = None,          # per-call ADDENDUM appended to the selected directive
        suppress_authority: bool = False,            # per-call: neutralize the authority tier-boost in
        #                                              ranking (a use-case lens for opinion/foresight
        #                                              queries, so expert/discussion evidence isn't
        #                                              demoted below filings). False → today's behavior.
        graph_question: str | None = None,   # PRISTINE user question for the graph expander — callers
        #                                      that augment `question` (reasoned coverage brief, engine
        #                                      hints) MUST pass the original here, or topic matching
        #                                      anchors on brief-mentioned branches instead of the asked
        #                                      subject (the Parkinson-leg prod bug)
        question_context: str | None = None, # caller-supplied PLANNER-ONLY framing (e.g. a vertical's
        #                                      structural brand→generic mapping, Noesis IN D-3) — rides
        #                                      the attachment-context channel, so it frames search and
        #                                      NEVER reaches compose or becomes citable
    ) -> AnswerResult:
        # ANSWER-FOCUS (flag): resolve a conversational FOLLOW-UP ("what dose?") into a self-contained
        # question carrying the subject from the conversation ("dose of TMP-SMX for PCP prophylaxis"),
        # BEFORE retrieval — so the query, the relevance ranking, AND compose all inherit the subject
        # (they all key off `question`). Only fires with history present; off/no-history → no-op. The
        # resolver sees ONLY the conversation (never the corpus), so it can't inject retrieved content;
        # the ORIGINAL question is preserved as `question_original` for echo/persistence. With `clarify`,
        # a genuinely ambiguous follow-up short-circuits into a clarifying question (no research run).
        question_original = question
        resolved_question = ""
        if answer_focus and history:
            r = await self._resolve_followup(question, history, allow_clarify=clarify)
            # OPERATE-ON-PRIOR (#5): "summarize that / shorten / explain point 2" → transform the
            # previous answer with NO new retrieval (adds no new facts). Fall through to normal
            # research if there's no prior answer or the transform fails.
            if r.operate_on_prior:
                prior = next((t.get("answer") for t in reversed(history)
                              if (t.get("answer") or "").strip()), "")
                if prior:
                    transformed = await self._transform_prior(question, prior)
                    if transformed:
                        if on_event is not None:
                            try:
                                await on_event({"type": "operate_prior"})
                            except Exception:
                                pass
                        out = AnswerResult(stopped_reason="operate_prior")
                        out.composed_answer = transformed
                        out.derived_from_prior = True
                        return out
            if r.needs_clarification and r.clarification:
                if on_event is not None:
                    try:
                        await on_event({"type": "clarify", "question": r.clarification})
                    except Exception:
                        pass
                out = AnswerResult(stopped_reason="clarify")
                out.clarification = r.clarification   # ask the user; skip the research run entirely
                return out
            if r.core_query and r.core_query != question:
                resolved_question = r.core_query
                question = r.core_query
                if on_event is not None:
                    try:
                        await on_event({"type": "resolved_question", "question": question})
                    except Exception:
                        pass
        # Audience changes ONLY the compose directive — same retrieval, same persona/system_prompt,
        # same span/entailment gates. "patient" uses the vertical's patient directive when it supplies
        # one; anything else (incl. an unknown value) falls back to the clinician directive → the
        # default path is byte-identical.
        if audience == "patient" and self.patient_answer_format:
            directive = self.patient_answer_format     # patient view always wins (per-audience contract)
        else:
            directive = answer_format_override or self.answer_format
        if extra_directive:   # opt-in addendum (e.g. integrative section) — appended to WHICHEVER directive won
            directive = (directive + "\n\n" + extra_directive) if directive else extra_directive
        # Effort scales STRUCTURAL search knobs only (turns, results, context, citations, budget) —
        # never the grounding gates. At effort<=1.0 every value round-trips to today's exact defaults,
        # so this is a byte-identical no-op when the caller passes 1.0 (flag OFF).
        from eigen_kernel.research.effort import scale_research_effort
        sc = scale_research_effort(
            effort, base_max_steps=max_steps, base_atom_cap=self.atom_cap, base_max_calls=self.max_calls)
        budget = BudgetState(max_calls=sc.max_calls)
        # Attachment context (never corpus evidence, never a verified claim):
        #  - images/scans → a labeled DESCRIPTIVE vision observation (vision pre-step),
        #  - uploaded documents (e.g. a paper PDF) → their extracted TEXT.
        # Both are combined into attachment_context that only frames the search.
        visual_obs = ""
        if images and self.vision_prompt:
            from eigen_kernel.research.vision import observe_images
            try:
                visual_obs = await observe_images(
                    llm=self.llm, vision_prompt=self.vision_prompt,
                    images=images, budget=budget)
            except Exception:
                visual_obs = ""             # a failed vision read must not break research
        parts: list[str] = []
        att_texts: list[tuple[str, str]] = []   # (name, text) → per-request CITABLE attachment source
        if visual_obs:
            parts.append("IMAGE (automated visual description):\n" + visual_obs)
        # NATIVE PDF reading: the model sees the original file (page layout intact), so report
        # tables keep their analyte/value/unit/range associations — the fix for scrambled
        # text-layer extraction on lab reports. Falls back to the text layer per document.
        if pdf_docs and self.report_prompt:
            from eigen_kernel.research.vision import read_documents
            try:
                reads = await read_documents(llm=self.llm, report_prompt=self.report_prompt,
                                             pdfs=pdf_docs, budget=budget)
            except Exception:   # noqa: BLE001
                reads = []
            read_names = {r["name"] for r in reads}
            for r in reads:
                parts.append(f"DOCUMENT — {r['name']} (structured digest, read natively from the file):\n{r['digest']}")
                att_texts.append((r["name"], r["digest"]))
            for pdf in pdf_docs:
                fb = (pdf.get("text_fallback") or "").strip()
                if pdf.get("name") not in read_names and fb:
                    parts.append(f"DOCUMENT — {pdf.get('name') or 'document'} (text-layer extraction):\n{fb[:20000]}")
                    att_texts.append((pdf.get("name") or "document", fb[:20000]))
        elif pdf_docs:
            for pdf in pdf_docs:
                fb = (pdf.get("text_fallback") or "").strip()
                if fb:
                    parts.append(f"DOCUMENT — {pdf.get('name') or 'document'} (text-layer extraction):\n{fb[:20000]}")
                    att_texts.append((pdf.get("name") or "document", fb[:20000]))
        for d in documents or []:
            txt = (d.get("text") or "").strip()
            if txt:
                name = d.get("name") or "document"
                parts.append(f"DOCUMENT — {name} (user-provided text):\n{txt}")
                att_texts.append((name, txt))
        if question_context:
            parts.append(question_context.strip())
        attachment_context = "\n\n".join(parts) or None

        # Prior conversation turns → a compact context block (a follow-up can be elliptical). This
        # only frames search/interpretation; it never becomes a grounded claim (like attachments).
        history_context = build_history_context(history, answer_focus=answer_focus)

        # THE ATTACHMENT AS A CITABLE SOURCE: for "analyze this report" questions the user's
        # document IS the primary content — its digest/text becomes a per-request in-memory
        # retrieval source, so claims can CITE the report with span-verified quotes (clearly
        # labeled "(user upload)"), while the corpus supplies the interpretive evidence.
        att_source = None
        if att_texts:
            import asyncio as _aio
            from eigen_kernel.contract.dto import Locator as _Loc
            from eigen_kernel.ingestion.storage import content_key as _ck
            from eigen_kernel.retrieval.memory import IndexedBlock, InMemoryRetrievalSource
            from eigen_kernel.retrieval.web import _chunk_text as _chunk
            chunks: list[tuple[str, str]] = []
            for _nm, _txt in att_texts:
                for _c in _chunk(_txt, max_chars=900)[:40]:
                    chunks.append((_nm, _c))
            if chunks:
                _embs = await _aio.to_thread(lambda: self.embedder.embed([c for _, c in chunks]))
                att_source = InMemoryRetrievalSource()
                att_source.key = "attachment"
                for (_nm, _c), _e in zip(chunks, _embs):
                    _bid = _ck(f"attachment:{_nm}|{_c}".encode())
                    _did = f"attachment:{_nm}"
                    att_source.add(IndexedBlock(
                        block_id=_bid, document_id=_did, text=_c, tenant_id=tenant_id,
                        embedding=tuple(_e), facets={"source_kind": "user_attachment"},
                        locator=_Loc("block_span", _did, {"block_id": _bid}),
                        document_title=f"{_nm} (user upload)", content_type="text/plain",
                        source_key="attachment"))
        if att_texts:
            # COMPLETENESS HINT (attachment-triggered, per-request — the validated compose
            # directive is untouched): an "analyze this" over a document means ALL of it.
            question = (question + "\n\n[The user attached document(s). Analyze them COMPLETELY: "
                        "address EVERY section/panel the document digest lists (see SECTIONS "
                        "PRESENT), searching for interpretive evidence per section — partially "
                        "analyzing an attached report is a failure.]")
        corpus_src, web_src = self._split_retriever(
            source_keys, extra_sources={"attachment": att_source} if att_source else None)
        # A9 graph-guided evidence legs (app-injected hook; best-effort — a graph failure never
        # delays or breaks the answer path). The hook decides legs AND mode (shadow vs merged).
        graph_legs, graph_shadow, graph_late = None, False, False
        if self.graph_expander is not None:
            try:
                # anchor topic matching on the ASKED subject: explicit pristine question from the
                # caller, else the follow-up-resolved question, else what ask() received —
                # never the augmented `question` (brief/hints name branch topics, not the subject)
                _gx = await self.graph_expander(
                    graph_question or resolved_question or question_original)
                if _gx and _gx.get("legs"):
                    graph_legs = list(_gx["legs"])
                    graph_shadow = bool(_gx.get("shadow"))
                    graph_late = bool(_gx.get("late"))
            except Exception:   # noqa: BLE001
                graph_legs = None
        res = await run_react(
            question=question, llm=self.llm, embedder=self.embedder,
            source=corpus_src, aux_source=web_src,
            tenant_id=tenant_id, workspace_id=workspace_id,
            budget=budget, gating=self.gating,
            system_prompt=self.persona_prompt, answer_format=directive,
            attachment_context=attachment_context, history_context=history_context,
            planner_llm=self.planner_llm, on_event=on_event,
            claims_first=self.claims_first, extraction_lenses=self.extraction_lenses,
            evidence_select=self.evidence_select, atom_cap=sc.atom_cap,
            facets=facets or {}, exclude_facets=exclude_facets or {},
            max_steps=sc.max_steps, k=sc.k, planner_atom_window=sc.planner_atom_window,
            compose_claim_cap=sc.compose_claim_cap, extract_collect=sc.extract_collect,
            answer_focus=answer_focus, reasoning_read=self.reasoning_read,
            readable_prose=self.readable_prose, country_boost=country_boost,
            axis_complete=self.axis_complete, tech_synthesis=self.tech_synthesis,
            collect_diagnostics=self.collect_diagnostics,
            classify_evidence=self.classify_evidence,
            evidence_fitness=self.evidence_fitness, evidence_ranker=self.evidence_ranker,
            retrieval_source_cap=self.retrieval_source_cap, suppress_authority=suppress_authority,
            source_routing=self.source_routing,
            freshness=self.freshness, answer_profiles=self.answer_profiles,
            evidence_identity=self.evidence_identity, claim_congruence=self.claim_congruence,
            question_contract=self.question_contract, contract_prompt=self.contract_prompt,
            explore_legs=self.explore_legs,
            answer_mode_routing=self.answer_mode_routing,
            enumerative_compose_addendum=self.enumerative_compose_addendum,
            graph_legs=graph_legs, graph_shadow=graph_shadow, graph_late=graph_late,
        )
        res.visual_observation = visual_obs      # surface the image reading (UI panel)
        res.effort = sc.effort                   # echo the resolved multiplier (observability)
        res.resolved_question = resolved_question # condensed question if it differed (observability)

        # GROUNDED REASONING (flag): derive labeled, checked conclusions FROM the verified findings —
        # a second trust regime on top of the fact gate. Additive: adds no fact, only reasons over the
        # findings run_react already verified; a failure never breaks the answer.
        if self.derive and getattr(res, "verified_claims", None):
            try:
                from eigen_kernel.research.reason import derive as _derive
                ds = await _derive(
                    resolved_question or question, res.verified_claims, self.llm,
                    generate_ideas=self.derive_ideas, judge_llm=self.derive_judge_llm)
                res.derivations = ds
                section = _render_derivations(ds)
                if section:
                    res.composed_answer = (res.composed_answer or "").rstrip() + "\n\n" + section
            except Exception:   # noqa: BLE001 — reasoning is additive; never sink the grounded answer
                pass
        return res

    def panel_roster(self) -> list[dict]:
        """The available specialists + their lens/expertise (for the UI roster view)."""
        return [{"id": getattr(s, "id", ""), "specialty": getattr(s, "specialty", ""),
                 "lens": getattr(s, "lens", ""), "focus": getattr(s, "focus", ""),
                 "default": getattr(s, "id", "") in set(self.panel_default_ids)}
                for s in self.panel_specialists]

    async def plan_panel(self, *, question: str) -> dict:
        """Phase 1: auto-select the specialists for this case (LLM triage) + return the full roster so
        the UI can show the proposed panel and let the user adjust. Fail-safe → the default set."""
        from eigen_kernel.research.panel import plan_panel as _plan
        roster = self.panel_roster()
        selected = await _plan(question=question, roster=roster, llm=self.llm,
                               selection_prompt=self.panel_selection_prompt) if roster else []
        if not selected:   # triage empty/failed → default set (never leave the panel empty)
            by_id = {r["id"]: r for r in roster}
            selected = [{"id": i, "specialty": by_id[i]["specialty"],
                         "rationale": "core panel lens"} for i in self.panel_default_ids if i in by_id]
        return {"selected": selected, "roster": roster}

    async def ask_panel(self, *, question: str, tenant_id: str, workspace_id: str | None = None,
                        specialist_ids: list[str] | None = None, source_keys: list[str] | None = None,
                        history: list[dict] | None = None, rationales: dict | None = None,
                        images: list[dict] | None = None,
        pdf_docs: list[dict] | None = None, documents: list[dict] | None = None, on_event=None):
        """Ask-Panel (Alpha): run the selected specialists (or the default set) as parallel grounded
        loops and synthesize their pooled findings. Provides the domain-free orchestrator with a
        source-scoping callback so each specialist can prefer its own sources. `history` threads in as
        context for a follow-up; `images`/`documents` (uploaded attachments) are read ONCE (vision +
        document text) and shared as context across all specialists — same contract as ask()."""
        from eigen_kernel.research.panel import run_panel
        roster = {getattr(s, "id", ""): s for s in self.panel_specialists}
        ids = [i for i in (specialist_ids or list(self.panel_default_ids)) if i in roster]
        specialists = [roster[i] for i in ids] or list(self.panel_specialists)
        # ATTACHMENT CONTEXT (parity with ask()): describe images ONCE + gather document text, then share
        # that context with every specialist (never re-describe per lens; never a citable finding).
        visual_obs = ""
        if images and self.vision_prompt:
            from eigen_kernel.research.vision import observe_images
            try:
                visual_obs = await observe_images(llm=self.llm, vision_prompt=self.vision_prompt,
                                                  images=images, budget=BudgetState(max_calls=4))
            except Exception:   # noqa: BLE001 — a failed vision read must not break the panel
                visual_obs = ""
        _parts = []
        if visual_obs:
            _parts.append("IMAGE (automated visual description):\n" + visual_obs)
        if pdf_docs and self.report_prompt:
            from eigen_kernel.research.vision import read_documents
            try:
                _reads = await read_documents(llm=self.llm, report_prompt=self.report_prompt,
                                              pdfs=pdf_docs, budget=BudgetState(max_calls=4))
            except Exception:   # noqa: BLE001
                _reads = []
            _rn = {r["name"] for r in _reads}
            for r in _reads:
                _parts.append(f"DOCUMENT — {r['name']} (structured digest, read natively from the file):\n{r['digest']}")
            for pdf in pdf_docs:
                fb = (pdf.get("text_fallback") or "").strip()
                if pdf.get("name") not in _rn and fb:
                    _parts.append(f"DOCUMENT — {pdf.get('name') or 'document'} (text-layer extraction):\n{fb[:20000]}")
        elif pdf_docs:
            for pdf in pdf_docs:
                fb = (pdf.get("text_fallback") or "").strip()
                if fb:
                    _parts.append(f"DOCUMENT — {pdf.get('name') or 'document'} (text-layer extraction):\n{fb[:20000]}")
        for d in documents or []:
            txt = (d.get("text") or "").strip()
            if txt:
                _parts.append(f"DOCUMENT — {d.get('name') or 'document'} (user-provided text):\n{txt}")
        attachment_context = "\n\n".join(_parts)
        if visual_obs and on_event is not None:
            try:
                await on_event({"type": "visual_observation", "text": visual_obs})
            except Exception:   # noqa: BLE001
                pass
        # FOLLOW-UP RESOLUTION (same as ask()): rewrite an elliptical follow-up ("what if they also have
        # gout?") into a SELF-CONTAINED question carrying the case subject, BEFORE the specialists run — so
        # every specialist's retrieval + reasoning inherits the full context, not just a raw fragment.
        if history:
            try:
                r = await self._resolve_followup(question, history, allow_clarify=False)
                if r and r.core_query and r.core_query != question:
                    question = r.core_query
                    if on_event is not None:
                        try:
                            await on_event({"type": "resolved_question", "question": question})
                        except Exception:   # noqa: BLE001
                            pass
            except Exception as e:   # noqa: BLE001 — fail-safe: keep the original follow-up
                import logging
                logging.getLogger(__name__).warning("panel follow-up resolution failed: %r", e)
        # episodic memory on: a follow-up should build on findings the panel already established
        history_context = build_history_context(history, answer_focus=True) or ""

        def make_retrievers(spec_source_keys):
            # a specialist's preferred sources ∩ the request's chosen sources (None = all)
            keys = spec_source_keys if spec_source_keys else source_keys
            return self._split_retriever(keys)

        return await run_panel(
            question=question, specialists=specialists, llm=self.llm, embedder=self.embedder,
            make_retrievers=make_retrievers, tenant_id=tenant_id, workspace_id=workspace_id,
            synthesis_directive=self.panel_synthesis_directive or "", history_context=history_context,
            attachment_context=attachment_context, rationales=rationales, chair_system_prompt=self.persona_prompt,
            classify_evidence=self.classify_evidence, evidence_ranker=self.evidence_ranker,
            evidence_fitness=self.evidence_fitness, evidence_identity=self.evidence_identity,
            claim_congruence=self.claim_congruence,
            panel_dedup=self.panel_dedup, panel_contract=self.panel_contract,
            contract_prompt=self.contract_prompt,
            panel_enumerative_addendum=self.panel_enumerative_addendum,
            panel_decision_addendum=self.panel_decision_addendum,
            on_event=on_event)

    async def _resolve_followup(self, question: str, history: list[dict],
                                *, allow_clarify: bool) -> "FollowupResolution":
        """Resolve a conversational FOLLOW-UP against the conversation in ONE structured LLM call
        (factra's Conversation-Manager pattern). Returns a FollowupResolution with:
          - core_query: the follow-up rewritten as a SELF-CONTAINED question (subject made explicit);
          - subject: the carried subject/entity (transparency + future gating);
          - needs_clarification + clarification: when the follow-up is genuinely ambiguous or has
            multiple plausible subjects (only honored when allow_clarify) — ask, don't guess.
        Sees ONLY the conversation (never the corpus), so it can inject no retrieved content —
        resolving the referent is a coreference judgment, the LLM's job (Rule 18). Fail-safe: any
        error → the original question, no clarification (never worse than today)."""
        from pydantic import BaseModel

        class _Resolution(BaseModel):
            core_query: str
            subject: str = ""
            needs_clarification: bool = False
            clarification: str = ""
            operate_on_prior: bool = False

        convo = []
        for t in (history or []):
            qy = (t.get("question") or "").strip()
            an = (t.get("answer") or "").strip()
            if qy:
                convo.append(f"Q: {qy}\nA: {an[:800]}" if an else f"Q: {qy}")
        if not convo:
            return FollowupResolution(core_query=question)
        clause = (
            " (4) If the follow-up is genuinely AMBIGUOUS — the subject is unclear OR there are MULTIPLE "
            "plausible subjects it could refer to — set needs_clarification=true and put ONE short, "
            "specific clarifying question in `clarification` (naming the candidate options), and set "
            "core_query to your best-guess standalone question anyway."
            if allow_clarify else
            " (4) Do NOT ask for clarification; always return your best-guess standalone core_query.")
        sys = ("You resolve a user's LATEST question in a medical research chat into a single, "
               "SELF-CONTAINED question, using the prior conversation to fill in the subject the latest "
               "question leaves implicit. You never add facts — you only make the question standalone.")
        user = (
            "CONVERSATION SO FAR:\n" + "\n\n".join(convo) + "\n\n"
            f"LATEST QUESTION: {question}\n\n"
            "Set core_query to LATEST QUESTION rewritten as ONE standalone question naming its subject "
            "explicitly (e.g. 'What dose?' after establishing co-trimoxazole for PCP prophylaxis → "
            "'What is the dose of co-trimoxazole for Pneumocystis pneumonia prophylaxis?'), and `subject` "
            "to the carried subject/entity. RULES: (1) If LATEST QUESTION is ALREADY self-contained, set "
            "core_query to it VERBATIM. (2) If it CHANGES the topic (a new subject), set core_query "
            "VERBATIM — do not graft on the old subject. (3) Carry ONLY the subject the latest question is "
            "implicitly about; do NOT add facts, answers, doses, or details from the prior answers. "
            "(3b) DO carry any patient CONSTRAINT the conversation established that still applies — age/"
            "pediatric/elderly, pregnancy, renal or hepatic impairment, an allergy, a comorbidity — into "
            "core_query (e.g. after 'in a patient with renal impairment', a later 'what about the dose?' → "
            "'... dose ... in a patient with renal impairment'), unless the latest question overrides it. "
            "(5) If LATEST QUESTION asks to TRANSFORM the PREVIOUS answer itself rather than seek new "
            "information — e.g. 'summarize that', 'shorten it', 'explain the second point', 'put it in a "
            "table', 'in one sentence' — set operate_on_prior=true (and core_query VERBATIM)."
            + clause)
        planner = self.planner_llm or self.llm
        try:
            res = await planner.complete(system=sys, messages=[{"role": "user", "content": user}],
                                         response_format=_Resolution, max_tokens=800)
            r = res.parsed
            cq = (r.core_query or "").strip()
        except Exception:
            return FollowupResolution(core_query=question)   # fail-safe → original
        # Structural guards (code owns structure): drop an empty/runaway rewrite back to the original.
        if not cq or len(cq) > max(160, 5 * len(question)):
            cq = question
        clar = (r.clarification or "").strip()
        return FollowupResolution(
            core_query=cq, subject=(r.subject or "").strip(),
            needs_clarification=bool(allow_clarify and r.needs_clarification and clar),
            clarification=clar if (allow_clarify and r.needs_clarification) else "",
            operate_on_prior=bool(r.operate_on_prior))

    async def _transform_prior(self, request: str, prior_answer: str) -> str:
        """Apply a user's TRANSFORM request ('summarize that', 'shorten', 'explain point 2', 'as a
        table') to the PREVIOUS answer, adding NO new facts. The prior answer was already grounded;
        this only reshapes it, so it is provenance-safe by construction (no retrieval, no new claims).
        Returns "" on failure → the caller falls back to normal research."""
        sys = ("You reshape a previous answer per the user's request. Use ONLY information already in "
               "the previous answer — add NO new facts, numbers, drugs, or claims. If the request asks "
               "for something not in the previous answer, say that briefly rather than inventing it.")
        user = (f"PREVIOUS ANSWER:\n{prior_answer[:6000]}\n\n"
                f"USER REQUEST: {request}\n\n"
                "Produce the reshaped answer as clean prose (no [n] citation markers — the sources are "
                "shown with the previous answer).")
        try:
            comp = await self.llm.complete(system=sys, messages=[{"role": "user", "content": user}],
                                           response_format=_PlainAnswer,
                                           max_tokens=min(8000, max(2000, len(prior_answer) // 2)))
            return (comp.parsed.text or "").strip()
        except Exception:
            return ""

    async def explain(self, *, question: str, answer: str) -> str:
        """On-demand plain-language rephrasing of a grounded answer (adds no new facts)."""
        if not self.layman_prompt:
            return ""
        from eigen_kernel.research.explain import explain_for_layperson
        return await explain_for_layperson(
            llm=self.llm, layman_prompt=self.layman_prompt, question=question, answer=answer)

    async def plan_gaps(self, *, question: str, answer: str, coverage_gaps: list[str]):
        """On-demand plan of what to ADD to the corpus so an under-evidenced question could be
        answered — actionable ingest jobs (over THIS deployment's connectors) + gold-source
        recommendations. Returns None when gap-healing isn't configured for the vertical."""
        if not self.gap_prompt or not self.connectors:
            return None
        from eigen_kernel.research.gap_planner import plan_gap_fill
        return await plan_gap_fill(
            llm=self.llm, gap_prompt=self.gap_prompt, question=question, answer=answer,
            coverage_gaps=coverage_gaps, available_connectors=list(self.connectors.keys()))

    async def suggest(self, *, question: str, answer: str, history: str = "") -> list[str]:
        """On-demand suggested follow-up questions that deepen discovery. [] when unavailable."""
        if not self.suggest_prompt:
            return []
        from eigen_kernel.research.suggest import suggest_followups
        return await suggest_followups(
            llm=self.llm, suggest_prompt=self.suggest_prompt,
            question=question, answer=answer, history=history)

    async def explain_terms(self, *, question: str, answer: str) -> list:
        """On-demand key-term explanations for an answer (definitional, with related-term
        edges for the vocabulary web). [] when the vertical supplies no terms directive."""
        if not self.terms_prompt:
            return []
        from eigen_kernel.research.terms import explain_key_terms
        return await explain_key_terms(
            llm=self.llm, terms_prompt=self.terms_prompt, question=question, answer=answer)

    async def visualize(self, *, question: str, answer: str) -> list:
        """On-demand conceptual visuals (flow/tree/timeline) restructuring a grounded answer, every
        element quote-anchored to the answer. [] when the vertical supplies no visuals directive or
        nothing qualifies."""
        if not self.visuals_prompt:
            return []
        from eigen_kernel.research.visuals import visualize_answer
        return await visualize_answer(
            llm=self.llm, visuals_prompt=self.visuals_prompt, question=question, answer=answer)

    async def explain_term(self, *, term: str, context: str = ""):
        """On-demand single-term explanation (glossary navigation). None when unavailable."""
        if not self.terms_prompt:
            return None
        from eigen_kernel.research.terms import explain_single_term
        return await explain_single_term(
            llm=self.llm, terms_prompt=self.terms_prompt, term=term, context=context)

    async def triage(self, *, transcript: list[dict], force_ready: bool = False,
                     v2: bool = False) -> dict:
        """Guided-intake / triage: run ONE clarifying turn over the transcript ([{role, text}]) and return
        either the next question (status="ask") or a crisp refined question + recommended route
        (status="ready"). `force_ready` (caller's turn cap) coerces a route. {} when the vertical has no
        triage prompt (feature effectively off). `v2` selects the vertical's intake-v2 directive + the
        TriageTurnV2 schema (register/case_facts/retrieval_terms); without a v2 directive it falls back
        to v1 behavior, byte-identical. Never answers the medical question — only narrows + routes."""
        if not self.triage_prompt:
            return {}
        from eigen_kernel.research.triage import run_triage_turn
        use_v2 = bool(v2 and self.triage_prompt_v2)
        roster = ", ".join(f"{s.get('specialty','')}" for s in self.panel_roster()) if self.panel_specialists else ""
        turn = await run_triage_turn(
            llm=self.llm,
            triage_prompt=(self.triage_prompt_v2 if use_v2 else self.triage_prompt),
            transcript=transcript, roster_summary=roster, force_ready=force_ready,
            schema_v2=use_v2)
        return turn.model_dump()

    async def refine(self, *, question: str) -> list[str]:
        """Pre-answer refinements: 0, or a few DISTINCT sharper standalone questions to choose from.
        [] when the vertical has no refine prompt, the question is already precise, or on error. Uses
        the FAST planner model — it only proposes questions the user picks; it never enters a gate."""
        if not self.refine_prompt:
            return []
        from eigen_kernel.research.refine import refine_question
        return await refine_question(
            llm=self.planner_llm or self.llm, refine_prompt=self.refine_prompt, question=question)

    async def search(
        self,
        *,
        question: str,
        tenant_id: str,
        workspace_id: str | None = None,
        source_keys: list[str] | None = None,
        k: int = 8,
        facets: dict | None = None,
    ):
        """Retrieval only — no LLM. Returns ranked evidence blocks. Works with just
        the embedder (OpenAI), so it's available even when the answer LLM isn't.
        `facets` is an optional HARD filter (generic dimension→allowed-values), e.g.
        `{"source_kind": ("paper","preprint")}` to retrieve only research. Omitted → no filter."""
        from eigen_kernel.contract.dto import RetrievalRequest
        qv = list(self.embedder.embed([question])[0])
        return await self._retriever(source_keys).search(RetrievalRequest(
            query=question, tenant_id=tenant_id, workspace_id=workspace_id,
            query_embedding=qv, k=k, facets=facets or {}))
