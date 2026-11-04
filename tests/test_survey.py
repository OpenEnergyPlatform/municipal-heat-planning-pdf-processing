"""The spec puts every coordinate in exactly one group, and the survey of a
whole plan packs at most one figure and two pages of text into a context,
asks for every passage of it, takes a parameter only on a quote from its own
passage and a frame tuple only on quotes that carry it, and is read again
from disk under its own key.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import copy
import json
from pathlib import Path

import pytest

from docpipe.extraction import runner, survey
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import SpecError, load as load_spec

RAW = json.loads((Path(__file__).resolve().parent.parent / "profiles" / "kwp"
                  / "extraction_spec.json").read_text(encoding="utf-8"))
SPEC = load_spec(RAW)
PARAMETERS = survey.parameters_of(SPEC)
SLOTS = survey.tuple_slots(SPEC)


def with_groups(change) -> dict:
    raw = copy.deepcopy(RAW)
    change(raw["groups"])
    return raw


def passage(kind, number, text, page=1):
    return Source(kind, number, text, {"document_id": 7, "page": page,
                                       "section_title": "Bilanz"})


# -- the groups of the spec ----------------------------------------------------

def test_every_coordinate_of_the_spec_is_in_exactly_one_group():
    grouped = [c for group in SPEC.groups.values() for c in group.coordinates]
    assert len(grouped) == len(set(grouped))
    assert [g.name for g in SPEC.groups_read_in("survey")] == ["frame"]


def test_a_coordinate_in_no_group_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].remove("whole"))
    with pytest.raises(SpecError, match="whole"):
        load_spec(raw)


def test_a_coordinate_in_two_groups_is_refused():
    raw = with_groups(lambda g: g["number"]["coordinates"].append("year"))
    with pytest.raises(SpecError, match="already in group"):
        load_spec(raw)


def test_a_name_that_is_no_coordinate_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].append("colour"))
    with pytest.raises(SpecError, match="no coordinate"):
        load_spec(raw)


def test_a_group_read_by_no_step_is_refused():
    raw = with_groups(lambda g: g["frame"].update(read_in="search"))
    with pytest.raises(SpecError, match="read_in"):
        load_spec(raw)


def test_a_survey_group_no_parameter_has_whole_is_refused():
    def odd(groups):
        for name in ("whole", "aggregation"):
            groups["context"]["coordinates"].remove(name)
        groups["odd"] = {"coordinates": ["whole", "aggregation"],
                         "read_in": "survey", "where": "irgendwo"}
    with pytest.raises(SpecError, match="one parameter"):
        load_spec(with_groups(odd))


# -- contexts ------------------------------------------------------------------

def test_a_context_holds_one_figure_and_two_pages_and_misses_no_passage():
    passages = [passage("section", 1, "a" * 300),
                passage("figure", 2, "Abbildung " * 50),
                passage("figure", 3, "Abbildung " * 50),
                passage("section", 4, "b" * 300),
                passage("table", 5, "c" * 450)]
    contexts = survey.contexts_of(passages, 700)
    for context in contexts:
        assert sum(p.owner_kind == "figure" for p in context) <= 1
        assert sum(len(p.text) for p in context
                   if p.owner_kind != "figure") <= 700
    assert [p.owner_id for c in contexts for p in c] == [1, 2, 3, 4, 5]


def test_a_passage_longer_than_two_pages_goes_in_pieces_that_keep_it():
    long = passage("section", 9, ("Zeile mit Text\n" * 100))
    contexts = survey.contexts_of([long], 300)
    assert len(contexts) > 1
    assert all(len(c) == 1 and c[0].owner_id == 9 and len(c[0].text) <= 300
               for c in contexts)
    assert "".join(c[0].text for c in contexts) == long.text


def test_two_pages_are_twice_the_plans_text_per_page_without_figures():
    passages = [passage("section", 1, "a" * 4000),
                passage("figure", 2, "b" * 9000)]
    assert survey.budget_of(passages, 4) == 2000


# -- the reply -----------------------------------------------------------------

def test_the_grammar_wants_an_answer_for_every_passage():
    context = [passage("section", 1, "x"), passage("table", 2, "y")]
    shape = survey.response_format(context, PARAMETERS, SLOTS)
    schema = shape["json_schema"]["schema"]["properties"]["passages"]
    assert schema["required"] == ["P1", "P2"]


TABLE = ("Tabelle 3: Treibhausgasemissionen der Stadt im Jahr 2022\n"
         "| Erdgas | 1.234 |")
TEXT = "Die Stadt liegt an einem Kanal und hat viele Brücken."


def read(entries):
    context = [passage("table", 1, TABLE), passage("section", 2, TEXT)]
    return survey.read_reply({"passages": entries}, context, PARAMETERS,
                             SLOTS, runner.frame_pairs)


def test_a_parameter_is_taken_on_a_quote_from_its_own_passage():
    answers, _ = read({"P1": {"parameters": ["emission"],
                              "quote": "Treibhausgasemissionen der Stadt"},
                       "P2": {"parameters": ["out:none"]}})
    assert answers[0].parameters == ["emission"]
    assert answers[1].parameters == []


def test_a_parameter_quoted_from_another_passage_or_too_short_is_not():
    answers, _ = read({"P1": {"parameters": ["emission"],
                              "quote": "an einem Kanal"},
                       "P2": {"parameters": ["emission"], "quote": "Die"}})
    assert answers[0].parameters == [] and answers[1].parameters == []
    assert [d["why"] for a in answers for d in a.dropped] == [
        "quote not in its passage", "quote too short"]


def frame(year, year_quote):
    return [{"scenario": "Bestand", "scenario_quote": "im Jahr 2022",
             "scenario_raw": "im Jahr 2022", "year": year,
             "year_quote": year_quote}]


def test_a_frame_tuple_is_taken_when_its_quotes_carry_it():
    answers, _ = read({"P1": {"parameters": ["out:none"],
                              "frame": frame(2022, "im Jahr 2022")},
                       "P2": {"parameters": ["out:none"]}})
    assert [(t["scenario"], t["year"]) for t in answers[0].tuples["frame"]] \
        == [("Bestand", 2022)]


def test_a_frame_tuple_whose_quote_lacks_its_year_is_not():
    answers, _ = read({"P1": {"parameters": ["out:none"],
                              "frame": frame(2040, "im Jahr 2022")},
                       "P2": {"parameters": ["out:none"]}})
    assert answers[0].tuples == {}
    assert answers[0].dropped


def test_a_passage_the_reply_leaves_out_is_unanswered():
    answers, unanswered = read({"P1": {"parameters": ["out:none"]}})
    assert [a.owner for a in answers] == [("table", 1)]
    assert unanswered == [("section", 2)]


# -- one document --------------------------------------------------------------

def make(store, ask, key="k"):
    passages = [passage("section", 1, TEXT), passage("table", 2, TABLE),
                passage("section", 3, TEXT + " Noch ein Satz.")]
    return survey.Survey(ask, lambda document_id: passages,
                         lambda document_id: 1, PARAMETERS, SLOTS,
                         runner.frame_pairs, key, store=store)


def emission_where_printed(context, document_id):
    return {"passages": {
        f"P{i + 1}": ({"parameters": ["emission"],
                       "quote": "Treibhausgasemissionen der Stadt"}
                      if "Treibhausgas" in s.text
                      else {"parameters": ["out:none"]})
        for i, s in enumerate(context)}}


def test_a_survey_names_a_parameters_passages_and_is_read_again(tmp_path):
    found = make(tmp_path, emission_where_printed)(7)
    assert found.complete
    assert found.passages_of("emission") == [("table", 2)]
    asked = []

    def counting(context, document_id):
        asked.append(context)
        return emission_where_printed(context, document_id)

    again = make(tmp_path, counting)(7)
    assert again.passages_of("emission") == [("table", 2)] and not asked
    make(tmp_path, counting, key="other")(7)
    assert asked


def test_a_reply_cut_off_is_split_and_not_rescued(tmp_path):
    def cut_when_long(context, document_id):
        if len(context) > 1:
            return survey.CUT
        return emission_where_printed(context, document_id)

    found = make(tmp_path, cut_when_long)(7)
    assert found.complete and found.passages_of("emission") == [("table", 2)]
