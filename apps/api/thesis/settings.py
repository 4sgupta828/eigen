"""Runtime, admin-editable settings (currently the reasoning provider), backed by ts_setting and read
through a short-TTL in-process cache. So a toggle from the app UI takes effect within seconds across
workers without a redeploy, while sync call sites (the LLM seam builders) can read the current value
without touching the DB on the hot path.
"""
from __future__ import annotations

import os
import time

from . import store as tstore

# The settings the UI exposes, with their allowed values + the env var that seeds the default.
KNOWN: dict[str, dict] = {
    "reasoning_provider": {
        "label": "Reasoning model provider",
        "help": "Which provider powers the take, answers, deck, competitive, brainstorm and other "
                "reasoning steps. DeepSeek is cheap (good for development); OpenAI uses the strongest models.",
        "options": ["deepseek", "openai"],
        "env": "EIGEN_THESIS_REASONING_PROVIDER",
        "default": "deepseek",
    },
}

_TTL = 15.0
_cache: dict = {"data": {}, "at": 0.0}


def env_default(key: str) -> str:
    spec = KNOWN.get(key) or {}
    return (os.environ.get(spec.get("env", "")) or spec.get("default", "")).strip().lower()


def get_cached(key: str, default: str = "") -> str:
    """Sync read of the cached override, else the env/default. Never touches the DB (hot path safe)."""
    v = str(_cache["data"].get(key) or "").strip().lower()
    return v or (env_default(key) if key in KNOWN else default)


async def ensure_fresh(pool) -> None:
    """Refresh the cache from the DB if the TTL has elapsed. Call at run/synthesis starts (async), so
    sync `get_cached` reads a value that's at most _TTL seconds stale. Never raises."""
    if time.monotonic() - _cache["at"] < _TTL:
        return
    try:
        _cache["data"] = await tstore.get_all_settings(pool)
        _cache["at"] = time.monotonic()
    except Exception:      # noqa: BLE001 — a settings-read failure must never break a run; keep last cache
        _cache["at"] = time.monotonic()


async def effective(pool) -> dict:
    """The effective settings for the admin UI: value (override-or-default), default, options, source."""
    await ensure_fresh(pool)
    out = {}
    for key, spec in KNOWN.items():
        override = str(_cache["data"].get(key) or "").strip().lower()
        out[key] = {"value": override or env_default(key), "default": env_default(key),
                    "override": override, "options": spec["options"], "label": spec["label"],
                    "help": spec["help"], "source": "override" if override else "default"}
    return out


async def set_value(pool, key: str, value: str) -> str:
    """Set (or clear, with '') a runtime setting; validates against KNOWN. Returns the effective value."""
    spec = KNOWN.get(key)
    if not spec:
        raise ValueError("unknown setting")
    v = str(value or "").strip().lower()
    if v and v not in spec["options"]:
        raise ValueError("value not allowed for this setting")
    await tstore.set_setting(pool, key, v)
    _cache["data"][key] = v          # update the cache immediately for this worker
    _cache["at"] = time.monotonic()
    return v or env_default(key)
