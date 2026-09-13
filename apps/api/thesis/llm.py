"""Tiered LLM seams for the thesis flow.

Most JSON calls (genesis clarifier, question generation, frame, decompose) are high-volume and
non-critical — DeepSeek (cheap, OpenAI-protocol JSON mode) is fine, and that stays the default seam
(`Providers.from_env().llm_json`, wired in routes as `_llm_json`).

The STRATEGIC, quality-critical steps — synthesizing the grounded ANSWER and reformulating the search
queries — are where the eval showed us weak (specificity/groundedness), so those route through a
STRONGER model (OpenAI) via `strong_json()`. If no OpenAI key/config is present, `strong_json()` returns
None and callers fall back to the default seam, so nothing breaks.
"""
from __future__ import annotations

import os


def _openai_json_seam(*, model: str, api_key: str, base_url: str | None = None):
    """An `llm_json(system, user) -> dict` over the OpenAI chat API in json_object mode (same shape as
    Providers.from_env's seam, so it's a drop-in for make_synthesize / reformulation)."""
    from eigen_kernel.providers import _jsonsafe
    state: dict = {}

    async def llm_json(system: str, user: str) -> dict:
        if "client" not in state:
            from openai import AsyncOpenAI
            state["client"] = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await state["client"].chat.completions.create(
            model=model, response_format={"type": "json_object"}, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return _jsonsafe.loads(resp.choices[0].message.content)

    return llm_json


def strong_json():
    """The strong (OpenAI) JSON seam for strategic answer-creation steps, or None when unconfigured
    (caller falls back to the default DeepSeek seam). Model via EIGEN_THESIS_STRONG_MODEL."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    model = os.environ.get("EIGEN_THESIS_STRONG_MODEL") or "gpt-4o"
    return _openai_json_seam(model=model, api_key=key)
