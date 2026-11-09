"""Each request is sent the words of its own task (thread.py, owner
decisions 2026-11-07).

Promise: the system prompt of a request is what every request of its kind
is told AND the part of each field its message carries, never the words of
a follow-up; a follow-up of the compute step carries the words of each of
its fields AND those fields as JSON AND the reply of its request where its
words show one; a field whose follow-ups have no words, or a part marked
twice, stops the run at its start, and an empty follow-up is an error.

Each promise has a case that breaks it by construction beside the one that
keeps it.
"""
import json
from pathlib import Path

import pytest

from docpipe.extraction import thread
from docpipe.prompts import Prompt

TEXT = """Gemeinsam.

<!-- with: table_before -->
Die Tabelle davor.

<!-- follow-up: corrections -->
Korrektur.

<!-- with: whole_table around -->
Ganze Tabelle.

<!-- follow-up: more hits -->
Mehr.

<!-- follow-up: next -->
Der nächste Wert, so: {{example}}
"""
FOLLOWS = ("corrections", "more", "hits", "next")


def prompt_of(text: str = TEXT) -> Prompt:
    return Prompt(id="extraction/read_values", text=text, meta={}, sha256="",
                  path=Path("read_values.md"))


PARTS = thread.cut(prompt_of(), follows=FOLLOWS)


def test_the_system_prompt_is_the_common_part_and_the_parts_it_carries():
    assert PARTS.system().text == "Gemeinsam.\n"
    assert PARTS.system({"table_before": "T"}).text \
        == "Gemeinsam.\n\nDie Tabelle davor.\n"
    # In the order of the file, a part once whichever of its fields come.
    assert PARTS.system({"around": 1, "whole_table": 1,
                         "table_before": 1}).text \
        == "Gemeinsam.\n\nDie Tabelle davor.\n\nGanze Tabelle.\n"
    # The words of a follow-up never, whatever the first message carries.
    assert PARTS.system({key: 1 for key in FOLLOWS}).text == "Gemeinsam.\n"


def test_a_follow_up_carries_the_words_of_its_fields_and_the_fields():
    said = PARTS.follow_up({"corrections": [{"what": "x"}]})
    words, data = said.split("\n\n", 1)
    assert words == "Korrektur."
    assert json.loads(data) == {"corrections": [{"what": "x"}]}
    # One part for two of its fields, once.
    both = PARTS.follow_up({"more": [1], "hits": [2]})
    assert both.count("Mehr.") == 1
    assert json.loads(both.split("\n\n", 1)[1]) == {"more": [1], "hits": [2]}
    # A field without a value is told by its words alone, with the reply of
    # the request where they show one, and only there.
    assert PARTS.follow_up({"next": None}, {"value": 1}) \
        == 'Der nächste Wert, so: {"value":1}'
    assert PARTS.follow_up({"corrections": ["x"]}, {"value": 1}) \
        == PARTS.follow_up({"corrections": ["x"]})
    # The failures by construction: nothing to carry, a field without
    # words, words that show a reply and none to show.
    with pytest.raises(ValueError):
        PARTS.follow_up({})
    with pytest.raises(LookupError, match="around"):
        PARTS.follow_up({"around": "x"})
    with pytest.raises(KeyError):
        PARTS.follow_up({"next": None})


def test_a_prompt_that_cannot_word_its_follow_ups_stops_at_the_start():
    thread.cut(prompt_of(), follows=FOLLOWS)
    # "next" only as a part of the system prompt: no words to follow with.
    with pytest.raises(LookupError, match="next"):
        thread.cut(prompt_of(TEXT.replace("<!-- follow-up: next -->",
                                          "<!-- with: next -->")),
                   follows=FOLLOWS)
    # A part marked twice is no prompt either.
    with pytest.raises(LookupError, match="corrections"):
        thread.cut(prompt_of(TEXT + "\n<!-- follow-up: corrections -->\n"
                                    "Noch einmal.\n"))
