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
  * the parameter is chosen with the question the caller words for a
    person's question, where it gives one, AND with the spec's own
    where it does not;
  * an answer uses a value where a statement quotes the value's quote,
    or a part of it that names the value as the plan writes it, AND
    not where they only share a passage.
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
        "units_accepted": {
            "MWh/a": {"factor": 1, "names_period": True},
            "GWh/a": {"factor": 1000, "names_period": True}},
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


class Heard(Asked):
    """Also notes the question each slot was asked with."""

    def __init__(self, **answers):
        super().__init__(**answers)
        self.questions = {}

    def __call__(self, task, slot):
        self.questions[slot.name] = slot.question
        return super().__call__(task, slot)


def test_the_parameter_is_chosen_with_the_callers_question(store, spec):
    heard = Heard(parameter="Final energy consumption")
    values_route.answer_from_values("Who made it?", store, ask=heard,
                                    parameter_question="What is asked for?")
    assert heard.questions["parameter"] == "What is asked for?"
    heard = Heard(parameter="Final energy consumption")
    values_route.answer_from_values("Who made it?", store, ask=heard)
    assert heard.questions["parameter"] == spec.parameter_question


def found(quote, raw):
    return {"id": raw, "quote": quote, "value_raw": raw}


TABLE = [found("| Summe | 125.000 |", "125.000"),
         found("| Holz | 7.872 |", "7.872"),
         found("| Solar | 4.135 |", "4.135")]


def test_an_answer_uses_the_values_its_statements_quote():
    said = [{"quote": "| Summe | 125.000 |", "citation": 1}]
    used = values_route.used_values(TABLE, said)
    assert [(value["id"], value["n"]) for value in used] == [("125.000", 1)]


def test_a_part_of_the_quote_counts_only_where_it_names_the_value():
    assert [v["id"] for v in values_route.used_values(
        TABLE, [{"quote": "Summe | 125.000", "citation": 2}])] == ["125.000"]
    # a part that names no value of the row is not a use of it
    assert values_route.used_values(
        TABLE, [{"quote": "Summe", "citation": 2}]) == []


def test_sharing_a_passage_is_not_using_its_values():
    """The twelve carriers of one table are one passage; an answer that
    quotes another passage of it uses none of them."""
    said = [{"quote": "Bis 2045 sinkt der Gesamtwert", "citation": 1}]
    assert values_route.used_values(TABLE, said) == []
    assert values_route.used_values(TABLE, []) == []


def test_parameter_of_asks_with_the_question_it_is_given(spec):
    heard = Heard(parameter="Greenhouse gas emissions")
    chosen = kg_route.parameter_of("?", spec, heard, question="Asked for?")
    assert chosen.uri == Q and heard.questions["parameter"] == "Asked for?"
    kg_route.parameter_of("?", spec, heard)
    assert heard.questions["parameter"] == spec.parameter_question


def test_a_persons_question_sees_what_each_parameter_means(spec):
    """The spec's labels are its own words; with the caller's question every
    entry carries the first sentence of its description, and without it the
    list stays as the extraction asks it."""
    seen = {}

    def ask(task, slot):
        seen[bool(slot.question == "Asked for?")] = {
            option.uri: option.definition for option in slot.options}
        return None

    kg_route.parameter_of("?", spec, ask, question="Asked for?")
    kg_route.parameter_of("?", spec, ask)
    assert seen[True][P] == ("What the document states for it, per year "
                             "and energy carrier.")
    assert set(seen[False].values()) == {""}
    assert kg_route._first_sentence("One. Two.") == "One."
    assert kg_route._first_sentence("No stop") == "No stop"
