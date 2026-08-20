"""Assemble the tech VerticalManifest — the single object this vertical exposes.

Everything domain-specific (connectors, persona, authority pyramid, answer format, lenses,
sector profiles, UI, eval gold) is passed in HERE; the kernel only threads opaque strings and
duck-typed policies. Sectors are the `sector_profiles` map — one deployment answers across
AI/fintech/biotech… (see sectors.py). Analytical angles are `extraction_lenses` (see lenses.py).
"""
from __future__ import annotations

from eigen_kernel.contract.manifest import VerticalManifest

from . import discovery, entities, evidence_kind
from .answer_format import (TECH_ANSWER_FORMAT, TECH_DILIGENCE_SYNTHESIS_FORMAT,
                            TECH_VISUAL_GUIDANCE, TECH_CHART_GUIDANCE, TECH_REASONING_FORMAT)
from .terms import TECH_TERMS_PROMPT
from .visuals import TECH_VISUALS_PROMPT
from .authority import TechAuthorityPolicy
from .connectors import (ArxivConnector, CompaniesHouseConnector, CrossrefConnector, EdgarConnector,
                         EngBlogConnector,
                         ExpertFeedConnector, GdeltConnector, GithubConnector, HackerNewsConnector,
                         HuggingFaceConnector, LobstersConnector, NihReporterConnector, NsfConnector,
                         OpenAlexConnector,
                         OpenReviewConnector, PatentsViewConnector, PodcastConnector, RedditConnector,
                         SemanticScholarConnector, StackExchangeConnector, UsptoConnector,
                         WikidataConnector, WikipediaConnector)
from .use_case_lenses import USE_CASE_LENSES
from .answer_contract import ANSWER_PROFILES, TECH_CONTRACT_PROMPT
from .reasoned import (TECH_ADAPTIVE_ANSWER_FORMAT, TECH_ADAPTIVE_SCAFFOLD_PROMPT,
                       TECH_REASONED_ANSWER_FORMAT, TECH_REASONED_SCAFFOLD_PROMPT,
                       TECH_UNDERSTANDING_ANSWER_FORMAT, TECH_UNDERSTANDING_QUERY_HINT,
                       adaptive_format_on)
from .eval_gold import GOLD
from .freshness import TECH_FRESHNESS_POLICY
from .fixtures import sample_filings, sample_papers
from .gaps import TECH_GAP_PROMPT
from .ma import MA_DIRECTIVE
from .gating import TechGatingPolicy
from .lenses import EXTRACTION_LENSES
from .persona import TechPersona
from .scope import SCOPE_DIMENSIONS
from .sectors import SECTOR_PROFILES
from .source import TechRetrievalSource
from .suggest import TECH_SUGGEST_PROMPT
from .ui import TechUI
from .web_domains import TRUSTED_WEB_DOMAINS, WEB_DOMAIN_FACETS


