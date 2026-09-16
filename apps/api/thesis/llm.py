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


def _openai_reasoning_json_seam(*, model: str, api_key: str, base_url: str | None = None):
    """A resilient `llm_json(system, user) -> dict` for a REASONING model (o-series, gpt-5.x): those
    reject a non-default `temperature`, and some reject `response_format`. We try the richest param set
    first and progressively drop what a given model rejects, so one seam works across model families and
    still returns parsed JSON (the prompt always says 'output ONLY the JSON object')."""
    from eigen_kernel.providers import _jsonsafe
    state: dict = {}

    async def llm_json(system: str, user: str) -> dict:
        if "client" not in state:
            from openai import AsyncOpenAI
            state["client"] = AsyncOpenAI(api_key=api_key, base_url=base_url)
        cli = state["client"]
        base = dict(model=model, messages=[{"role": "system", "content": system},
                                           {"role": "user", "content": user}])
        attempts = (
            {**base, "response_format": {"type": "json_object"}, "temperature": 0},  # gpt-4o-style
            {**base, "response_format": {"type": "json_object"}},                    # reasoning: no temp
            {**base},                                                               # last resort: parse prose
        )
        last: Exception | None = None
        for kw in attempts:
            try:
                resp = await cli.chat.completions.create(**kw)
                return _jsonsafe.loads(resp.choices[0].message.content)
            except Exception as exc:      # noqa: BLE001 — try the next, simpler param set
                last = exc
        raise last if last else RuntimeError("no attempt succeeded")

    return llm_json


def take_json():
    """The DEEP-THINKING seam for the Collective Take — a reasoning model (default gpt-5.5, override with
    EIGEN_THESIS_TAKE_MODEL). Returns None when OpenAI is unconfigured so the caller falls back to the
    strong seam. The take is the one artifact whose whole value is second-order synthesis across every
    finding, so it gets the strongest reasoner; the deck/matrix stay on the faster strong seam."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    model = os.environ.get("EIGEN_THESIS_TAKE_MODEL") or "gpt-5.5"
    return _openai_reasoning_json_seam(model=model, api_key=key)
