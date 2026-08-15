"""Suggested follow-up questions — propose a few next questions that deepen discovery.

After an answer, suggest 3–4 questions the user could ask next to go deeper: understand the
mechanism/evidence better, explore an adjacent angle, or move toward action. The domain framing
(what "deeper discovery, understanding, and action" means here) lives entirely in the vertical's
`suggest_prompt`; the kernel owns only the mechanics. These are QUESTIONS, not answers — asking
one runs the normal grounded loop, so nothing here bypasses the grounding invariant.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from eigen_kernel.providers.llm import LLMClient


class Suggestions(BaseModel):
    questions: list[str] = Field(default_factory=list, description="3–4 concise follow-up questions")


async def suggest_followups(
    *, llm: LLMClient, suggest_prompt: str, question: str, answer: str,
    history: str = "", max_tokens: int = 700,
) -> list[str]:
    """Return 3–4 follow-up questions (or [] if there's nothing useful to suggest)."""
    clean = (answer or "").strip()
    user = (
        (f"CONVERSATION SO FAR:\n{history}\n\n" if history.strip() else "")
        + f"CURRENT QUESTION:\n{question}\n\n"
        + f"ANSWER GIVEN:\n{clean or '(no grounded answer was produced)'}\n\n"
        "Propose the next questions the user could ask. Each must be a single, self-contained "
        "question that stands on its own if clicked."
    )
    res = await llm.complete(
        system=suggest_prompt,
        messages=[{"role": "user", "content": user}],
        response_format=Suggestions, max_tokens=max_tokens)
    seen, out = set(), []
    for q in (res.parsed.questions or []):
        s = (q or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower()); out.append(s)
    return out[:4]
