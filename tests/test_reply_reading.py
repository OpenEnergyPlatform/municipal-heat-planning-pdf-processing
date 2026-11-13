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


