"""A value is a value of its parameter only with the entry it must have
(owner decisions 2026-11-07: the kind of a year, the work of a publication's
value), each promise with a case that breaks it by construction.

1. A value read with another entry is asked nothing after it, AND is asked
   for once more in the conversation of its passage's rounds, told it was
   read wrongly, AND a value named instead is read with its coordinates,
   without a second such question.
2. A value read with the entry it must have goes on to its coordinates, and
   nothing is asked again.
3. The combing asks no coordinate after one it reads as another entry.
4. The graph takes a value only with every such entry read as that entry: a
   value of another work, a year that is no scenario year and a year whose
   kind stayed open stay out of it.
5. A spec whose entry to keep is no entry of its list is refused.
"""
import json
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from docpipe.extraction import combing, fields, reading, runner, survey
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import SpecError, load as load_spec
from profiles.scenarios import kg
from test_graph_from_shapes import OEO, empty_db, oekg

SPEC_PATH = (Path(__file__).resolve().parent.parent / "profiles"
             / "scenarios" / "extraction_spec.json")
SPEC = load_spec(json.loads(SPEC_PATH.read_text(encoding="utf-8")))
YEAR = SPEC.by_uri["scenario_year"]
KIND = next(slot for slot in fields.axis_slots(YEAR)
            if slot.name == "year_kind")
SCENARIO = next(slot for slot in fields.axis_slots(YEAR)
                if slot.name == "scenario")
PUBLISHED = "Published in the year 2018 by BNEF."
LATER = "Revised in the year 2019 by BNEF."
RUNS = "The NEO scenario runs to the year 2050."
SOURCE = Source("section", 4, "\n".join((PUBLISHED, LATER, RUNS)),
                {"document_id": 7, "section_title": "Studies"})


def answered(thread, reply):
    """What the run keeps of an answer: the conversation goes on after it."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


def kind_of(year, kinds):
    entry = kinds[year]
    quote = {"2018": PUBLISHED, "2019": LATER, "2050": RUNS}[year]
    return {"year_kind": {"value": entry, "value_raw": quote.split(" in ")[0],
                          "quote": quote}}


def listed(reply):
    """A values reply as the run asks it (owner decisions 2026-11-08: every
    value of a passage in one answer): a fixture's one value as an answer
    that lists it, {"value": null} as one that lists none; a whole answer,
    or no answer, as given."""
    if not isinstance(reply, dict) or "values" in reply:
        return reply
    if reply.get("value") is None:
        return {"values": [], "incomplete": False}
    return {"values": [reply], "incomplete": False}


def read_years(kinds, again):
    """The reading of the scenario years of SOURCE: the rounds name 2018
    and then none, the question asked again names *again*; *kinds* answers
    the kind of each year. (the rows, the follow-ups of the rounds, the
    coordinates asked per year)."""
    rounds = iter([{"value": "2018", "quote": PUBLISHED}, {"value": None}])
    follows, asked = [], []

    def ask_values(src, parameter, context, read, thread, follow=None,
                   drawn=False):
        follows.append(follow)
        if follow and reading.WRONG in follow:
            return answered(thread, listed(again.pop(0) if again
                                           else {"value": None}))
        return answered(thread, listed(next(rounds)))

    def ask_text(src, parameter, group, slots, row, context, thread,
                 follow=None):
        name = slots[0].name
        year = row.claim["value"]
        if follow is None:
            asked.append((year, name))
        if name == "year_kind":
            return answered(thread, kind_of(year, kinds))
        return answered(thread, {"scenario": {"value": "NEO",
                                              "quote": RUNS}})

    reader = reading.Reader(SPEC, ask_values, ask_text)
    found = survey.Found(True, {("section", 4): survey.Answer(
        ("section", 4), [YEAR.uri], {}, [])}, [])
    reads = reader(7, found, {("section", 4): SOURCE})
    rows = [claim for read in reads for claim in read.claims]
    return rows, follows, asked


def by_value(rows):
    return {row["value"]: row for row in rows}


def test_a_year_read_as_another_year_is_asked_again_and_not_for_its_scenario():
    rows, follows, asked = read_years(
        {"2018": "other year", "2050": "scenario year"},
        [{"value": "2050", "quote": RUNS}])
    years = by_value(rows)
    assert ("2018", "scenario") not in asked
    assert years["2018"]["scenario_state"] == fields.OUT_OF_SLICE
    wrong = [follow[reading.WRONG] for follow in follows
             if follow and reading.WRONG in follow]
    assert [one["value"] for one in wrong] == ["2018"]
    assert wrong[0]["what"]
    # The value named instead is read with its coordinates.
    assert ("2050", "year_kind") in asked and ("2050", "scenario") in asked
    assert years["2050"]["scenario_state"] == fields.READ


def test_a_value_named_instead_is_not_asked_again_a_second_time():
    rows, follows, asked = read_years(
        {"2018": "other year", "2019": "other year"},
        [{"value": "2019", "quote": LATER}])
    assert sum(1 for follow in follows
               if follow and reading.WRONG in follow) == 1
    assert by_value(rows)["2019"]["scenario_state"] == fields.OUT_OF_SLICE
    assert ("2019", "scenario") not in asked


def test_a_scenario_year_goes_on_to_its_scenario_and_is_not_asked_again():
    rows, follows, asked = read_years({"2018": "scenario year"}, [])
    assert not any(follow and reading.WRONG in follow for follow in follows)
    assert ("2018", "scenario") in asked
    assert by_value(rows)["2018"]["scenario_state"] == fields.READ


class Talk:
    """The combing's messages: the coordinate each asks, answered by
    *answers*."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, payload, shape, document_id, source, group=None,
                 example=None, thread=None, follow=None):
        shown = (follow or payload or {}).get(reading.COORDINATES) or {}
        name = next(iter(shown), None)
        self.asked.append(name)
        return answered(thread, {name: self.answers[name]})


