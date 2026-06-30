"""Tests for Stage 4 refinement: JSON parsing, action application, vLLM call."""
import json

import pytest

from scripts.textrefinement import refine as s4


def test_loads_json_object_direct_and_fallback():
    assert s4._loads_json_object('{"a": 1}') == {"a": 1}
    assert s4._loads_json_object('noise {"a": 2} tail') == {"a": 2}
    with pytest.raises(json.JSONDecodeError):
        s4._loads_json_object("no json here")


def test_tail_text():
    assert s4._tail_text("abcdef", 3) == "def"
    assert s4._tail_text("ab", 5) == "ab"
    assert s4._tail_text(["@book{a}", "@book{b}"], 100).startswith("@book{a}")


def test_coerce_section_normalises_types():
    s = s4._coerce_section({"title": 123, "content": {"x": 1}, "tables": "nope",
                            "_action": "remove"})
    assert s == {"title": "123", "content": "", "tables": [], "figures": [],
                 "_action": "remove"}
    assert s4._coerce_section("not a dict")["_action"] == "keep"
    assert s4._coerce_section({"content": ["@book{x}"]})["content"] == ["@book{x}"]


def test_is_empty_section():
    assert s4._is_empty_section({"content": "  ", "tables": [], "figures": []})
    assert not s4._is_empty_section({"content": "x"})
    assert not s4._is_empty_section({"content": "", "tables": [{"id": "t"}]})
    assert not s4._is_empty_section({"content": ["@book{x}"]})


def test_apply_actions_keep_remove_merge():
    sections = [
        {"title": "A", "content": "a", "_action": "keep"},
        {"title": "B", "content": "b", "_action": "merge_into_previous"},
        {"title": "C", "content": "c", "_action": "remove"},
        {"title": "D", "content": "d", "_action": "keep"},
    ]
    result, last = s4._apply_actions(sections, None)
    assert [s["title"] for s in result] == ["A", "D"]
    assert result[0]["content"] == "a b"      # B merged into A
    assert last["title"] == "D"


def test_apply_actions_merges_across_window_boundary():
    prev = {"title": "Prev", "content": "p", "tables": [], "figures": []}
    sections = [{"title": "frag", "content": "x", "_action": "merge_into_previous"}]
    result, _ = s4._apply_actions(sections, prev)
    assert result == []                # nothing new emitted
    assert prev["content"] == "p x"    # merged into the carried-over previous section


def test_apply_actions_tolerates_non_dict_section():
    result, _ = s4._apply_actions([{"title": "K", "_action": "keep"}, "junk"], None)
    assert [s["title"] for s in result] == ["K", ""]


def test_block_ids_of_output_tolerates_non_dict():
    # The LLM occasionally emits a bare string where a section object belongs;
    # provenance threading (_redistribute_segments) must not crash on it.
    assert s4._block_ids_of_output("a bogus string section") == set()
    assert s4._block_ids_of_output({"content": "[p1_tbl0] text",
                                    "tables": [{"id": "p1_tbl0"}]}) == {"p1_tbl0"}


def test_call_llm_happy_path(make_client, seq_responder):
    client = make_client(seq_responder(['{"sections": [{"_action": "keep", "title": "A"}]}']))
    assert s4._call_llm([{"title": "A", "content": "x"}], client) == [
        {"_action": "keep", "title": "A"}
    ]


def test_call_llm_request_uses_json_object_format(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    s4._call_llm([{"t": 1}], client)
    assert rec[0]["response_format"] == {"type": "json_object"}
    assert "max_tokens" in rec[0] and "temperature" in rec[0]


def test_call_llm_injects_previous_context(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    prev = {"title": "Vorheriger", "content": "…ENDE-MARKER"}
    s4._call_llm([{"title": "X"}], client, prev)
    user_msg = rec[0]["messages"][1]["content"]
    assert "CONTEXT (read-only" in user_msg
    assert "ENDE-MARKER" in user_msg and "merge_into_previous" in user_msg


def test_call_llm_retries_after_bad_json(make_client, seq_responder):
    client = make_client(seq_responder(["garbage", '{"sections": []}']))
    assert s4._call_llm([{"t": 1}], client) == []


def test_call_llm_exhausts_to_none(make_client, seq_responder):
    client = make_client(seq_responder([RuntimeError("down")]))
    assert s4._call_llm([{"t": 1}], client) is None


def test_strip_table_source_text():
    secs = [
        {"tables": [{"id": "t", "source_text": "x"}, {"id": "u"}], "figures": []},
        "junk",   # non-dict tolerated
    ]
    s4._strip_table_source_text(secs)
    assert "source_text" not in secs[0]["tables"][0]
    assert secs[0]["tables"][1] == {"id": "u"}


def test_run_refine_uses_provided_data(tmp_path):
    out = s4.run_refine(tmp_path, data={"sections": []})
    assert out == {"sections": []}
    assert (tmp_path / "results" / "structured_output_final.json").exists()


def test_run_refine_missing_input_returns_none(tmp_path):
    assert s4.run_refine(tmp_path, data=None) is None
