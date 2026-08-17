"""Offline unit tests for the keyless DuckDuckGo web client — parsing only, NO network."""
from __future__ import annotations

from eigen_kernel.providers.ddg_web import DuckDuckGoWebSearch, _clean, _real_url


def test_unwrap_ddg_redirect_url():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fopenai.com%2Findex%2Fgpt-5-6&rut=abc"
    assert _real_url(href) == "https://openai.com/index/gpt-5-6"
    assert _real_url("https://anthropic.com/news") == "https://anthropic.com/news"
    assert _real_url("//example.com/x") == "https://example.com/x"


def test_clean_strips_tags_and_whitespace():
    assert _clean("<b>GPT-5.6</b>\n  has   landed") == "GPT-5.6 has landed"


def test_recency_days_to_ddg_timelimit():
    d = DuckDuckGoWebSearch._df
    assert d(None) == "" and d(1) == "d" and d(7) == "w" and d(30) == "m" and d(150) == "y"
