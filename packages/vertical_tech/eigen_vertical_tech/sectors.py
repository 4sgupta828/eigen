"""SECTOR_PROFILES — the sub-vertical seam (threaded via the manifest `sector_profiles` slot).

Each sector (AI, fintech, biotech…) is a per-question SUBJECT scope, NOT a separate vertical
package: one deployment answers across all of them. A profile supplies sector vocabulary
(`vocab_seed`), a retrieval-steering `context_fn(question) -> planner-only context str`, a
compose `directive`, and optionally sector-specific extra `web_domains`. Adding a sector =
one dict entry here — zero kernel/connector change. Mirrors medical `country_profiles`.
"""
from __future__ import annotations

# ---- AI / ML (the seeded beachhead sector) -------------------------------------------------

_AI_VOCAB = (
    "large language model", "foundation model", "transformer", "inference", "training compute",
    "GPU", "benchmark", "MMLU", "agentic", "fine-tuning", "RAG", "open-weights",
    "OpenAI", "Anthropic", "Google DeepMind", "Meta AI", "Mistral", "Nvidia", "Hugging Face",
)

_AI_DOMAINS = ("paperswithcode.com", "huggingface.co", "mlcommons.org", "arxiv.org")


def _ai_context(question: str) -> str:
    """Planner-only steering context for the AI sector (never a citable fact)."""
    return ("SECTOR = AI/ML. Relevant evidence lives in arXiv preprints, peer-reviewed ML papers, "
            "benchmark leaderboards (MMLU, MLPerf, SWE-bench), model/repo traction on GitHub and "
            "Hugging Face, and the SEC filings of public AI companies. When judging a technology "
            "claim, prefer reproducible benchmark numbers and granted patents over marketing.")

_AI_DIRECTIVE = ("For AI/ML subjects: report benchmark results with the EXACT metric, dataset, and "
                 "model size; distinguish a released open-weights model from an API-only one; treat "
                 "compute/parameter and 'state-of-the-art' claims as vendor statements unless a "
                 "third-party benchmark confirms them.")

SECTOR_PROFILES: dict[str, dict] = {
    "ai": {
        "context_fn": _ai_context,
        "directive": _AI_DIRECTIVE,
        "vocab_seed": _AI_VOCAB,
        "web_domains": _AI_DOMAINS,
    },
    # Future sectors (fintech, biotech, semiconductors, climate…) drop in here as one entry each.
}