def comb(kind):
    quote = "NEO, published in the year 2018 by BNEF."
    talk = Talk({"year_kind": {"value": kind, "value_raw": "published",
                               "quote": quote},
                 "scenario": {"value": "NEO", "quote": quote}})
    claim = {"source": "Q1", "value": "2018", "quote": quote,
             "year_kind_state": fields.SAID_UNSTATED,
             "scenario_state": fields.SAID_UNSTATED}
    comber = combing.Comber(SPEC, talk, None, lambda claim, asked: {})
    comber.comb(7, YEAR, SOURCE, [KIND, SCENARIO], [claim],
                {("section", 4): SOURCE}, [])
    return talk, claim


def test_the_combing_asks_nothing_after_a_year_it_reads_as_another_year():
    talk, claim = comb("other year")
    assert talk.asked == ["year_kind"]
    assert claim["scenario_state"] == fields.OUT_OF_SLICE
    talk, claim = comb("scenario year")
    assert talk.asked == ["year_kind", "scenario"]
    assert claim["scenario_state"] == fields.READ


THIS = "work:this_publication"
SCENARIO_YEAR = OEO + "OEO_00020097"


def harvest(other_year_kind):
    own = {"work": THIS, "work_state": fields.READ}
    return [
        {"parameter": "publication_title", "value": "A Study",
         "quote": "A Study", **own},
        {"parameter": "publication_author", "value": "Ada Lovelace",
         "quote": "Ada Lovelace", **own},
        {"parameter": "publication_author", "value": "Bob Other",
         "quote": "Developed by: Bob Other", "work": "out:another_work",
         "work_state": fields.READ},
        {"parameter": "scenario_year", "value": "2030", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol reaches 2030.",
         "scenario_quote": "CurPol reaches 2030.",
         "year_kind": SCENARIO_YEAR, "year_kind_state": fields.READ},
        {"parameter": "scenario_year", "value": "2018", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol, published 2018.",
         "scenario_quote": "CurPol, published 2018.",
         "year_kind": other_year_kind, "year_kind_state": fields.READ},
        {"parameter": "scenario_year", "value": "2040", "scenario": "CurPol",
         "scenario_raw": "CurPol", "quote": "CurPol in 2040.",
         "scenario_quote": "CurPol in 2040.",
         "year_kind_state": fields.UNANSWERED},
    ]


def graph_of(rows):
    serializer = kg.make_serializer(empty_db(), model=oekg())
    text = serializer("doc", rows)
    graph = Graph().parse(data=text, format="turtle")
    years = {str(o)[:4] for o in graph.objects(
        predicate=URIRef(OEO + "OEO_00020440"))}
    return text, years


def test_the_graph_takes_only_values_read_with_the_entry_they_must_have():
    rows = harvest("out:other_year")
    text, years = graph_of(rows)
    assert years == {"2030"}
    assert "Ada Lovelace" in text and "Bob Other" not in text
    assert kg.held_back(rows[2]) == "work:out:another_work"
    assert kg.held_back(rows[5]) == f"year_kind:{fields.UNANSWERED}"
    assert kg.held_back(rows[1]) is None
    # The same harvest with 2018 read as a scenario year: it is taken.
    _text, years = graph_of(harvest(SCENARIO_YEAR))
    assert years == {"2030", "2018"}


def test_a_spec_whose_entry_to_keep_is_none_of_its_list_is_refused():
    raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    year = next(p for p in raw["parameters"] if p["uri"] == "scenario_year")
    year["axes"]["year_kind"]["keep"] = "out:no_such_entry"
    with pytest.raises(SpecError):
        load_spec(raw)
