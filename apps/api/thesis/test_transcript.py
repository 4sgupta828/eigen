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


@pytest.mark.asyncio
async def test_extract_insights_gates_verbatim_and_maps_stance():
    from api.thesis import transcript as tx
    transcript = ("Interviewer: How painful is the switch? Expert: Honestly ripping out our vector "
                  "database would take two quarters and we would not do it lightly. But the pricing "
                  "keeps climbing every renewal.")
    async def llm(system, user):
        return {"points": [
            {"quote": "ripping out our vector database would take two quarters",
             "insight": "High switching cost", "stance": "validates", "refers_to": "How high are switching costs?"},
            {"quote": "the pricing keeps climbing every renewal",
             "insight": "Pricing pressure", "stance": "invalidates", "refers_to": "Is pricing stable?"},
            {"quote": "THIS WAS NEVER SAID IN THE CALL", "insight": "hallucinated", "stance": "validates", "refers_to": ""},
            {"quote": "we would not do it lightly", "insight": "reluctance", "stance": "bogus-stance", "refers_to": ""},
        ]}
    got = await tx.extract_insights(llm, transcript=transcript, inquiry_name="Switching costs",
                                    framing="Test lock-in", questions=["How high are switching costs?"],
                                    thesis="Vector DB has a moat")
    quotes = [g["quote"] for g in got]
    assert "ripping out our vector database would take two quarters" in quotes
    assert "the pricing keeps climbing every renewal" in quotes
    assert "THIS WAS NEVER SAID IN THE CALL" not in quotes      # verbatim gate drops the hallucination
    stances = {g["quote"]: g["stance"] for g in got}
    assert stances["ripping out our vector database would take two quarters"] == "validates"
    assert stances["the pricing keeps climbing every renewal"] == "invalidates"
    assert stances["we would not do it lightly"] == "context"   # unknown stance → context (fail-safe)


@pytest.mark.asyncio
async def test_extract_insights_safe_without_a_model():
    from api.thesis import transcript as tx
    assert await tx.extract_insights(None, transcript="x", inquiry_name="", framing="",
                                     questions=[], thesis="") == []


def test_insight_tally_counts_stances():
    from api.thesis import transcript as tx
    t = tx.insight_tally([{"stance": "validates"}, {"stance": "validates"},
                          {"stance": "invalidates"}, {"stance": "weird"}, {}])
    assert t == {"validates": 2, "invalidates": 1, "context": 2}   # weird + missing → context
