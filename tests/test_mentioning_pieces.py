"""
The text that names a table or figure by its label and number is shown
beside the first search of a value in it (owner decision 2026-11-17, from
the literature on DocFS: a table's scenario or year often stands in the
paragraph that discusses it).

The promises, each with a case that breaks it by construction:

1. The text pieces that name "Tabelle 4" come for a value of table 4, AND
   not for "Tabelle 41" or "Tabelle 4.1", AND not for another table, AND
   an abbreviation of the label ("Tab. 4") names it, AND another kind of
   item ("Abbildung 4") does not.
2. As many as the rule `mentioning_pieces` says, AND 0 shows none, AND a
   piece beside the value or seen is not added again.
3. The labels are the rule `item_labels`: a label not in it names nothing.
"""
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction.addressed import label_names
from docpipe.extraction.engine import Engine
from docpipe.extraction.pipeline import Source

from test_addressed import TABLE, plan_of


def text(owner, body):
    return Source("section", owner, body,
                  {"document_id": 7, "page": owner, "section_title": "T"})


FOUR = text(10, "Tabelle 4 zeigt das Szenario Klimaneutral.")
ABBR = text(11, "Siehe Tab. 4 fuer das Zieljahr.")
FIGURE = text(12, "Abbildung 4 zeigt das Szenario Trend.")
FORTY_ONE = text(13, "Tabelle 41 zeigt das Szenario Trend.")
DOTTED = text(14, "Tabelle 4.1 zeigt das Szenario Trend.")
OTHER = Source("table", 5, "Tabelle 5: Anderes\n| a | b |\n| --- | --- |\n"
                           "| 1 | 2 |", {"document_id": 7, "page": 5})
FIVE = text(15, "Tabelle 5 zeigt das Szenario Basis.")


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def coord_of(owner, seen=()):
    return SimpleNamespace(row=SimpleNamespace(claim={"at": {
        "owner": list(owner), "line": 1}}), seen=set(seen))


def plan():
    return plan_of(TABLE, OTHER, FOUR, ABBR, FIGURE, FORTY_ONE, DOTTED, FIVE,
                   chunk_units=1)


def owners(pieces):
    return [p.owner[1] for p in pieces]


def test_the_text_that_names_the_table_comes_for_its_values():
    p = plan()
    got = Engine.mention_pieces(coord_of(("table", 3)), p, [])
    assert owners(got) == [10, 11]       # not 41, 4.1, Abbildung 4, Tabelle 5
    assert owners(Engine.mention_pieces(coord_of(("table", 5)), p, [])) \
        == [15]
    # The break by construction: a text without the label names nothing.
    assert Engine.mention_pieces(coord_of(("section", 10)), p, []) == []


def test_labels_name_each_other_only_as_an_abbreviation():
    assert label_names("tabelle", "tab.") and label_names("tab", "tabelle")
    assert label_names("abbildung", "abb") and label_names("fig.", "figure")
    assert not label_names("tabelle", "abbildung")
    assert not label_names("tabelle", "karte")


def test_as_many_as_the_rule_says_and_none_twice():
    p = plan()
    with rules.overlaid(mentioning_pieces=1):
        assert owners(Engine.mention_pieces(
            coord_of(("table", 3)), p, [])) == [10]
    with rules.overlaid(mentioning_pieces=0):
        assert Engine.mention_pieces(coord_of(("table", 3)), p, []) == []
    first = [c for c in p.chunks if c.owner == ("section", 10)]
    assert owners(Engine.mention_pieces(coord_of(("table", 3)), p,
                                        first)) == [11]
    seen = {c.key for c in first}
    assert owners(Engine.mention_pieces(coord_of(("table", 3), seen), p,
                                        [])) == [11]


def test_the_labels_are_the_rule():
    p = plan()
    with rules.overlaid(item_labels=["Karte"]):
        assert Engine.mention_pieces(coord_of(("table", 3)), p, []) == []
    with rules.overlaid(item_labels=["Abbildung"]):
        assert Engine.mention_pieces(coord_of(("table", 3)), p, []) == []
