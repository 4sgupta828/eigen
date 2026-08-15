"""Trusted web-search domains for the tech vertical + venue-authority facet stamps.

When set, web search is RESTRICTED to these — the corpus is augmented only with high-quality
sources, never the open web. `WEB_DOMAIN_FACETS` stamps venue authority as structural metadata
so web evidence is graded by `evidence_kind.classify` like corpus evidence.
"""
from __future__ import annotations

TRUSTED_WEB_DOMAINS: tuple[str, ...] = (
    # Primary / regulatory
    "sec.gov", "uspto.gov", "patents.google.com",
    # Verified structured — scholarly / benchmarks / code
    "arxiv.org", "openalex.org", "semanticscholar.org", "crossref.org",
    "paperswithcode.com", "mlcommons.org", "huggingface.co", "github.com",
    # Analysis — reputable trade / business press
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "theinformation.com",
    "techcrunch.com", "arstechnica.com", "nature.com", "ieee.org",
    # Structured company/funding profiles (public pages)
    "crunchbase.com", "dealroom.co", "pitchbook.com",
)

# domain → facets stamped on web-retrieved blocks (venue authority as structural metadata).
WEB_DOMAIN_FACETS: dict[str, dict] = {
    "sec.gov": {"source_kind": "filing"},
    "uspto.gov": {"source_kind": "patent"},
    "patents.google.com": {"source_kind": "patent"},
    "arxiv.org": {"source_kind": "preprint"},
    "openalex.org": {"source_kind": "paper", "is_peer_reviewed": "true"},
    "semanticscholar.org": {"source_kind": "paper"},
    "paperswithcode.com": {"source_kind": "benchmark"},
    "mlcommons.org": {"source_kind": "benchmark"},
    "github.com": {"source_kind": "code"},
    "reuters.com": {"source_kind": "news"},
    "bloomberg.com": {"source_kind": "news"},
    "ft.com": {"source_kind": "news"},
    "wsj.com": {"source_kind": "news"},
    "techcrunch.com": {"source_kind": "news"},
    "theinformation.com": {"source_kind": "news"},
}
