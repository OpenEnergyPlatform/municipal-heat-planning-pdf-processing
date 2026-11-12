"""
The rules of the numbered lines a request shows (`units.py`), each read
where it is used and set at a step of its kind: the letters of the blocks
beside a value's own passage, the marks that end a sentence, the words that
join the head rows over one cell.

The promise of each: the value the step sets decides what the code makes,
AND the standard gives today's result, AND a value that breaks the promise
by construction (a letter another block uses, no mark at all) is not
followed blindly.

Author: Felix Vossel
"""
import pytest

from docpipe import rules
from docpipe.extraction import addressed, units
from docpipe.extraction.pipeline import Source
from docpipe.extraction.units import Line

from test_addressed import TABLE, TEXT, TITLE, plan_of
from conftest import step_node


def at(kind: str, values: dict):
    """What the engine does around a box of *kind* that sets *values*."""
    return rules.in_step(rules.stepped(step_node(kind), values))


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


CLAIM = {"at": {"owner": ["table", 3], "line": 3}, "value": 1}


def shown_of(plan=None):
    plan = plan or plan_of(TITLE, TEXT, TABLE)
    plan.settings = [(Line(1, "Basisjahr 2021"), TEXT)]
    shown, payload = addressed.show_value(plan, CLAIM)
    return shown, payload


# -- the letters of the blocks ----------------------------------------------

def test_the_letter_of_the_headings_names_them_in_every_request():
    _shown, payload = shown_of()
    assert payload["headings"][0].startswith("H1 ")        # the standard
    with at("coord", {"letter_headings": "Z"}):
        _shown, payload = shown_of()
        assert payload["headings"][0].startswith("Z1 ")
        assert units.letter_headings() == "Z"
    assert units.letter_headings() == "H"                  # outside the step


def test_the_letter_of_the_title_page_names_its_lines():
    _shown, payload = shown_of()
    assert [line.split(" ")[0] for line in payload["title_page"]] == [
        "T1", "T2"]
    with at("find", {"letter_title_page": "Q"}):
        _shown, payload = shown_of()
        assert [line.split(" ")[0] for line in payload["title_page"]] == [
            "Q1", "Q2"]


def test_the_letter_of_the_settings_names_the_fields_of_the_document():
    _shown, payload = shown_of()
    assert payload["settings"] == ["F1 Basisjahr 2021"]
    with at("search", {"letter_settings": "S"}):
        _shown, payload = shown_of()
        assert payload["settings"] == ["S1 Basisjahr 2021"]


def test_a_letter_a_block_has_is_no_letter_of_the_pieces_beside_it():
    # the failure by construction: the letters of the blocks are kept out of
    # those of the other passages, whatever a step sets, so that no letter
    # names two blocks
    assert "H" not in units.letters_others()
    assert "A" in units.letters_others()
    with at("search", {"letter_headings": "A", "letter_settings": "B"}):
        assert "A" not in units.letters_others()
        assert "B" not in units.letters_others()
        assert "C" in units.letters_others()


# -- the marks that end a sentence --------------------------------------------

def test_the_marks_that_end_a_sentence_are_the_rule_s():
    text = "Eins ist gut. Zwei ist gut! Drei? Vier ist gut."
    assert units.sentences_of(text) == [
        "Eins ist gut.", "Zwei ist gut!", "Drei?", "Vier ist gut."]
    with at("split", {"sentence_marks": "."}):
        assert units.sentences_of(text) == [
            "Eins ist gut.", "Zwei ist gut! Drei? Vier ist gut."]
    # the failure by construction: a mark that no sentence ends in, and one
    # that means something in a pattern, end nothing and break nothing
    with at("split", {"sentence_marks": "^]"}):
        assert units.sentences_of(text) == [text]
    with at("split", {"sentence_marks": "?"}):
        assert units.sentences_of(text) == [
            "Eins ist gut. Zwei ist gut! Drei?", "Vier ist gut."]
    assert len(units.sentences_of(text)) == 4          # the standard again


# -- the words over one cell --------------------------------------------------

def test_the_head_rows_over_one_cell_are_joined_by_the_rule_s_words():
    table = Source("table", 9, "| 2030 | |\n| Bestand | Bedarf |\n"
                               "| --- | --- |\n| 1 | 2 |", {"page": 1})
    passage = units.passage_of(table)
    assert passage.head_of(1) == "2030 / Bestand"
    with at("coord", {"head_joiner": " | "}):
        assert passage.head_of(1) == "2030 | Bestand"
    # the failure by construction: a column with one head row has nothing
    # to join, whatever the joiner is
    with at("coord", {"head_joiner": " | "}):
        assert passage.head_of(2) == "Bedarf"
