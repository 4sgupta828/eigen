"""TDD for the intent debugger (kernel). Pure: no model, no DB, no domain vocabulary."""
from __future__ import annotations

from eigen_kernel.facets import Contract, FacetKey, FacetSchema, FacetType
from eigen_kernel.facets.intent_check import evidence, parse, worth_asking

SCHEMA = FacetSchema(keys=(
    FacetKey(key="mode", type=FacetType.categorical, kinds=("thing",), label="Mode",
             values=("remote", "hybrid", "onsite")),
    FacetKey(key="tier", type=FacetType.ordinal, kinds=("thing",), label="Tier",
             values=("junior", "mid", "senior")),
    FacetKey(key="tags", type=FacetType.set, kinds=("thing",), label="Tags"),
))


def test_the_evidence_shows_what_was_asked_what_was_decided_and_what_came_back():
    """A debugger that will not show its current hypothesis is just a prompt. The model is given the
    query, the contract in force, and the actual result set — enough to judge whether they agree."""
    c = Contract(kind="thing", text="platform", must={"mode": ["remote"]}, prefer={"tier": ["senior"]})
    rows = [{"title": "Platform Engineer", "company": "acme", "facets": {"tier": ["senior"], "mode": ["remote"]}},
            {"title": "Infra Engineer", "company": "acme", "facets": {"tier": ["mid"], "mode": ["remote"]}}]
    counts = {"tier": {"senior": 9000, "mid": 1000}}          # the whole slice — deliberately unlike the rows
    ev = evidence("platform", c, rows, counts, SCHEMA, kind="thing")
    assert ev["query"] == "platform"
    assert ev["believed"]["must"] == {"mode": ["remote"]}
    assert ev["returned"]["titles"] == ["Platform Engineer", "Infra Engineer"]
    assert ev["vocabulary"]["mode"] == ["remote", "hybrid", "onsite"]
    # the spread describes THESE ROWS, not the slice they were drawn from
    assert ev["spread"]["tier"] == [{"value": "senior", "share": 0.5}, {"value": "mid", "share": 0.5}]
    assert "mode" not in ev["spread"], "a value every row shares distinguishes nothing"


def test_the_spread_describes_the_rows_not_the_whole_index():
    """THE BUG THIS EXISTS FOR. `counts` are computed over the MUST-SLICE, and when the only must is a
    country that slice is the entire index. Feeding them here told the debugger that a search for ML
    infrastructure had returned "truck driving 3280, insurance 1440" — the shape of the whole job
    market — and it duly reported that retrieval was pulling in noise. It reasoned correctly from
    evidence that was wrong, and accused the search of a fault it did not have."""
    rows = [{"title": "ML Infra Engineer", "facets": {"tags": ["machine learning", "infrastructure"]}},
            {"title": "Distributed Systems Engineer", "facets": {"tags": ["distributed systems", "machine learning"]}}]
    index_wide = {"tags": {"truck driving": 3280, "insurance": 1440, "machine learning": 12}}
    ev = evidence("ml infra", Contract(kind="thing"), rows, index_wide, SCHEMA, kind="thing")
    values = [v["value"] for v in ev["spread"]["tags"]]
    assert "truck driving" not in values and "insurance" not in values
    assert "machine learning" in values


def test_a_reading_keeps_only_values_the_vocabulary_holds():
    """The same discipline a compiled contract gets: an invented value never reaches a search."""
    got = parse({"question": "Which did you mean?", "readings": [
        {"label": "Infra", "says": "the substrate", "text": "kubernetes reliability",
         "prefer": {"tier": ["senior", "wizard"], "made_up": ["x"]}}]}, SCHEMA, "thing")
    assert got is not None
    assert got.readings[0].prefer == {"tier": ["senior"]}


def test_a_reading_that_would_change_nothing_is_dropped():
    """An option that carries no edit is not an option — choosing it would re-run the same search."""
    got = parse({"question": "Which?", "readings": [
        {"label": "Empty", "says": "nothing at all"},
        {"label": "Real", "says": "something", "text": "developer tooling"}]}, SCHEMA, "thing")
    assert [r.label for r in got.readings] == ["Real"]


