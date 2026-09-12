"""TestStartupThesis — the gates that make this a stress test rather than a search.

Free: no database, no model. Every case here is one designed to pass a gate while being wrong.
"""
import pytest

from api.thesis import attack as atk
from api.thesis import argue as arg
from api.thesis import decompose as dec
from api.thesis import people as ppl
from api.thesis.attack import _terms, binds, verdict_for
from api.thesis.routes import next_move
from api.thesis.schema import CALL_ONLY, SETTLEABLE, is_signal_only, labels, register_of


# ── the ladder is fixed, and two rungs can never move ──────────────────────────────────────────────

def test_willingness_to_pay_and_switching_can_never_be_settled_by_documents():
    """The whole design rests on this. No document records a budget that was never allocated for a
    SKU that was never offered — so no amount of encouraging retrieval may move these."""
    assert SETTLEABLE["willingness_to_pay"] == CALL_ONLY
    assert SETTLEABLE["switching_feasible"] == CALL_ONLY


def test_a_mountain_of_supporting_evidence_cannot_settle_a_call_only_claim():
    v, note = verdict_for(settleable=CALL_ONLY, n_for=99, n_against=0)
    assert v == "unsettleable"
    assert "needs a person" in note


def test_the_model_never_decides_settleable():
    """A model that just wrote an encouraging sentence about willingness to pay will mark it
    settleable. The schema decides, not the model."""
    import inspect
    src = inspect.getsource(dec.decompose)
    assert '"settleable": SETTLEABLE[k]' in src
    assert "c.get(\"settleable\")" not in src and "c['settleable']" not in src


@pytest.mark.asyncio
async def test_a_thesis_with_no_model_still_gets_the_whole_ladder():
    out = await dec.decompose(None, "Mid-market logistics firms will pay for route re-planning.")
    assert [c["rung"] for c in out["claims"]] == list(SETTLEABLE.keys())
    assert all(c["claim"] for c in out["claims"])
    assert out["degraded"] is True
    assert out["error"] == "decomposer_unavailable"


# ── the verdicts ───────────────────────────────────────────────────────────────────────────────────

def test_nothing_either_way_is_under_tested_not_supported():
    """The state nobody else ships, and the reason this is a stress test: disconfirmation attempted
    is not disconfirmation found."""
    v, note = verdict_for(settleable="corpus", n_for=0, n_against=0)
    assert v == "under_tested"
    assert "Nothing either way" in note


def test_support_with_no_counter_evidence_says_so_out_loud():
    """A claim nobody could attack is not thereby proven, and the note must not let it read that way."""
    v, note = verdict_for(settleable="corpus", n_for=4, n_against=0)
    assert v == "supported"
    assert "not the same as there being nothing to find" in note


def test_counter_evidence_with_no_support_contradicts():
    assert verdict_for(settleable="corpus", n_for=0, n_against=2)[0] == "contradicted"


def test_evidence_both_ways_is_open_not_a_winner():
    v, note = verdict_for(settleable="corpus", n_for=3, n_against=2)
    assert v == "open" and "Read both" in note


# ── congruence: the Clay lesson, at claim scale ───────────────────────────────────────────────────

def test_one_shared_word_is_not_congruence():
    terms = _terms("Mid-market logistics firms already pay for route-optimisation software")
    assert not binds("our firms are growing quickly this year", terms)
    assert binds("route-optimisation is standard at logistics firms", terms)


def test_grammar_words_are_never_binding_terms():
    terms = [t.lower() for t in _terms("Companies need to pay for the software they use")]
    for junk in ("companies", "need", "pay", "they", "use", "for", "the"):
        assert junk not in terms, junk


def test_one_generic_domain_noun_can_never_bind_alone():
    """"software" is a real noun in a thesis about software and is kept as a term — but two distinct
    terms are required, so it can never bind a passage on its own."""
    terms = _terms("Companies need to pay for the software they use")
    assert [t.lower() for t in terms] == ["software"]
    assert not binds("this software is popular", terms)


def test_a_term_must_stand_as_its_own_word():
    """'scale' must not match inside 'scaled' — the failure that corrupted a whole dossier once."""
    assert not binds("we scaled and rescaled the cluster", ["scale", "cluster2"])


# ── sentiment is quarantined ──────────────────────────────────────────────────────────────────────

def test_forum_enthusiasm_is_signal_not_evidence():
    """The most seductive false positive in this mode: an excited thread reads exactly like demand."""
    for k in ("hackernews", "reddit", "news", "startup_news", "gdelt"):
        assert is_signal_only(k), k
    for k in ("edgar", "github", "eng_blog"):
        assert not is_signal_only(k), k


def test_registers_follow_the_source_not_the_prose():
    assert register_of("edgar") == "filed"
    assert register_of("github") == "observed"
    assert register_of("hackernews") == "stated"
    assert register_of("call") == "stated", "a person's account is never laundered into filed"


