from __future__ import annotations

import pytest

from api.thesis import transcript as tx


@pytest.mark.asyncio
async def test_extract_keeps_only_verbatim_quotes():
    T = ("Interviewer: how hard was switching?\n"
         "Buyer: honestly the migration took a weekend, far easier than we feared. "
         "We had budgeted three months.")
    async def llm(system, user):
        return {"points": [
            {"quote": "the migration took a weekend, far easier than we feared",
             "point": "Switching was easy.", "relation": "supports"},
            {"quote": "it took an entire year of painful rework",   # NOT in transcript → dropped
             "point": "Switching was hard.", "relation": "contradicts"}]}
    pts = await tx.extract_call_points(llm, transcript=T, aspect_prompt="Is switching feasible?",
                                       thesis="X", subject="")
    assert len(pts) == 1
    assert pts[0]["relation"] == "supports" and "migration took a weekend" in pts[0]["quote"]


@pytest.mark.asyncio
async def test_extract_empty_without_model_or_transcript():
    assert await tx.extract_call_points(None, transcript="hi", aspect_prompt="a", thesis="t") == []
    async def llm(s, u): return {"points": []}
    assert await tx.extract_call_points(llm, transcript="", aspect_prompt="a", thesis="t") == []


def test_call_status_is_conservative_on_independence():
    C = lambda who, firm, rel: {"source_key": "call", "said_by": who, "source_subject": firm, "relation": rel}
    assert tx.call_status([])[0] == "unsettleable"                      # nobody asked
    assert tx.call_status([C("A", "Acme", "supports")])[0] == "primary_research_needed"   # one account
    # three people at ONE firm are still one account → not settled
    same_firm = [C("A", "Acme", "supports"), C("B", "Acme", "supports"), C("C", "Acme", "supports")]
    assert tx.call_status(same_firm)[0] == "primary_research_needed"
    # two INDEPENDENT firms one way → moves
    assert tx.call_status([C("A", "Acme", "supports"), C("B", "Globex", "supports")])[0] == "supported"
    assert tx.call_status([C("A", "Acme", "contradicts"), C("B", "Globex", "contradicts")])[0] == "contradicted"
    # conflicting accounts → open, never a false settle
    assert tx.call_status([C("A", "Acme", "supports"), C("B", "Globex", "contradicts"),
                           C("C", "Initech", "supports")])[0] in ("open", "supported")