def test_no_readings_means_no_question():
    """Saying nothing is a valid and common answer; an empty menu must not reach the reader."""
    assert parse({"question": "Which?", "readings": []}, SCHEMA, "thing") is None
    assert parse({"readings": [{"label": "x", "text": "y"}]}, SCHEMA, "thing") is None, "a menu needs its question"
    assert parse(None, SCHEMA, "thing") is None


def test_at_most_three_readings_reach_the_reader():
    raw = {"question": "Which?", "readings": [{"label": f"r{i}", "text": f"t{i}"} for i in range(6)]}
    assert len(parse(raw, SCHEMA, "thing").readings) == 3


# ---------------------------------------------------------------- when to ask at all

def test_a_short_query_is_worth_asking_about():
    """Few words carry little constraint — the case where a reading is most likely to be wrong."""
    assert worth_asking("platform engineer", {"pool": 400})[0] is True


def test_a_long_query_still_gets_a_read():
    """A word count cannot judge whether a question was understood — only what came back can, and only
    the model sees that. "ML Infra Distributed Systems, AI Agents VP Director roles" is eight words and
    was silently skipped; a reader cannot tell that from a query that simply had nothing to say. The
    model is asked, and returns no readings when nothing is unclear."""
    ok, why = worth_asking("staff backend engineer at stripe working on payments infrastructure",
                           {"pool": 400, "best_match": 95})
    assert ok is True and why


def test_the_only_silences_are_the_ones_that_cannot_be_argued_with():
    assert worth_asking("", {"pool": 400})[0] is False           # nothing was typed
    assert worth_asking("platform", {"pool": 3})[0] is False     # nothing to have a view about


def test_an_ambiguous_query_is_always_worth_asking_about():
    ok, _ = worth_asking("a very long and otherwise specific sounding sentence about work", {"pool": 400},
                         ambiguous=True)
    assert ok is True


def test_a_thin_result_set_is_never_reinterpreted():
    """With almost nothing back, the problem is coverage, not comprehension."""
    assert worth_asking("platform", {"pool": 3})[0] is False


class TestDistinctReadings:
    """A reading is a way of understanding the words. Two options that run the same query and differ only
    in which facet they attach are one reading and a chip — and the rail already has every chip."""

    def _r(self, label, text, **kw):
        from eigen_kernel.facets.intent_check import Reading
        return Reading(label=label, text=text, **kw)

    def test_two_readings_sharing_one_query_collapse(self):
        """Measured on the first real model call: "AI infra seed funds" and "AI infra venture funds",
        identical text, differing only by investor_type. Both legal, both useless."""
        from eigen_kernel.facets.intent_check import distinct_readings
        got = distinct_readings([
            self._r("AI infra seed funds", "ai infrastructure", prefer={"investor_type": ["seed_fund"]}),
            self._r("AI infra venture funds", "ai infrastructure", prefer={"investor_type": ["venture_fund"]}),
        ])
        assert len(got) == 1 and got[0].label == "AI infra seed funds"

    def test_readings_with_different_queries_both_survive(self):
        from eigen_kernel.facets.intent_check import distinct_readings
        got = distinct_readings([
            self._r("Training and serving", "model inference and GPU orchestration"),
            self._r("Tooling around models", "evaluation and observability for LLMs"),
        ])
        assert len(got) == 2

    def test_case_and_spacing_do_not_defeat_it(self):
        from eigen_kernel.facets.intent_check import distinct_readings
        got = distinct_readings([self._r("A", "AI  Infrastructure"), self._r("B", "ai infrastructure")])
        assert len(got) == 1

    def test_a_reading_with_no_query_is_kept(self):
        """A pure facet edit is a legitimate, if weak, reading — it is only the DUPLICATE query that is not."""
        from eigen_kernel.facets.intent_check import distinct_readings
        got = distinct_readings([self._r("A", "", must={"stage": ["seed"]}),
                                 self._r("B", "", must={"stage": ["series_a"]})])
        assert len(got) == 2


