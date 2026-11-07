"""The spec puts every coordinate in exactly one group, and the survey of a
whole plan asks for each passage in a request of its own, a passage longer
than a page in pieces (owner decisions 2026-11-06), reads the reply as that
passage's entry with no wrapper and no id, takes the parameters it names as
named, those of the spec only and without a quote, and a frame tuple only on
quotes that carry it, and is read again from disk under its own key.

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
        groups["context"].pop("own_passage", None)
        groups["odd"] = {"coordinates": ["whole", "aggregation"],
                         "read_in": "survey", "where": "irgendwo"}
    with pytest.raises(SpecError, match="one parameter"):
        load_spec(with_groups(odd))


def test_what_only_a_value_s_own_passage_or_number_says_is_of_its_group():
    # Owner decision 2026-11-06: what a number counts and how it is
    # aggregated only its own passage says, a word like "ca." only the
    # number itself; the combing does not look for them elsewhere.
    number, context = SPEC.groups["number"], SPEC.groups["context"]
    # And its unit, what the number is, and the beginning of a period it is
    # a mean over: read again beside it, never searched elsewhere (owner
    # decisions 2026-11-07).
    assert (number.own_passage, number.own_value) == (
        ("unit", "what", "subject"), ("qualifier",))
    assert context.own_passage == ("aggregation",)
    assert SPEC.groups["frame"].own_passage == ("period_start",)
    raw = with_groups(lambda g: g["number"].update(own_passage=["year"]))
    with pytest.raises(SpecError, match="group's coordinates"):
        load_spec(raw)
    raw = with_groups(lambda g: g["number"].update(own_value=["subject"]))
    with pytest.raises(SpecError, match="not both"):
        load_spec(raw)


# -- contexts ------------------------------------------------------------------

def test_each_passage_is_a_context_of_its_own_and_none_is_missed():
    # Small passages that would have fit one page together are still asked
    # one by one, and a figure is not cut however long its description.
    passages = [passage("section", 1, "a" * 30),
                passage("figure", 2, "Abbildung " * 100),
                passage("figure", 3, "Abbildung " * 5),
                passage("section", 4, "b" * 30),
                passage("table", 5, "c" * 45)]
    contexts = survey.contexts_of(passages, 700)
    assert all(len(context) == 1 for context in contexts)
    assert [p.owner_id for c in contexts for p in c] == [1, 2, 3, 4, 5]
    assert contexts[1][0].text == "Abbildung " * 100


def test_a_passage_longer_than_a_page_goes_in_pieces_that_keep_it():
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
    assert survey.budget_of(passages, 4, 1) == 1000


def test_every_passage_is_asked_alone_however_short(tmp_path):
    # Owner decision 2026-11-06: one passage per request. Four short
    # sections of a plan of one page are that page's text together, and
    # still four requests.
    pages = [passage("section", n, "x" * 100) for n in range(1, 5)]
    asked = []

    def ask(context, document_id, thread=None,
               follow=None):
        corrections = (follow or {}).get("corrections")
        asked.append([s.owner_id for s in context])
        return {"parameters": ["out:none"]}
    survey.Survey(ask, lambda document_id: pages, lambda document_id: 1,
                  PARAMETERS, SLOTS, runner.frame_pairs, "k",
                  store=tmp_path)(7)
    assert asked == [[1], [2], [3], [4]]


# -- the request and the reply -------------------------------------------------

def test_a_request_shows_its_one_passage_without_an_id():
    shown = survey.payload([passage("table", 1, "y")], PARAMETERS, {})
    assert shown["source"] == {"kind": "table", "section": "Bilanz",
                               "text": "y", "page": 1}
    assert "sources" not in shown and "id" not in shown["source"]
    with pytest.raises(ValueError, match="one passage"):
        survey.payload([passage("section", 1, "x"), passage("table", 2, "y")],
                       PARAMETERS, {})


def test_the_grammar_wants_the_passages_parameters_at_its_top():
    schema = survey.response_format(PARAMETERS, SLOTS)["json_schema"]["schema"]
    assert schema["required"] == ["parameters"]
    assert set(schema["properties"]) == {"parameters", "frame"}
    assert "passages" not in schema["properties"]


TABLE = ("Tabelle 3: Treibhausgasemissionen der Stadt im Jahr 2022\n"
         "| Erdgas | 1.234 |")
TEXT = "Die Stadt liegt an einem Kanal und hat viele Brücken."


def read(reply, source=None):
    source = source or passage("table", 1, TABLE)
    return survey.read_reply(reply, [source], PARAMETERS, SLOTS,
                             runner.frame_pairs)


def test_a_parameter_named_for_a_passage_is_taken_without_a_quote():
    answers, _ = read({"parameters": ["emission"]})
    assert answers[0].parameters == ["emission"] and not answers[0].dropped
    answers, _ = read({"parameters": ["out:none"]},
                      passage("section", 2, TEXT))
    assert answers[0].parameters == []
    # Not even a quote the passage does not print takes a name back: the
    # survey names, the reading checks.
    answers, _ = read({"parameters": ["emission"],
                       "quote": "steht nirgends im Plan"},
                      passage("section", 2, TEXT))
    assert answers[0].parameters == ["emission"] and not answers[0].dropped


def test_a_name_that_is_no_parameter_of_the_spec_is_not_taken():
    answers, _ = read({"parameters": ["colour", "emission"]})
    assert answers[0].parameters == ["emission"]
    answers, _ = read({"parameters": ["colour"]})
    assert answers[0].parameters == []


def frame(year, year_quote):
    return [{"scenario": "Bestand", "scenario_quote": "im Jahr 2022",
             "scenario_raw": "im Jahr 2022", "year": year,
             "year_quote": year_quote}]


def test_a_frame_tuple_is_taken_when_its_quotes_carry_it():
    answers, _ = read({"parameters": ["out:none"],
                       "frame": frame(2022, "im Jahr 2022")})
    assert [(t["scenario"], t["year"]) for t in answers[0].tuples["frame"]] \
        == [("Bestand", 2022)]


def test_a_frame_tuple_whose_quote_lacks_its_year_is_not():
    answers, _ = read({"parameters": ["out:none"],
                       "frame": frame(2040, "im Jahr 2022")})
    assert answers[0].tuples == {}
    assert answers[0].dropped


def test_a_reply_without_a_list_of_parameters_leaves_its_passage_unanswered():
    # The wrapper the reply had before, a list that is no list, no object.
    for reply in ({"passages": {"P1": {"parameters": ["emission"]}}},
                  {"parameters": "emission"}, None):
        answers, unanswered = read(reply)
        assert answers == [] and unanswered == [("table", 1)]
    with pytest.raises(ValueError, match="one passage"):
        survey.read_reply({"parameters": ["emission"]},
                          [passage("table", 1, TABLE),
                           passage("section", 2, TEXT)],
                          PARAMETERS, SLOTS, runner.frame_pairs)


# -- one document --------------------------------------------------------------

def make(store, ask, key="k"):
    passages = [passage("section", 1, TEXT), passage("table", 2, TABLE),
                passage("section", 3, TEXT + " Noch ein Satz.")]
    return survey.Survey(ask, lambda document_id: passages,
                         lambda document_id: 1, PARAMETERS, SLOTS,
                         runner.frame_pairs, key, store=store)


def emission_where_printed(context, document_id, thread=None,
                              follow=None):
    corrections = (follow or {}).get("corrections")
    return ({"parameters": ["emission"]}
            if "Treibhausgas" in context[0].text
            else {"parameters": ["out:none"]})


def test_a_survey_names_a_parameters_passages_and_is_read_again(tmp_path):
    found = make(tmp_path, emission_where_printed)(7)
    assert found.complete
    assert found.passages_of("emission") == [("table", 2)]
    asked = []

    def counting(context, document_id, thread=None,
                    follow=None):
        corrections = (follow or {}).get("corrections")
        asked.append(context)
        return emission_where_printed(context, document_id)

    again = make(tmp_path, counting)(7)
    assert again.passages_of("emission") == [("table", 2)] and not asked
    make(tmp_path, counting, key="other")(7)
    assert asked


def test_a_reply_cut_off_leaves_its_passage_unanswered_and_is_not_rescued(
        tmp_path):
    def cut_at_the_table(context, document_id, thread=None,
                            follow=None):
        corrections = (follow or {}).get("corrections")
        if "Treibhausgas" in context[0].text:
            return survey.CUT
        return emission_where_printed(context, document_id)

    found = make(tmp_path, cut_at_the_table)(7)
    assert not found.complete and found.unanswered == [("table", 2)]
    assert found.passages_of("emission") == []
    assert set(found.answers) == {("section", 1), ("section", 3)}


def test_a_reply_without_its_parameters_is_asked_again_and_answered(
        tmp_path):
    calls = []

    def table_wrapped_first(context, document_id, thread=None,
                               follow=None):
        corrections = (follow or {}).get("corrections")
        reply = emission_where_printed(context, document_id)
        if "Treibhausgas" in context[0].text:
            calls.append(corrections)
            if corrections is None:
                return {"passages": {"P1": reply}}
        return reply

    found = make(tmp_path, table_wrapped_first)(7)
    assert found.passages_of("emission") == [("table", 2)]
    assert len(calls) == 2 and calls[0] is None
    assert len(calls[1]) == 1 and '"parameters"' in calls[1][0]


def test_a_reply_without_fault_is_asked_once_per_passage(tmp_path):
    calls = []

    def right(context, document_id, thread=None,
                 follow=None):
        corrections = (follow or {}).get("corrections")
        calls.append(corrections)
        return emission_where_printed(context, document_id)

    make(tmp_path, right)(7)
    assert calls == [None, None, None]


def test_a_reply_wrong_twice_is_not_asked_a_third_time(tmp_path):
    calls = []

    def always_without_the_table(context, document_id, thread=None,
                                    follow=None):
        corrections = (follow or {}).get("corrections")
        if "Treibhausgas" in context[0].text:
            calls.append(corrections)
            return {}
        return {"parameters": ["out:none"]}

    found = make(tmp_path, always_without_the_table)(7)
    assert len(calls) == 2 and ("table", 2) in found.unanswered
