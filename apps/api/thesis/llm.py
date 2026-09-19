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

import contextvars
import os

# The last LLM/provider error seen in THIS async task (background run), so a run whose artifact came back
# empty can attribute it to the real cause instead of failing silently. Reset at the start of each run;
# read after producing the artifact. Per-task (asyncio.create_task copies the context), so no cross-talk.
LAST_LLM_ERROR: contextvars.ContextVar[str] = contextvars.ContextVar("last_llm_error", default="")


def classify_llm_error(exc: Exception | str) -> str:
    """A short, user-facing reason for an LLM/provider failure — surfaced across every synthesis surface
    so the user is never left clueless in front of an empty artifact."""
    name = "" if isinstance(exc, str) else type(exc).__name__
    s = (exc if isinstance(exc, str) else str(exc)).lower()
    if "429" in s or "ratelimit" in name.lower() or "rate limit" in s:
        if any(k in s for k in ("no credits", "quota", "billing", "insufficient", "exceeded your current")):
            return "The model API is out of credits — top up the provider account (e.g. OpenAI → Billing) and retry."
        return "The model API is rate-limited right now — wait a moment and retry."
    if "timeout" in s or "timed out" in name.lower() or "timed out" in s:
        return "The model API timed out — retry."
    if any(k in s for k in ("authentication", "invalid api key", "incorrect api key", "401")) or "auth" in name.lower():
        return "The model API key is invalid or missing — check the API configuration."
    if "connection" in s or "connect" in name.lower():
        return "Couldn't reach the model API — check connectivity and retry."
    return f"The model API returned an error ({name or 'unknown'}) — retry, or check the API configuration."


def _record(exc: Exception):
    try:
        LAST_LLM_ERROR.set(classify_llm_error(exc))
    except Exception:      # noqa: BLE001
        pass


def recording(seam):
    """Wrap any llm_json seam so a failure records its cause (for run-level surfacing) then re-raises.
    Applied to the default seam so DeepSeek errors surface too; the OpenAI seams record natively."""
    if seam is None:
        return None

    async def wrapped(system: str, user: str):
        try:
            return await seam(system, user)
        except Exception as exc:      # noqa: BLE001
            _record(exc)
            raise
    return wrapped


def _openai_json_seam(*, model: str, api_key: str, base_url: str | None = None):
    """An `llm_json(system, user) -> dict` over the OpenAI chat API in json_object mode (same shape as
    Providers.from_env's seam, so it's a drop-in for make_synthesize / reformulation)."""
    from eigen_kernel.providers import _jsonsafe
    state: dict = {}

    async def llm_json(system: str, user: str) -> dict:
        if "client" not in state:
            from openai import AsyncOpenAI
            state["client"] = AsyncOpenAI(api_key=api_key, base_url=base_url)
        try:
            resp = await state["client"].chat.completions.create(
                model=model, response_format={"type": "json_object"}, temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            return _jsonsafe.loads(resp.choices[0].message.content)
        except Exception as exc:      # record the real cause for the run to surface, then re-raise
            _record(exc)
            raise

    return llm_json


def reasoning_provider() -> str:
    """Which provider powers the STRONG + REASONING seams (the take, answer synthesis, query
    reformulation, deck, competitive, prioritize, sample, brainstorm): 'deepseek' (default — cheap, for
    development) or 'openai' (the strongest models). Set at runtime from the admin Settings UI (a
    short-TTL cache; falls back to the EIGEN_THESIS_REASONING_PROVIDER env, then 'deepseek'). 'deepseek'
    makes strong_json()/take_json() return None so callers fall through to the default DeepSeek seam."""
    try:
        from . import settings
        return settings.get_cached("reasoning_provider", "deepseek")
    except Exception:      # noqa: BLE001 — never let a settings read break seam selection
        return (os.environ.get("EIGEN_THESIS_REASONING_PROVIDER") or "deepseek").strip().lower()


def strong_json():
    """The strong JSON seam for strategic steps. OpenAI when the reasoning provider is 'openai' and a key
    is configured; otherwise None so the caller falls back to the default (DeepSeek) seam.
    Model via EIGEN_THESIS_STRONG_MODEL."""
    if reasoning_provider() != "openai":
        return None
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
        if last:
            _record(last)      # every attempt failed — record the real cause for the run to surface
            raise last
        raise RuntimeError("no attempt succeeded")

    return llm_json


def take_json():
    """The DEEP-THINKING seam for the Collective Take — the strongest reasoner when the reasoning provider
    is 'openai' (default model gpt-5.5, override with EIGEN_THESIS_TAKE_MODEL). Returns None otherwise
    (provider 'deepseek', or no key) so the caller falls back to the strong/default seam. Toggle via
    EIGEN_THESIS_REASONING_PROVIDER."""
    if reasoning_provider() != "openai":
        return None
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    model = os.environ.get("EIGEN_THESIS_TAKE_MODEL") or "gpt-5.5"
    return _openai_reasoning_json_seam(model=model, api_key=key)