class TestReadingsMustBeProse:
    """`text` is the search a person would type. The contract restated in facet syntax is not a reading."""

    def test_facet_syntax_is_not_prose(self):
        from eigen_kernel.facets.intent_check import reads_as_prose
        for t in ('still_deploying: ["yes_recent"] AND ai_infra',
                  'investor_type: ["venture_fund", "seed_fund"] AND ai_infra',
                  'investor_type:seed_fund', 'still_deploying:yes_recent', 'stage=seed'):
            assert not reads_as_prose(t), t

    def test_real_queries_are_prose(self):
        from eigen_kernel.facets.intent_check import reads_as_prose
        for t in ("model inference and GPU orchestration",
                  "funds small enough that a $2M round matters to them",
                  "evaluation and observability for LLMs", ""):
            assert reads_as_prose(t), t

    def test_a_colon_in_ordinary_prose_survives(self):
        from eigen_kernel.facets.intent_check import reads_as_prose
        assert reads_as_prose("infrastructure: the layer that runs models")
        assert reads_as_prose("see https://example.com for the list")

    def test_a_reading_keeps_its_label_when_only_the_query_was_fake(self):
        """"Firms that say they do pre-seed" is a real distinction even when the model wrote the filter
        into the wrong field. Drop the fake query, keep the reading."""
        from eigen_kernel.facets import FacetKey, FacetSchema, FacetType
        from eigen_kernel.facets.intent_check import parse
        sc = FacetSchema(keys=(FacetKey(key="investor_type", type=FacetType.categorical, kinds=("i",),
                                        values=("seed_fund", "venture_fund")),))
        got = parse({"question": "which?", "readings": [
            {"label": "They say so", "says": "self-reported", "text": "investor_type:seed_fund",
             "prefer": {"investor_type": ["seed_fund"]}}]}, sc, "i")
        assert got and len(got.readings) == 1
        assert got.readings[0].text == "" and got.readings[0].prefer == {"investor_type": ["seed_fund"]}


class TestAbsenceIsNeverAFinding:
    """Caught in production: "no regulatory disclosures reported, indicating a lack of transparency."
    No disclosures on file is a CLEAN record; the sentence turned it into an accusation."""

    def test_the_measured_sentence_is_rejected(self):
        from eigen_kernel.facets.intent_check import absence_read_as_finding
        assert absence_read_as_finding(
            "There is a significant share of firms with no regulatory disclosures reported, "
            "indicating a lack of transparency or recent activity")

    def test_other_shapes_of_the_same_error(self):
        from eigen_kernel.facets.intent_check import absence_read_as_finding
        for t in ("this suggests a lack of activity", "the firms are opaque about their portfolio",
                  "a failure to disclose their sectors", "these companies are hiding their funding"):
            assert absence_read_as_finding(t), t

    def test_an_honest_observation_survives(self):
        from eigen_kernel.facets.intent_check import absence_read_as_finding
        for t in ("72% of these firms are SEC-registered advisers",
                  "we have not read their sites yet, so stated terms are missing for most",
                  "most of these closed their latest fund in 2024 or later"):
            assert not absence_read_as_finding(t), t

    def test_parse_drops_the_observation_but_keeps_the_turn(self):
        from eigen_kernel.facets import FacetKey, FacetSchema, FacetType
        from eigen_kernel.facets.intent_check import parse
        sc = FacetSchema(keys=(FacetKey(key="k", type=FacetType.categorical, kinds=("i",), values=("a", "b")),))
        got = parse({"believed": "Right now I'm showing X", "understanding": ["asked for X"],
                     "noticed": "no disclosures reported, indicating a lack of transparency"}, sc, "i")
        assert got and got.noticed == "" and got.believed == "Right now I'm showing X"
