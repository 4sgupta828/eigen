from __future__ import annotations

import pytest

from eigen_kernel.research.evidence_binding import EvidenceCandidate, bind_candidates


def _candidate(**changes) -> EvidenceCandidate:
    values = {
        "id": "cand-1",
        "quote": "The measured result fell by 31 percent during the current period.",
        "block_text": "Report. The measured result fell by 31 percent during the current period.",
        "document_id": "doc-1",
        "block_id": "block-4",
        "source_subject": "Entity A",
        "evidence_kind": "measured_result",
        "period": "2026-Q2",
        "facets": {"issuer": "Entity A"},
        "discovery_side": "against",
    }
    values.update(changes)
    return EvidenceCandidate(**values)


@pytest.mark.asyncio
async def test_relationship_comes_from_binding_not_discovery_side() -> None:
    async def judge(_system, _user):
        return {"bindings": [{"candidate_id": "cand-1", "relation": "supports",
                               "entailed": True, "on_subject": True, "kind_ok": True,
                               "period_ok": True, "reason": "Direct measurement."}]}

    got = await bind_candidates("Entity A result fell", [_candidate()], judge)

    assert got[0]["discovery_side"] == "against"
    assert got[0]["relation"] == "supports"
    assert got[0]["gate_results"] == {"span_ok": True, "entailed": True,
                                      "on_subject": True, "kind_ok": True,
                                      "period_ok": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_gate", ["entailed", "on_subject", "kind_ok", "period_ok"])
async def test_any_failed_congruence_gate_demotes_candidate_to_context(failed_gate: str) -> None:
    async def judge(_system, _user):
        row = {"candidate_id": "cand-1", "relation": "contradicts", "entailed": True,
               "on_subject": True, "kind_ok": True, "period_ok": True, "reason": "Checked."}
        row[failed_gate] = False
        return {"bindings": [row]}

    got = await bind_candidates("Entity A result rose", [_candidate()], judge)

    assert got[0]["relation"] == "context"
    assert got[0]["gate_results"][failed_gate] is False


@pytest.mark.asyncio
async def test_quote_missing_from_block_fails_before_judgment() -> None:
    calls = 0

    async def judge(_system, _user):
        nonlocal calls
        calls += 1
        return {"bindings": []}

    got = await bind_candidates("Entity A result rose", [
        _candidate(quote="A quote that is absent from the source block."),
    ], judge)

    assert calls == 0
    assert got[0]["relation"] == "context"
    assert got[0]["gate_results"]["span_ok"] is False


@pytest.mark.asyncio
async def test_missing_judge_fails_closed_instead_of_guessing() -> None:
    got = await bind_candidates("Entity A result rose", [_candidate()], None)

    assert got[0]["relation"] == "context"
    assert got[0]["gate_results"]["entailed"] is False
    assert "unavailable" in got[0]["reason"].lower()


@pytest.mark.asyncio
async def test_signal_only_candidate_stays_signal_without_judgment() -> None:
    got = await bind_candidates("Entity A result rose", [
        _candidate(signal_only=True),
    ], None)

    assert got[0]["relation"] == "signal"
    assert got[0]["gate_results"]["span_ok"] is True


@pytest.mark.asyncio
async def test_stable_provenance_and_span_hash_survive_binding() -> None:
    async def judge(_system, _user):
        return {"bindings": [{"candidate_id": "cand-1", "relation": "context",
                               "entailed": False, "on_subject": True, "kind_ok": True,
                               "period_ok": True, "reason": "Background only."}]}

    got = await bind_candidates("Entity A result rose", [_candidate()], judge)

    assert got[0]["document_id"] == "doc-1"
    assert got[0]["block_id"] == "block-4"
    assert len(got[0]["span_hash"]) == 64
    assert got[0]["facets"] == {"issuer": "Entity A"}
