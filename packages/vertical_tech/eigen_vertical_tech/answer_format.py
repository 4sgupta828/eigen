"""Tech answer-shaping directives (opaque prose the kernel threads into compose).

A diligence-memo structure for an investor audience. Sections appear ONLY when supported by
verified findings — never fabricate a heading to fill it (empty mandatory sections pressure
the model to invent, which attacks the provenance gate from the prompt side). Market signal
is a SEPARATE, explicitly-labeled section so sentiment is never merged into grounded fact.
"""
from __future__ import annotations

TECH_ANSWER_FORMAT = """Write for an investor doing diligence. Markdown. Include a section ONLY \
when the verified findings support it — never add an empty or speculative heading.

Sections, in order, each present only if supported:
- **Bottom line** — the 1–3 sentence read a partner needs first, strictly from verified facts.
- **Funding & traction** — rounds, investors, revenue/loss, customers, hiring/repo momentum \
(from filings/funding records/code), each with a verbatim [n] citation.
- **Technology & IP** — architecture/approach claims, benchmark results (with the exact figure), \
granted vs. pending patents. Distinguish a GRANTED patent from a pending APPLICATION.
- **Competitive landscape** — named competitors/substitutes and any comparison the evidence states.
- **Market signal** — news / forum / social SENTIMENT, clearly framed as perception and momentum, \
NOT fact ("coverage suggests…", "sentiment is…"). Never state a signal as an established number.
- **Not addressed** — what the retrieved evidence does NOT cover (an evidence GAP, not an inference).

Every factual sentence carries an inline [n] tied to a verified quote. Do not rank a single \
"best" investment or predict a winner; report the grounded facts and name what the evidence \
does not establish. Optional inline highlight markers the UI may render: [[F]]…[[/F]] (a hard \
fact/number), [[R]]…[[/R]] (reasoning), [[K]]…[[/K]] (key context)."""

# Sharper A/B variant used only when the diligence-synthesis flag is ON (Rule 20 seam).
# Same section set; tighter in-section discipline. None-safe: falls back to TECH_ANSWER_FORMAT.
TECH_DILIGENCE_SYNTHESIS_FORMAT = TECH_ANSWER_FORMAT + """

Additional discipline when synthesizing:
- Preserve exact figures ($, %, headcount, benchmark score) verbatim; never round or paraphrase a number.
- Treat a filing's forward-looking statements and a press release as INTENT, not realized results.
- Attribute every competitive or market claim to the specific source that states it; do not aggregate \
sentiment into an implied fact. Avoid vague momentum words ("promising", "explosive") unless quoted."""
