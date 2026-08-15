"""Suggested follow-up questions directive (opaque prose the kernel threads)."""
from __future__ import annotations

TECH_SUGGEST_PROMPT = """Given a tech-diligence Q&A, propose 3–4 self-contained follow-up questions \
that deepen the diligence, across four angles:
- deeper understanding (a technology/financial detail worth pulling next),
- adjacent discovery (a competitor, comparable, or upstream/downstream player to examine),
- risk & tradeoffs (a concentration, dependency, IP, or execution risk to probe),
- toward a decision (what evidence would most change the investment view).
Each must be concrete, answerable from filings/patents/papers/code/news, and NOT an investment \
recommendation. Return them as short standalone questions."""
