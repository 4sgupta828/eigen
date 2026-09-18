"""Cross-finding synthesis — deck (compose_over_findings), memo (compose_memo), matrix (compose_matrix)
cite findings by SHORT F-tokens and resolve them (tolerating F1/f1/[F1]) back to real ids, then inherit
the fail-safe grounding gate: a point/cell/block citing no finding, or an F-number not shown, is
dropped; an invented peer row is dropped. Emitted markers carry the REAL finding id.
"""
from __future__ import annotations

import asyncio

from eigen_kernel.decision import (compose_over_findings, compose_deck, compose_memo, compose_matrix,
                                    ANALYSIS_KINDS, NOT_ESTABLISHED)

# Real finding ids are opaque (like a question id); the model only ever sees/echoes F1, F2.
_FINDINGS = [
    {"id": "abc123def456aaaa", "line": "Is the problem real?", "aspect": "problem",
     "status": "target_supported", "question": "Is the pain real?", "answer": "Churn runs 30%. [[e:e1]]"},
    {"id": "beef987654321000", "line": "Who buys?", "aspect": "buyer", "status": "target_supported",
     "question": "Are there paying buyers?", "answer": "Two enterprises signed. [[e:e9]]"},
]
_F1, _F2 = "abc123def456aaaa", "beef987654321000"
_DECK_SECTIONS = [{"key": "problem", "title": "Problem", "intent": "the pain"},
                  {"key": "ask", "title": "The Ask", "intent": "what to believe"}]


def test_deck_resolves_F_tokens_and_drops_uncited_or_out_of_range():
    async def llm(_s, _u):
        return {"sections": [
            {"key": "problem", "points": [
                {"text": "Churn runs 30% at Acme.", "finding_ids": ["F1"]},        # kept -> real id
                {"text": "Sloppy but valid.", "finding_ids": ["[f2]"]},            # kept (tolerant)
                {"text": "They own the market.", "finding_ids": ["F9"]},           # dropped: out of range
                {"text": "Looks strong.", "finding_ids": []}]},                    # dropped: uncited
            {"key": "ask", "points": []}]}
    out = asyncio.run(compose_over_findings(llm, directive="d", sections=_DECK_SECTIONS,
                                            findings=_FINDINGS, decision="Acme", layout="bullets"))
    by = {s["key"]: s["prose"] for s in out}
    assert ("[[e:%s]]" % _F1) in by["problem"] and "Churn runs 30% at Acme." in by["problem"]
    assert ("[[e:%s]]" % _F2) in by["problem"] and "Sloppy but valid." in by["problem"]
    assert "own the market" not in by["problem"] and "Looks strong" not in by["problem"]
    assert by["ask"] == NOT_ESTABLISHED
    assert [s["key"] for s in out] == ["problem", "ask"]


def test_deck_no_model_yields_blank_and_failure_never_raises():
    assert all(s["prose"] == NOT_ESTABLISHED for s in
               asyncio.run(compose_over_findings(None, directive="d", sections=_DECK_SECTIONS,
                                                  findings=_FINDINGS, layout="bullets")))

    async def boom(_s, _u):
        raise RuntimeError("down")
    assert all(s["prose"] == NOT_ESTABLISHED for s in
               asyncio.run(compose_over_findings(boom, directive="d", sections=_DECK_SECTIONS,
                                                  findings=_FINDINGS, layout="bullets")))


_SPINE = {"one_liner": "one line", "insight": "the insight", "bottom_line": "will it fly"}


def test_deck_spine_and_headline_points_gate_and_never_crash():
    async def llm(_s, _u):
        return {"spine": {
                    "one_liner": {"text": "Acme is retention tooling for churny SaaS.", "finding_ids": ["F1"]},
                    "insight": {"text": "uncited insight", "finding_ids": []},          # dropped: uncited
                    "bottom_line": {"text": "Fabricated read.", "finding_ids": ["F9"]}},  # dropped: out of range
                "sections": [
                    {"key": "problem",
                     "headline": {"text": "Churn is a 30% bleed.", "finding_ids": ["F1"]},
                     "points": [{"text": "Two enterprises already signed.", "finding_ids": ["[f2]"]},  # tolerant
                                {"text": "Looks strong.", "finding_ids": []},               # dropped: uncited
                                {"text": "They own it.", "finding_ids": ["F9"]}]},          # dropped: out of range
                    {"key": "ask",
                     "headline": {"text": "no citation", "finding_ids": []},               # dropped -> blank
                     "points": []}]}
    out = asyncio.run(compose_deck(llm, directive="d", spine_intent=_SPINE, sections=_DECK_SECTIONS,
                                   findings=_FINDINGS, decision="Acme"))
    spine = out["spine"]
    assert spine["one_liner"]["text"] == "Acme is retention tooling for churny SaaS."
    assert ("[[e:%s]]" % _F1) in spine["one_liner"]["markers"]
    assert "insight" not in spine and "bottom_line" not in spine        # both dropped, not fabricated
    probs = {s["key"]: s for s in out["sections"]}
    assert probs["problem"]["headline"]["text"] == "Churn is a 30% bleed."
    assert [p["text"] for p in probs["problem"]["points"]] == ["Two enterprises already signed."]
    assert ("[[e:%s]]" % _F2) in probs["problem"]["points"][0]["markers"]
    assert probs["ask"]["headline"]["text"] == "" and probs["ask"]["points"] == []
    assert [s["key"] for s in out["sections"]] == ["problem", "ask"]


