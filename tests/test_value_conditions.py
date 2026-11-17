"""
A value that breaks a condition of the ontology is read a second time and
marked, and nothing is taken away for it (owner decision 2026-11-17, from
the literature on correcting extracted facts after reading: what breaks a
condition of the ontology is read again).

The promises, each with a case that breaks it by construction:

1. A value above the most the rule `value_bounds` gives its field breaks
   "over_bound", AND one at or below it breaks none, AND without the rule
   none is checked.
2. A part greater than its whole among the values read before it breaks
   "part_over_whole", the whole being the value with the entry the rule
   `part_of_whole` names, AND so does a whole smaller than a part read
   before it, AND another year or a smaller part breaks none, AND without
   the rule no part is compared.
3. The check of a value that breaks one reads it a second time and marks
   it, AND keeps it where that reading does not agree.
"""
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import engine as engine_map
from docpipe.extraction.engine import Engine
from docpipe.extraction.pipeline import Row
from docpipe.extraction.trust import REVIEW_DISAGREE

from test_addressed import ENERGY, TABLE, plan_of

WHOLES = {"carrier": "out:total"}


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def value(target, year=2020, carrier="OEO_1"):
    return {"value_target": float(target), "year": year, "carrier": carrier}


def test_a_value_above_the_bound_of_its_field_breaks_it():
    plan = plan_of(TABLE)
    with rules.overlaid(value_bounds=[{"parameter": "energy",
                                       "at_most": "500"}]):
        assert Engine.conditions(plan, ENERGY, value(600)) == ["over_bound"]
        assert Engine.conditions(plan, ENERGY, value(500)) == []
    assert Engine.conditions(plan_of(TABLE), ENERGY, value(600)) == []


def test_a_part_greater_than_its_whole_breaks_it_either_way_round():
    plan = plan_of(TABLE)
    with rules.overlaid(part_of_whole=WHOLES):
        assert Engine.conditions(plan, ENERGY,
                                 value(1000, carrier="out:total")) == []
        assert Engine.conditions(plan, ENERGY, value(1200)) == \
            ["part_over_whole"]
        assert Engine.conditions(plan, ENERGY, value(300, carrier="OEO_2")) \
            == []
        assert Engine.conditions(plan, ENERGY, value(5000, year=2030)) == []
    plan = plan_of(TABLE)
    with rules.overlaid(part_of_whole=WHOLES):
        assert Engine.conditions(plan, ENERGY, value(1200)) == []
        assert Engine.conditions(plan, ENERGY,
                                 value(1000, carrier="out:total")) == \
            ["part_over_whole"]
    plan = plan_of(TABLE)
    with rules.overlaid(part_of_whole={}):
        Engine.conditions(plan, ENERGY, value(1000, carrier="out:total"))
        assert Engine.conditions(plan, ENERGY, value(1200)) == []


def test_the_check_reads_it_again_marks_it_and_keeps_it():
    plan = plan_of(TABLE)
    claim = {"parameter": "energy", "value": 600, "value_target": 600.0,
             "quote": "| Rathaus | 600 |", "year": 2020, "carrier": "OEO_1"}
    row = Row("r", 0, claim)
    asked: list = []

    def review(view, parameter, sources):
        asked.append(sources)
        view.setdefault("flags", []).append(REVIEW_DISAGREE)
        return REVIEW_DISAGREE
    source = SimpleNamespace(owner_kind="table", owner_id=3, text="")
    checking = SimpleNamespace(
        check=lambda view, parameter, slots, shown: None,
        owner_sources=lambda pairs: {},
        review_sources=lambda view: [source], review=review)
    fake = SimpleNamespace(slot_sequence=lambda parameter: [],
                           reader=SimpleNamespace(spec=SimpleNamespace(
                               coordinates=None)),
                           run_steps=lambda steps, scope: None)
    item = SimpleNamespace(read=SimpleNamespace(batch=SimpleNamespace(
        items=[SimpleNamespace(source=source)], document_id=7)),
        rows=[row], clone=lambda one: one)
    scope = SimpleNamespace(get=lambda name: {
        "doc": SimpleNamespace(plan=plan, seen_of={})}.get(name))
    with rules.overlaid(value_bounds=[{"parameter": "energy",
                                       "at_most": "500"}]):
        engine_map.Engine.check_row(fake, checking, scope, item, row,
                                    ENERGY, None)
    assert asked == [[source]]
    assert "condition:over_bound" in claim["flags"]
    assert REVIEW_DISAGREE in claim["flags"]
    assert not claim.get("_why")
    # The break by construction: a value that breaks nothing is not read
    # again.
    asked.clear()
    claim2 = {**claim, "value_target": 400.0, "flags": []}
    with rules.overlaid(value_bounds=[{"parameter": "energy",
                                       "at_most": "500"}]):
        engine_map.Engine.check_row(fake, checking, scope, item,
                                    Row("s", 0, claim2), ENERGY, None)
    assert asked == [] and claim2["flags"] == []
