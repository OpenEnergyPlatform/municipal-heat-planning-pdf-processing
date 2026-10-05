"""A question for a number, answered from the harvest.

What is promised, sentence by sentence:

  * the parameter and every coordinate are one closed question each over
    the spec's own lists AND asked once;
  * a coordinate the question does not name narrows nothing AND an answer
    outside the list is no answer;
  * the values come back as the harvest holds them, with quote, page and
    level, for one document or for all of them;
  * the route says why it did not answer: no harvest, no parameter named,
    nothing held for what was named;
  * the worst level still wanted is the caller's to say;
  * a value is shown to a model as one line with its document, its page
    and its quote.
"""
import pytest

from docpipe.extraction import fields
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL
from docpipe.inference import kg_route, values_route
from docpipe.serve.values import Values

P, Q = "energy_consumption", "emissions"


def parameter(uri, label):
    return {
        "uri": uri, "label": label,
        "description": "What the document states for it, per year and "
                       "energy carrier.",
        "value_type": "float", "unit_target": "MWh/a",
        "units_accepted": {"MWh/a": 1, "GWh/a": 1000},
        "axes": {
            "carrier": {"vocabulary": {"oeo:gas": ["natural gas", "Erdgas"],
                                       "oeo:coal": ["coal", "Kohle"]}},
            "year": {"type": "int"}},
        "example": {"source": "| Erdgas | 241 GWh/a | 2040 |", "tuples": [{
            "value": 241.0, "unit_raw": "GWh/a", "carrier": "oeo:gas",
            "carrier_raw": "Erdgas", "year": 2040,
            "quote": "| Erdgas | 241 GWh/a | 2040 |"}]},
    }


@pytest.fixture(scope="module")
def spec():
    return load_spec({"parameters": [
        parameter(P, "Final energy consumption"),
        parameter(Q, "Greenhouse gas emissions")]})


def row(value, carrier="oeo:gas", year=2040, uri=P, tier=TIER_TEXT):
    return {"kind": "tuple", "parameter": uri, "value": value,
            "value_raw": str(value), "unit": "GWh/a", "tier": tier,
            "quote": f"| {carrier} | {value} | {year} |",
            "provenance": {"document_id": 1, "owner_kind": "table",
                           "owner_id": 4, "page": 12},
            "carrier": carrier, "carrier_state": fields.READ,
            "year": year, "year_state": fields.READ}


@pytest.fixture
def store(spec):
    return Values({
        "kassel": [row(241.0), row(180.0, year=2030),
                   row(5.0, carrier="oeo:coal", tier=TIER_VISUAL),
                   row(77.0, uri=Q)],
        "marburg": [row(90.0)],
    }, spec=spec)


class Asked:
    """Answers each closed question from a table and notes what was asked."""

    def __init__(self, **answers):
        self.answers = answers
        self.slots = []

    def __call__(self, task, slot):
        self.slots.append(slot.name)
        return self.answers.get(slot.name)


def test_the_question_is_turned_into_closed_questions_asked_once(store):
    ask = Asked(parameter="Final energy consumption", carrier="natural gas",
                year="in 2040")
    got = values_route.answer_from_values("How much gas in 2040?", store,
                                          ask=ask, document="kassel")
    assert ask.slots.count("parameter") == 1
    assert sorted(ask.slots) == ["carrier", "parameter", "year"]
    assert got["route"] == "values" and got["reason"] is None
    assert got["parameter"] == P
    assert got["coordinates"] == {"carrier": "oeo:gas", "year": 2040}
    (value,) = got["values"]
    assert (value["value"], value["unit"], value["page"]) == (
        241.0, "GWh/a", 12)
    assert value["quote"] == "| oeo:gas | 241.0 | 2040 |"
    assert value["level"] == "A" and got["total"] == 1


