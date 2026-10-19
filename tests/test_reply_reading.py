"""A model reply is read as exactly one JSON object, or asked again with its
cause named. Nothing is repaired."""
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner


def reply(content, finish="stop", thought=None):
    return SimpleNamespace(
        finish_reason=finish,
        message=SimpleNamespace(content=content, reasoning_content=thought))


@pytest.mark.parametrize("text", [
    '{"tuples": []}',
    '  {"tuples": []}\n',
])
def test_one_object_is_read(text):
    assert runner._loads_object(text) == {"tuples": []}


@pytest.mark.parametrize("text", [
    "", None, "[]", '"text"',
    '```json\n{"tuples": []}\n```',
    'Here it is: {"tuples": []}',
    '{"tuples": [',
    '<think>x</think>{"tuples": []}',
])
def test_anything_but_one_object_is_not_read(text):
    assert runner._loads_object(text) is None


def test_a_rows_reply_needs_its_tuples_list():
    assert runner._parse_reply('{"status": "complete"}') is None
    assert runner._parse_reply('{"tuples": {}}') is None


def test_a_rows_reply_defaults_to_partial_and_keeps_only_real_queries():
    got = runner._parse_reply(
        '{"tuples": [], "status": "maybe", "need_more": ["Satz", "", 3]}')
    assert got["status"] == "partial"
    assert got["need_more"] == ["Satz"]
    done = runner._parse_reply('{"tuples": [], "status": "complete"}')
    assert done["status"] == "complete" and done["need_more"] == []


def test_shared_defaults_fill_a_tuple_but_never_its_evidence():
    got = runner._parse_reply(
        '{"tuples": [{"value": 1, "quote": "eigene Zeile"}, {"value": 2}],'
        ' "defaults": {"unit_raw": "MWh", "quote": "geteilt", "value": 9}}')
    first, second = got["tuples"]
    assert first["unit_raw"] == second["unit_raw"] == "MWh"
    assert first["quote"] == "eigene Zeile"
    assert "quote" not in second and second["value"] == 2


@pytest.mark.parametrize("given, cause", [
    (reply('{"tuples": [', finish="length"), "cut_off"),
    (reply("", finish="length"), "cut_off"),
    (reply(""), "empty"),
    (reply("", thought="lange Überlegung"), "reasoning_only"),
    (reply("keine Antwort"), "no_object"),
    (reply('{"tuples": [1,, 2]}'), "syntax"),
    (reply('Antwort: {"tuples": []}'), "outside_text"),
    (reply("[1, 2]"), "not_an_object"),
    (reply('{"rows": []}'), "missing_key"),
    (reply('{"tuples": {}}'), "missing_key"),
])
def test_each_unreadable_reply_names_its_own_cause(given, cause):
    assert runner._reply_fault(given, 100, key="tuples")[0] == cause


def test_a_parsable_reply_of_the_wrong_shape_is_not_called_cut_off():
    """The ceiling explains a syntax error, never a wrong shape."""
    got = runner._reply_fault(reply("[1]", finish="length"), 100, key="tuples")
    assert got[0] == "not_an_object"


def test_a_half_of_a_split_request_is_relabelled_onto_the_whole():
    entries = [{"source": "Q1", "unit_source": "Q2", "quote": "Q1"},
               {"source": "Q 3"}, "not a dict"]
    runner._relabel_sources(entries, 3)
    assert entries[0]["source"] == "Q4" and entries[0]["unit_source"] == "Q5"
    assert entries[0]["quote"] == "Q1", "only source keys are labels"
    assert entries[1]["source"] == "Q6"
    same = [{"source": "Q1"}]
    assert runner._relabel_sources(same, 0) == [{"source": "Q1"}]