# ── the agent's move ──────────────────────────────────────────────────────────────────────────────

def _doc(claims, turns=()):
    return {"claims": claims, "turns": list(turns), "subject": {"segment": "mid-market logistics"}}


def test_the_agent_attacks_before_it_talks():
    d = _doc([{"rung": "problem_exists", "claim": "c", "settleable": "corpus", "verdict": "open",
               "attacked": False, "evidence": []}])
    m = next_move(d)
    assert m["move"] == "attacked" and m["payload"]["action"] == "attack"


def test_the_agent_opens_on_the_weakest_claim_not_the_nicest():
    ev_bad = [{"side": "against", "signal_only": False, "quote": "they all build it in house",
               "title": "T", "register": "observed", "source_key": "eng_blog"}]
    ev_good = [{"side": "for", "signal_only": False, "quote": "everyone pays for this",
                "title": "G", "register": "filed", "source_key": "edgar"}]
    d = _doc([
        {"rung": "enough_buyers", "claim": "lots of buyers", "settleable": "corpus",
         "verdict": "supported", "attacked": True, "evidence": ev_good},
        {"rung": "problem_exists", "claim": "the problem is real", "settleable": "corpus",
         "verdict": "contradicted", "attacked": True, "evidence": ev_bad},
    ])
    m = next_move(d)
    assert m["move"] == "attacked" and m["rung"] == "problem_exists"


def test_an_unsettleable_claim_becomes_a_person_and_a_question():
    d = _doc([{"rung": "willingness_to_pay", "claim": "they would pay $50k",
               "settleable": CALL_ONLY, "verdict": "unsettleable", "attacked": False,
               "evidence": []}])
    m = next_move(d)
    assert m["move"] == "needs_person"
    assert m["payload"]["question"]
    assert "buyer" in m["payload"]["ask"]


def test_every_move_is_one_of_the_three():
    for verdict in ("contradicted", "under_tested", "unsettleable", "supported", "open"):
        d = _doc([{"rung": "problem_exists", "claim": "c", "settleable": "corpus",
                   "verdict": verdict, "attacked": True,
                   "evidence": [{"side": "for", "signal_only": False, "quote": "q", "title": "t",
                                 "register": "filed", "source_key": "edgar"}]}])
        assert next_move(d)["move"] in ("settled", "attacked", "needs_person")


# ── people ────────────────────────────────────────────────────────────────────────────────────────

def test_a_person_with_no_name_is_never_invented():
    rows = ppl.from_evidence([{"source_key": "eng_blog", "title": "t", "quote": "q",
                               "source_url": "u", "register": "stated"}])
    assert rows == []


def test_a_complainer_is_not_offered_as_a_buyer():
    """Users complain; buyers allocate. A forum source may never map to the buyer role."""
    for sk, (role, _k) in ppl._ROLE_OF.items():
        if sk in ("hackernews", "reddit"):
            assert role != "buyer"
    assert "hackernews" not in ppl._ROLE_OF and "reddit" not in ppl._ROLE_OF


def test_we_say_plainly_when_we_cannot_name_a_buyer():
    g = ppl.buyer_guidance("claim", "regional banks")
    assert "rarely name an economic buyer" in g and "regional banks" in g


def test_labels_ship_the_whole_ladder_so_the_shell_hardcodes_nothing():
    l = labels()
    assert len(l["ladder"]) == len(SETTLEABLE)
    assert set(l["verdicts"]) >= {"supported", "contradicted", "under_tested", "unsettleable"}


@pytest.mark.asyncio
async def test_the_decomposer_calls_the_json_seam_the_way_the_app_defines_it():
    """`llm_json(system, user)` is POSITIONAL (startups/pipeline.py). Calling it with keywords
    raises, the except swallows it, and the ladder comes back generic with nothing saying it
    failed — a silent degradation that looks exactly like 'the model had nothing to add'."""
    seen = {}

    async def seam(system, user):
        seen["system"], seen["user"] = system, user
        return {"subject": {"product": "p"},
                "claims": [{"rung": "problem_exists", "claim": "a real claim"}]}

    out = await dec.decompose(seam, "Logistics firms will pay for route re-planning.")
    assert seen.get("user"), "the seam was never called with positional args"
    assert out["subject"]["product"] == "p"
    assert out["claims"][0]["claim"] == "a real claim"
    # …and the model still does not get to say what is settleable.
    assert out["claims"][0]["settleable"] == SETTLEABLE["problem_exists"]


# ── the web leg ───────────────────────────────────────────────────────────────────────────────────