def build_manifest() -> VerticalManifest:
    return VerticalManifest(
        name="tech",
        entity_types=entities.ENTITY_TYPES,
        scope_dimensions=SCOPE_DIMENSIONS,
        # Connectors are fixture-injected so the offline pipeline + tests run without network.
        connectors={
            "edgar": EdgarConnector(filings=sample_filings()),
            "arxiv": ArxivConnector(papers=sample_papers()),
            "openalex": OpenAlexConnector(),
            "semantic_scholar": SemanticScholarConnector(),
            "crossref": CrossrefConnector(),
            "wikidata": WikidataConnector(),
            "hackernews": HackerNewsConnector(),
            "reddit": RedditConnector(),
            "lobsters": LobstersConnector(),
            "stackoverflow": StackExchangeConnector(),
            "huggingface": HuggingFaceConnector(),
            "openreview": OpenReviewConnector(),
            "companies_house": CompaniesHouseConnector(),
            "uspto": UsptoConnector(),
            "wikipedia": WikipediaConnector(),
            "nsf": NsfConnector(),
            "nih_reporter": NihReporterConnector(),
            "expert_feed": ExpertFeedConnector(),
            "eng_blog": EngBlogConnector(),
            "podcast": PodcastConnector(),
            "github": GithubConnector(),
            "patentsview": PatentsViewConnector(),
            "gdelt": GdeltConnector(),
        },
        retrieval_sources={"corpus": TechRetrievalSource()},
        gating_policy=TechGatingPolicy(),
        citation_verifier=None,       # block_span handled by the kernel
        persona=TechPersona(),
        authority_policy=TechAuthorityPolicy(),
        evidence_classifier=evidence_kind.classify,   # structural facets → evidence tier (Rule 18)
        discovery_entity_of=discovery.entity_of,       # "who is working on X" scouting (M&A/corp-dev)
        # Analytical modes / USE-CASE LENSES: acquirer (M&A) + the deep-tech-intelligence lenses
        # (foresight/wisdom/genesis/market/whitespace/moat) that re-mix + re-posture the same grounded
        # evidence per what the user is doing. Selected via the request `mode`.
        answer_modes={"acquirer": MA_DIRECTIVE, **USE_CASE_LENSES},
        ui=TechUI(),
        answer_format=TECH_ANSWER_FORMAT,
        # Enhanced A/B synthesis variant (reuses the kernel's enhanced-answer slot; same section set).
        clinical_answer_format=TECH_DILIGENCE_SYNTHESIS_FORMAT,
        # Concept/term glossary + grounded conceptual VISUALS (diagrams) + inline visual/chart/reasoning
        # guidance — the noesis answer-augmentation features, targeted for tech diligence (flag-gated).
        terms_prompt=TECH_TERMS_PROMPT,
        visuals_prompt=TECH_VISUALS_PROMPT,
        visual_guidance=TECH_VISUAL_GUIDANCE,
        chart_guidance=TECH_CHART_GUIDANCE,
        reasoning_format=TECH_REASONING_FORMAT,
        gap_prompt=TECH_GAP_PROMPT,
        suggest_prompt=TECH_SUGGEST_PROMPT,
        web_domains=TRUSTED_WEB_DOMAINS,
        web_domain_facets=WEB_DOMAIN_FACETS,
        # Fast-moving tech: recency re-orders ALL tiers over a short horizon (flag EIGEN_FRESHNESS_RANKING).
        freshness_policy=TECH_FRESHNESS_POLICY,
        # Question-driven evidence regime (flag EIGEN_ANSWER_CONTRACT): one classification →
        # current/established/balanced → customizes retrieval+ranking+compose per question.
        contract_prompt=TECH_CONTRACT_PROMPT,
        answer_profiles=ANSWER_PROFILES,
        # REASONED engine (flag EIGEN_REASONED_DEFAULT, default OFF — the noesis clinical-decision mode
        # re-homed to diligence): one scaffold call classifies the question (decision/lookup/understanding)
        # → decision-shaped questions get a coverage-brief-steered retrieval + a decision-first, grounding-
        # safe compose contract; lookups fall through to the standard engine; why/how → causal-model engine.
        # OFF → the engine param is ignored and answers are byte-identical to today.
        # FLAG EIGEN_ADAPTIVE_FORMAT: swap the ported clinical/VC decision memo for the general-audience,
        # question-adaptive format + de-VC scaffold (the persona de-VCs in lockstep, in persona.py). OFF →
        # legacy (byte-identical). Read at manifest-build (process start), so flip = redeploy.
        reasoned_scaffold_prompt=(TECH_ADAPTIVE_SCAFFOLD_PROMPT if adaptive_format_on()
                                  else TECH_REASONED_SCAFFOLD_PROMPT),
        reasoned_answer_format=(TECH_ADAPTIVE_ANSWER_FORMAT if adaptive_format_on()
                                else TECH_REASONED_ANSWER_FORMAT),
        understanding_answer_format=TECH_UNDERSTANDING_ANSWER_FORMAT,
        understanding_query_hint=TECH_UNDERSTANDING_QUERY_HINT,
        # Sub-vertical seam: sectors as a per-question subject scope (AI seeded), NOT separate verticals.
        sector_profiles=SECTOR_PROFILES,
        # Analytical lenses (the orthogonal axis): angles applied within the active sector.
        extraction_lenses=EXTRACTION_LENSES,
        eval_gold=dict(GOLD),
    )