def test_a_coordinate_the_question_does_not_name_narrows_nothing(store):
    ask = Asked(parameter="Final energy consumption", carrier="out:unstated")
    got = values_route.answer_from_values("Energy use?", store, ask=ask,
                                          document="kassel")
    assert got["coordinates"] == {}
    assert sorted(value["value"] for value in got["values"]) \
        == [5.0, 180.0, 241.0]


def test_an_answer_outside_the_list_is_no_answer(store):
    ask = Asked(parameter="Final energy consumption", carrier="hydrogen",
                year="soon")
    got = values_route.answer_from_values("Hydrogen soon?", store, ask=ask,
                                          document="kassel")
    assert got["coordinates"] == {} and got["total"] == 3


def test_without_a_document_the_whole_corpus_answers(store):
    ask = Asked(parameter="Final energy consumption", year="2040",
                carrier="Erdgas")                   # a spelling of the entry
    got = values_route.answer_from_values("Gas in 2040?", store, ask=ask)
    assert sorted((value["document"], value["value"])
                  for value in got["values"]) == [("kassel", 241.0),
                                                  ("marburg", 90.0)]


def test_the_worst_level_still_wanted_is_the_callers(store):
    ask = Asked(parameter="Final energy consumption")
    everything = values_route.answer_from_values("Energy?", store, ask=ask,
                                                 document="kassel")
    stated = values_route.answer_from_values("Energy?", store, ask=ask,
                                             document="kassel", level="A")
    assert (everything["total"], stated["total"]) == (3, 2)
    assert all(value["level"] == "A" for value in stated["values"])


def test_the_number_of_values_shown_is_limited_and_the_total_is_said(store):
    ask = Asked(parameter="Final energy consumption")
    got = values_route.answer_from_values("Energy?", store, ask=ask,
                                          limit=2)
    assert len(got["values"]) == 2 and got["total"] == 4


@pytest.mark.parametrize("answers, document, reason, parameter", [
    ({}, "kassel", "no_parameter", None),
    ({"parameter": "Heat load"}, "kassel", "no_parameter", None),
    ({"parameter": "Greenhouse gas emissions"}, "marburg", "no_values", Q),
    ({"parameter": "Final energy consumption", "year": "1990"}, "kassel",
     "no_values", P),
    ({"parameter": "Final energy consumption"}, "nowhere", "no_values", P),
])
def test_the_route_says_why_it_did_not_answer(store, answers, document,
                                              reason, parameter):
    got = values_route.answer_from_values("?", store, ask=Asked(**answers),
                                          document=document)
    assert got["route"] == "rag" and got["reason"] == reason
    assert got["values"] == [] and got["total"] == 0
    assert got["parameter"] == parameter
    assert reason in values_route.REASONS


def test_no_harvest_no_route_and_no_question_asked(spec):
    for nothing in (None, Values({}, spec=spec), Values({"a": [row(1.0)]})):
        ask = Asked(parameter="Final energy consumption")
        got = values_route.answer_from_values("?", nothing, ask=ask)
        assert (got["route"], got["reason"]) == ("rag", "no_store")
        assert ask.slots == []


def test_the_graph_route_still_asks_the_same_way(spec):
    ask = Asked(parameter="Final energy consumption", carrier="coal",
                year="2030")
    assert kg_route.to_coordinates("?", spec, ("year",), ask) \
        == {"year": 2030}
    assert "carrier" not in ask.slots               # not one of its axes
    assert kg_route.to_coordinates("?", spec, ("year",), Asked()) == {}


def test_a_value_as_a_line_a_model_is_shown(store):
    ask = Asked(parameter="Final energy consumption", carrier="coal")
    got = values_route.answer_from_values("Coal?", store, ask=ask)
    (line,) = values_route.as_passages(got["values"])
    assert line["text"] == ("Final energy consumption: 5.0 GWh/a "
                            "(carrier: coal, year: 2040)")
    assert line["where"] == "kassel, p. 12"
    assert line["quote"] == "| oeo:coal | 5.0 | 2040 |"
    assert (line["level"], line["reasons"]) == ("B", [])
    assert line["id"] == got["values"][0]["id"]
