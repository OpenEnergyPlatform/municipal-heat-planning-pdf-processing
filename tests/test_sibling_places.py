"""
Where a dimension was read for one value of a table or section, the search
of the same dimension of another value of it looks there first (owner
decision 2026-11-17, from the literature on agentic retrieval: the
relevance of a place carries over to its neighbours and to the next round).

The promises, each with a case that breaks it by construction:

1. A dimension the model read for a value is noted at the piece of its
   quote, under the value's passage, AND a dimension not read is noted
   nowhere.
2. The first search of the same dimension of another value of that passage
   shows that piece beside the neighbours, the piece most values read it in
   first, AND as many as the rule `sibling_places` says, AND 0 shows the
   neighbours alone, AND a value of another passage gets none, AND a piece
   already beside the value or shown is not added again.
"""
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import fields
from docpipe.extraction.engine import Engine
from docpipe.extraction.pipeline import Source

from test_addressed import (ENERGY, TABLE, TEXT, Model, coordinate_answers,
                            plan_of, reader_of)

NOTE = Source("section", 9, "Alle Werte gelten für das Zielszenario 2040. "
                            "Die Tabellen zeigen den Stand. Danach folgt "
                            "die Bilanz.",
              {"document_id": 7, "page": 9, "section_title": "Szenario"})


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def test_a_dimension_read_is_noted_at_the_piece_of_its_quote():
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if p["passage"]["kind"] == "table" else {"found": []},
        coord=coordinate_answers(year={"at": "1", "words": "2021"}))
    plan = plan_of(TABLE)
    reads = reader_of(model)(plan, [ENERGY])
    (claim,) = [c for r in reads for c in r.claims]
    assert claim["year_state"] == fields.READ
    (piece,) = plan.read_near("year", ("table", 3))
    assert piece[:2] == ("table", 3)
    # The break by construction: a dimension the reply did not read (the
    # unit stays open for want of an answer) is noted nowhere.
    assert claim.get("carrier_state") != fields.READ
    assert plan.read_near("carrier", ("table", 3)) == []


def coord_of(owner, name="year", seen=()):
    return SimpleNamespace(row=SimpleNamespace(claim={"at": {
        "owner": list(owner), "line": 1}}), slot=SimpleNamespace(name=name),
        seen=set(seen))


def test_the_sibling_s_place_comes_first_as_far_as_the_rule_says():
    plan = plan_of(TABLE, NOTE, TEXT, chunk_units=1)
    note = [c for c in plan.chunks if c.owner == ("section", 9)]
    text = [c for c in plan.chunks if c.owner == ("section", 2)]
    # Two values of table 3 read the year in the first sentence of the
    # note, one in a sentence of the text.
    plan.note_read("year", ("table", 3), note[0].key)
    plan.note_read("year", ("table", 3), text[1].key)
    plan.note_read("year", ("table", 3), note[0].key)
    got = Engine.read_near(coord_of(("table", 3)), plan, [])
    assert [c.key for c in got] == [note[0].key, text[1].key]
    with rules.overlaid(sibling_places=1):
        got = Engine.read_near(coord_of(("table", 3)), plan, [])
    assert [c.key for c in got] == [note[0].key]
    with rules.overlaid(sibling_places=0):
        assert Engine.read_near(coord_of(("table", 3)), plan, []) == []
    # Another dimension, another passage: none.
    assert Engine.read_near(coord_of(("table", 3), "scenario"), plan,
                            []) == []
    assert Engine.read_near(coord_of(("section", 2)), plan, []) == []
    # A piece beside the value or shown before is not added again.
    got = Engine.read_near(coord_of(("table", 3), seen=[text[1].key]),
                           plan, [note[0]])
    assert got == []


def test_a_quote_finds_the_piece_of_its_line():
    plan = plan_of(NOTE, chunk_units=1)
    piece = plan.piece_of_quote(["section", 9], "Danach folgt die Bilanz.",
                                False)
    assert piece is not None and piece.numbers == (3,)
    assert plan.piece_of_quote(["section", 9], "Steht nirgends.",
                               False) is None
    assert plan.piece_of_quote(["section", 77], "Danach folgt die Bilanz.",
                               False) is None