def test_deck_no_model_and_failure_yield_blank_never_raise():
    for llm in (None, ):
        out = asyncio.run(compose_deck(llm, directive="d", spine_intent=_SPINE, sections=_DECK_SECTIONS,
                                       findings=_FINDINGS))
        assert out["spine"] == {} and all(not s["points"] and not s["headline"]["text"] for s in out["sections"])

    async def boom(_s, _u):
        raise RuntimeError("down")
    out = asyncio.run(compose_deck(boom, directive="d", spine_intent=_SPINE, sections=_DECK_SECTIONS,
                                   findings=_FINDINGS))
    assert out["spine"] == {} and [s["key"] for s in out["sections"]] == ["problem", "ask"]


def test_memo_two_layers_grounded_and_reasoning_with_kind_gate():
    secs = [{"key": "risks", "title": "Risks", "intent": "what's weak"}]

    async def llm(_s, _u):
        return {"bottom_line": {"text": "The record leans to more diligence.", "finding_ids": ["F1"]},
                "sections": [{"key": "risks",
                    "grounded": [{"text": "Churn is 30%.", "finding_ids": ["F1"]},
                                 {"text": "Fabricated.", "finding_ids": ["F7"]}],       # dropped: out of range
                    "analysis": [
                        {"kind": "gap", "text": "WTP is untested.", "finding_ids": ["F1"]},   # kept
                        {"kind": "bogus", "text": "invalid kind", "finding_ids": ["F1"]},      # dropped: kind
                        {"kind": "tension", "text": "uncited", "finding_ids": []}]}]}          # dropped: uncited
    out = asyncio.run(compose_memo(llm, directive="d", sections=secs, findings=_FINDINGS, decision="Acme"))
    assert out["bottom_line"]["text"] == "The record leans to more diligence."
    assert ("[[e:%s]]" % _F1) in out["bottom_line"]["markers"]
    sec = out["sections"][0]
    assert [g["text"] for g in sec["grounded"]] == ["Churn is 30%."]
    assert [(a["kind"], a["text"]) for a in sec["analysis"]] == [("gap", "WTP is untested.")]
    assert set(ANALYSIS_KINDS) == {"tension", "gap", "assumption", "implication", "what_would_change_this"}


def test_matrix_subject_always_shows_and_ungrounded_peer_is_dropped():
    cols = [{"key": "idea", "label": "Central idea"}, {"key": "funding", "label": "Funding"}]

    async def llm(_s, _u):
        return {"rows": [
            {"entity": "Acme", "subject": True, "cells": [
                {"col": "idea", "text": "retention tooling", "finding_ids": ["F1"]},
                {"col": "funding", "text": "invented seed round", "finding_ids": ["F9"]}]},   # cell blanked
            {"entity": "RealPeer", "subject": False, "cells": [
                {"col": "idea", "text": "adjacent tool", "finding_ids": ["F2"]}]},             # kept: grounded
            {"entity": "GhostCo", "subject": False, "cells": [
                {"col": "idea", "text": "hallucinated", "finding_ids": ["F9"]}]}]}             # dropped row
    out = asyncio.run(compose_matrix(llm, directive="d", columns=cols, findings=_FINDINGS,
                                     subject_label="Acme", decision="Acme"))
    assert [r["entity"] for r in out["rows"]] == ["Acme", "RealPeer"]      # GhostCo dropped
    acme = out["rows"][0]
    assert acme["cells"][0]["text"] == "retention tooling" and ("[[e:%s]]" % _F1) in acme["cells"][0]["markers"]
    assert acme["cells"][1]["text"] == ""          # ungrounded funding cell blanked
    assert out["columns"] == cols


def test_matrix_no_model_is_empty_not_a_crash():
    out = asyncio.run(compose_matrix(None, directive="d", columns=[{"key": "x", "label": "X"}],
                                     findings=_FINDINGS, subject_label="Acme"))
    assert out["rows"] == []


def test_deck_visual_bar_is_gated_to_findings():
    async def llm(_s, _u):
        return {"spine": {}, "sections": [
            {"key": "problem", "headline": {"text": "Churn is high.", "finding_ids": ["F1"]},
             "points": [{"text": "Churn runs 30%.", "finding_ids": ["F1"]}],
             "visual": {"kind": "bar", "title": "Churn vs. peers", "unit": "%", "series": [
                 {"label": "Acme churn", "value": 30, "finding_ids": ["F1"]},        # kept: cites a finding
                 {"label": "Signed enterprises", "value": 2, "finding_ids": ["F2"]}, # kept
                 {"label": "Made-up number", "value": 99, "finding_ids": ["F9"]},    # dropped: bad citation
                 {"label": "no cite", "value": 5, "finding_ids": []}]}},             # dropped: uncited
            {"key": "ask", "points": [{"text": "Believe it.", "finding_ids": ["F2"]}],
             "visual": {"kind": "bar", "title": "one point", "series": [
                 {"label": "solo", "value": 1, "finding_ids": ["F1"]}]}},            # <2 survivors -> no visual
        ]}
    out = asyncio.run(compose_deck(llm, directive="d", sections=_DECK_SECTIONS, findings=_FINDINGS, decision="Acme"))
    by = {s["key"]: s for s in out["sections"]}
    viz = by["problem"].get("visual")
    assert viz and viz["kind"] == "bar" and viz["unit"] == "%"
    assert [s["label"] for s in viz["series"]] == ["Acme churn", "Signed enterprises"]   # uncited/bad dropped
    assert viz["series"][0]["value"] == 30
    assert "visual" not in by["ask"]                                                     # single-series -> gated out
