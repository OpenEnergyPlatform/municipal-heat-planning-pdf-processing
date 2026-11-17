"""
The order in which an answer writes its keys is a setting (owner decision
2026-11-17, from the literature on forced formats: the order and names of an
answer's keys can change what a model writes; for our model the direction
is open until measured).

The promises, each with a case that breaks it by construction:

1. With `reply_order` at its standard every reply form keeps the line
   before its words, AND "words_first" puts "words" first in every object
   of a form that has it, nested ones too, AND an object without words
   stays as it is.
2. The example a prompt shows follows the same order.
"""
import json

import pytest

from docpipe import rules
from docpipe.extraction import addressed, runner


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def keys(form):
    return list(form["json_schema"]["schema"]["properties"])


def test_the_standard_keeps_the_line_before_its_words():
    assert keys(addressed.coord_format(False)) == ["at", "words"]
    with rules.overlaid(reply_order="words_first"):
        assert keys(addressed.coord_format(False)) == ["words", "at"]
        found = addressed.found_format()["json_schema"]["schema"]
        assert list(found["properties"]["found"]["items"][
            "properties"]) == ["words", "at"]
        # A form without words stays as it is.
        assert keys(addressed.phrase_format()) == ["phrase"]


def test_the_example_follows_the_order_of_the_form():
    class Prompt:
        id, text, placeholders = "x", "Antwort: {{example}}", ("example",)

        @staticmethod
        def render(example):
            return f"Antwort: {example}"
    prompt = Prompt()
    example = {"found": [{"at": "3.2", "words": "1.200"}]}
    standard = runner.system_text(prompt, example)
    with rules.overlaid(reply_order="words_first"):
        turned = runner.system_text(prompt, example)
    assert json.dumps(example["found"][0], separators=(",", ":")) in standard
    assert '{"words":"1.200","at":"3.2"}' in turned
