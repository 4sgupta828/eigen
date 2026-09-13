"""The answer gate is string-level and fail-safe — the panel's grounding fix."""
from __future__ import annotations

from eigen_kernel.decision import sanitize_answer, NOT_ESTABLISHED


def test_a_cited_sentence_survives_with_stable_markers():
    out = sanitize_answer([{"text": "The record shows churn is high.", "evidence_ids": ["e1", "e2"]}],
                          ["e1", "e2", "e3"])
    assert "The record shows churn is high." in out
    assert "[[e:e1]]" in out and "[[e:e2]]" in out


def test_a_sentence_citing_an_invented_id_is_dropped_whole():
    # the intra-sentence hallucination the panel flagged: a false clause ending in a valid id must NOT
    # launder in — the WHOLE sentence is dropped because it also cites an invalid id
    out = sanitize_answer([{"text": "They have 100% market share.", "evidence_ids": ["made_up", "e1"]}],
                          ["e1"])
    assert out == NOT_ESTABLISHED


def test_uncited_prose_is_dropped():
    out = sanitize_answer([{"text": "This looks strong.", "evidence_ids": []}], ["e1"])
    assert out == NOT_ESTABLISHED


def test_no_regex_splitting_abbreviations_survive_intact():
    # "Inc." would have broken the old regex splitter; the sentence-array gate keeps it whole
    out = sanitize_answer([{"text": "Acme Inc. filed a Form D in 2026.", "evidence_ids": ["e9"]}], ["e9"])
    assert "Acme Inc. filed a Form D in 2026." in out
    assert "[[e:e9]]" in out


def test_mixed_kept_and_dropped():
    out = sanitize_answer([
        {"text": "Good, cited.", "evidence_ids": ["ok"]},
        {"text": "Bad, invented cite.", "evidence_ids": ["nope"]},
        {"text": "Uncited.", "evidence_ids": []},
    ], ["ok"])
    assert "Good, cited." in out
    assert "Bad, invented cite." not in out
    assert "Uncited." not in out


def test_raw_ids_in_prose_are_stripped_keeping_only_clean_markers():
    out = sanitize_answer([{"text": "Revenue grew 20% (abc123def456ghi789).", "evidence_ids": ["abc123def456ghi789"]}],
                          ["abc123def456ghi789"])
    assert "Revenue grew 20%." in out                    # the parenthesized raw id is gone
    assert "abc123def456ghi789" not in out.replace("[[e:abc123def456ghi789]]", "")  # no bare id leaks
    assert "[[e:abc123def456ghi789]]" in out             # only the clean marker remains


def test_bracketed_ids_and_empty_brackets_are_scrubbed():
    # the model often writes its cite inline as "[<id>]"; stripping the id must not leave a stray "[]"
    out = sanitize_answer(
        [{"text": "Five tools failed the causality test in May 2026 [abc123def456ghi789].",
          "evidence_ids": ["abc123def456ghi789"]}], ["abc123def456ghi789"])
    assert "May 2026." in out                            # no " []" and no double space before the period
    assert "[]" not in out.replace("[[e:abc123def456ghi789]]", "")
    assert "[[e:abc123def456ghi789]]" in out             # the clean marker is still appended


def test_literal_empty_brackets_from_the_model_are_removed():
    out = sanitize_answer([{"text": "The results were clear []. ", "evidence_ids": ["ok"]}], ["ok"])
    assert "The results were clear." in out              # empty [] the model typed is gone
    assert "[]" not in out.replace("[[e:ok]]", "")


def test_bullets_mode_prefixes_each_point_and_single_newline_joins():
    out = sanitize_answer([
        {"text": "Fact one.", "evidence_ids": ["a"]},
        {"text": "Fact two.", "evidence_ids": ["b"]}], ["a", "b"], bullets=True)
    assert out == "- Fact one. [[e:a]]\n- Fact two. [[e:b]]"


def test_sanitize_table_gates_rows_and_appends_source_markers():
    from eigen_kernel.decision import sanitize_table
    tbl = {"columns": ["Tool", "Result"], "rows": [
        {"cells": ["LangSmith", "failed causality test"], "evidence_ids": ["ok1"]},
        {"cells": ["Phoenix", "failed"], "evidence_ids": ["nope"]},        # bad id → dropped
        {"cells": ["Studio"], "evidence_ids": ["ok1"]}]}                   # wrong arity → dropped
    md = sanitize_table(tbl, ["ok1"])
    assert "| Tool | Result | Source |" in md                             # header + Source column
    assert "| LangSmith | failed causality test | [[e:ok1]] |" in md      # kept row cites its source
    assert "Phoenix" not in md and "Studio" not in md                     # ungrounded rows dropped


def test_sanitize_table_empty_or_single_column_returns_blank():
    from eigen_kernel.decision import sanitize_table
    assert sanitize_table(None, ["x"]) == ""
    assert sanitize_table({"columns": ["Only"], "rows": [{"cells": ["a"], "evidence_ids": ["x"]}]}, ["x"]) == ""
    assert sanitize_table({"columns": ["A", "B"], "rows": []}, ["x"]) == ""