def test_web_rows_are_signal_never_fact():
    """An article is somebody writing. It can colour a case and can never carry it — the standing
    directive, and here also the difference between a stress test and a hype machine."""
    import asyncio

    class _R:
        url, title, snippet, body, published, highlights = (
            "https://x.com/a", "Route chaos at mid-market carriers",
            "mid-market logistics firms still re-plan their delivery routes by hand every single "
            "morning, on a whiteboard", "", "", ())

    class _C:
        async def search(self, q, **kw):
            return [_R()]

    rows = asyncio.run(atk._web(_C(), "q", "for", ["logistics", "delivery", "routes"]))
    assert rows and rows[0]["signal_only"] is True
    assert rows[0]["register"] == "stated"
    assert rows[0]["source_url"] == "https://x.com/a", "a web row the reader cannot open is worthless"


def test_a_web_row_must_bind_the_claim_like_any_other():
    import asyncio

    class _R:
        url, title, snippet, body, published, highlights = (
            "https://x.com/b", "Something else", "a long enough passage about entirely other matters "
            "that shares no terms with the claim at all", "", "", ())

    class _C:
        async def search(self, q, **kw):
            return [_R()]

    rows = asyncio.run(atk._web(_C(), "q", "for", ["logistics", "delivery", "routes"]))
    assert rows == []


def test_signal_rows_never_move_a_verdict():
    """Web coverage is all we have on a thin claim — and a verdict built on it would say `supported`
    off the back of sentiment. The counts that decide exclude signal rows."""
    assert verdict_for(settleable="corpus", n_for=0, n_against=0)[0] == "under_tested"


# ── stable case citations ─────────────────────────────────────────────────────────────────────────

def _case_evidence(evidence_id: str, *, quote: str = "A measured result.") -> dict:
    return {"id": evidence_id, "side": "for", "signal_only": False, "register": "filed",
            "source_key": "edgar", "source_subject": "Entity A",
            "evidence_kind": "operating_metric", "period": "2026-Q2", "quote": quote,
            "gate_results": {"span_ok": True, "entailed": True, "on_subject": True,
                             "kind_ok": True, "period_ok": True}}


def test_case_rows_use_stable_evidence_ids_and_keep_identity_metadata() -> None:
    rendered = arg._rows([_case_evidence("ev-abc")], "for")

    assert "[[e:ev-abc]]" in rendered
    assert "Entity A" in rendered
    assert "operating_metric" in rendered
    assert "2026-Q2" in rendered
    assert "on_subject=true" in rendered


def test_reordering_evidence_does_not_retarget_case_citation() -> None:
    first = _case_evidence("ev-first", quote="First result.")
    second = _case_evidence("ev-second", quote="Second result.")

    assert "[[e:ev-first]]" in arg._rows([second, first], "for")
    assert "[[e:ev-first]]" in arg._rows([first, second], "for")


def test_sentence_with_invented_evidence_id_fails_closed() -> None:
    text = "Supported result [[e:ev-real]]. Invented assertion [[e:ev-fake]]."

    assert arg.sanitize_case(text, {"ev-real"}) == "Supported result [[e:ev-real]]."


@pytest.mark.asyncio
async def test_case_model_output_is_validated_against_claim_evidence() -> None:
    async def seam(_system, _user):
        return {"cases": [{"rung": "problem_exists",
                            "case_for": "Real [[e:ev-real]]. Fake [[e:ev-fake]].",
                            "case_against": "Nothing in the record speaks to this side yet.",
                            "leans": "for"}], "overall": "The claim has support."}

    cases, _overall = await arg.cases_for(seam, thesis="A thesis", claims=[{
        "rung": "problem_exists", "claim": "A claim", "evidence": [_case_evidence("ev-real")],
    }])

    assert cases["problem_exists"]["case_for"] == "Real [[e:ev-real]]."


def test_corpus_row_keeps_stable_source_and_evidence_identity():
    row = atk._row({
        "document_id": "doc-7", "block_id": "block-9",
        "text": "Regional operators report a repeated measurable workflow failure every week.",
        "document_title": "Operating report", "source_key": "edgar",
        "published_at": "2026-04-01T00:00:00Z",
        "facets": {"issuer": "Entity A", "evidence_kind": "operating_metric",
                   "url": "https://example.test/report"},
    }, "for")

    assert row["document_id"] == "doc-7"
    assert row["block_id"] == "block-9"
    assert row["source_subject"] == "Entity A"
    assert row["evidence_kind"] == "operating_metric"
    assert row["period"] == "2026-04-01"
    assert row["facets"]["issuer"] == "Entity A"


@pytest.mark.asyncio
async def test_missing_refuter_is_attack_unavailable_not_under_tested():
    got = await atk.attack_claim("", claim="Entity A has a repeated workflow failure",
                                 settleable="corpus", judge_llm=None)

    assert got["research_status"] == "attack_unavailable"
    assert got["attack_attempted"] is False
    assert got["verdict"] != "under_tested"
