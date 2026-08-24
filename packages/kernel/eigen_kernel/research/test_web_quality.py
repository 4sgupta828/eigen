"""Unit tests for the open-web quality screen (LLM-owned).

Contract: `None` = could-not-judge (caller fails safe); `[]` = judged-nothing-kept
or nothing-to-judge; `list` = kept hits.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from eigen_kernel.research.web_quality import (
    _Verdict,
    _Verdicts,
    screen_open_web_hits,
)


# --- minimal fakes -----------------------------------------------------------

@dataclass
class _FakeHit:
    """A BlockHit-like item carrying only the fields the screen reads."""
    document_id: str = ""
    document_title: str = ""
    text: str = ""


@dataclass
class _FakeResult:
    parsed: object
    output_tokens: int = 0


@dataclass
class _FakeBudget:
    exhausted: bool = False
    charges: list = field(default_factory=list)

    def charge(self, *, calls: int = 1, tokens: int = 0) -> None:
        self.charges.append((calls, tokens))


class _ScriptedLLM:
    """Returns a fixed _Verdicts (or raises) and records the call."""

    def __init__(self, verdicts=None, *, raises: Exception | None = None, output_tokens: int = 42):
        self._verdicts = verdicts or []
        self._raises = raises
        self._output_tokens = output_tokens
        self.calls = 0

    async def complete(self, *, system, messages, response_format, max_tokens=2048, temperature=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return _FakeResult(parsed=_Verdicts(verdicts=self._verdicts), output_tokens=self._output_tokens)


_PROMPT = "judge these pages (domain prompt injected here)"


def _hits(n: int) -> list[_FakeHit]:
    return [_FakeHit(document_id=f"http://x/{i}", document_title=f"t{i}", text=f"body {i}") for i in range(n)]


# --- tests -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keep_drop_filtering_by_index():
    hits = _hits(3)
    llm = _ScriptedLLM([
        _Verdict(index=0, keep=True),
        _Verdict(index=1, keep=False),
        _Verdict(index=2, keep=True),
    ])
    budget = _FakeBudget()
    out = await screen_open_web_hits(hits, question="q", llm=llm, prompt=_PROMPT, budget=budget)
    assert out == [hits[0], hits[2]]
    assert llm.calls == 1
    assert budget.charges == [(1, 42)]  # charged once with output_tokens


@pytest.mark.asyncio
async def test_out_of_range_indices_ignored():
    hits = _hits(2)
    llm = _ScriptedLLM([
        _Verdict(index=0, keep=True),
        _Verdict(index=5, keep=True),   # out of range → ignored
        _Verdict(index=-1, keep=True),  # out of range → ignored
    ])
    out = await screen_open_web_hits(hits, question="q", llm=llm, prompt=_PROMPT, budget=_FakeBudget())
    assert out == [hits[0]]


@pytest.mark.asyncio
async def test_empty_hits_returns_empty():
    # Nothing to judge is NOT a failure — empty input legitimately yields [] (not None).
    llm = _ScriptedLLM([_Verdict(index=0, keep=True)])
    budget = _FakeBudget()
    out = await screen_open_web_hits([], question="q", llm=llm, prompt=_PROMPT, budget=budget)
    assert out == []
    assert llm.calls == 0
    assert budget.charges == []


@pytest.mark.asyncio
async def test_judged_all_drop_returns_empty_list():
    # A judge that ran and dropped everything → [] (respected), NOT None (can't-judge).
    hits = _hits(3)
    llm = _ScriptedLLM([
        _Verdict(index=0, keep=False),
        _Verdict(index=1, keep=False),
        _Verdict(index=2, keep=False),
    ])
    budget = _FakeBudget()
    out = await screen_open_web_hits(hits, question="q", llm=llm, prompt=_PROMPT, budget=budget)
    assert out == []
    assert llm.calls == 1
    assert budget.charges == [(1, 42)]   # the judge DID run and was charged


@pytest.mark.asyncio
async def test_llm_none_returns_none():
    # Could not judge (no judge) → None so the caller fails safe.
    out = await screen_open_web_hits(_hits(2), question="q", llm=None, prompt=_PROMPT, budget=_FakeBudget())
    assert out is None


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", [None, "", "   "])
async def test_prompt_missing_returns_none(prompt):
    # Blank/missing prompt → could not judge → None.
    llm = _ScriptedLLM([_Verdict(index=0, keep=True)])
    out = await screen_open_web_hits(_hits(2), question="q", llm=llm, prompt=prompt, budget=_FakeBudget())
    assert out is None
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_budget_exhausted_returns_none():
    # Exhausted budget → could not judge → None; never spent.
    llm = _ScriptedLLM([_Verdict(index=0, keep=True)])
    budget = _FakeBudget(exhausted=True)
    out = await screen_open_web_hits(_hits(2), question="q", llm=llm, prompt=_PROMPT, budget=budget)
    assert out is None
    assert llm.calls == 0           # never spent
    assert budget.charges == []


@pytest.mark.asyncio
async def test_llm_raises_returns_none():
    # ANY error → could not judge → None so the caller fails safe.
    llm = _ScriptedLLM(raises=RuntimeError("boom"))
    out = await screen_open_web_hits(_hits(3), question="q", llm=llm, prompt=_PROMPT, budget=_FakeBudget())
    assert out is None


@pytest.mark.asyncio
async def test_duplicate_urls_deduped():
    hits = [
        _FakeHit(document_id="http://same", document_title="a", text="body a"),
        _FakeHit(document_id="http://same", document_title="b", text="body b"),
        _FakeHit(document_id="http://other", document_title="c", text="body c"),
    ]
    # after dedup: index 0 = first "same", index 1 = "other"
    llm = _ScriptedLLM([_Verdict(index=0, keep=True), _Verdict(index=1, keep=True)])
    out = await screen_open_web_hits(hits, question="q", llm=llm, prompt=_PROMPT, budget=_FakeBudget())
    assert out == [hits[0], hits[2]]
