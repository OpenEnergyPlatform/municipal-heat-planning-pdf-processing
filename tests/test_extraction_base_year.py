"""A row's year from the plan's base year or its target year, and the
grammar of a field reply.

The promise of the first, in one sentence: a year answer whose quote carries
the answer's wording but not its number is read when, AND only when, the
number is one of the years the document's frame found for a state the profile
names, the plan's own state or its target; it then cites the frame's passage
for the number AND keeps the row's passage as its link AND the window and the
count say under which of the two states the year was offered AND the request
for the year offers each state's years under a key of its own AND a profile
that names no target has no target years. Which state the word means is the
model's reading and is not checked. corpus_m5 dropped 127,233 year answers
whose wording stood in their quote and whose number did not, "Basisjahr"
among the most common, and the harvest after it about 14,500 with the plan's
word for its target.

The promise of the second: every reply shape the parser reads is one the
server may generate, AND an answer off the closed list or beside the object is
not.
"""
import json
from types import SimpleNamespace as NS

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (Batch, Row, Source, merge_field,
                                         named_years, option_named,
                                         state_years)
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

jsonschema = pytest.importorskip("jsonschema")

ROW_TEXT = ("Die Sektoren GHD & Sonstiges emittierten im Basisjahr 4 % der "
            "gesamten CO2-Emissionen.")
BASE_QUOTE = ("Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr "
              "2022 erstellt.")
TARGET_ROW = "Im Zieljahr entfallen 60 % der Wärme auf Wärmenetze."
TARGET_QUOTE = "Die Stadt will bis zum Zieljahr 2045 klimaneutral sein."


def _year():
    return fields.Slot(name="year", kind=fields.NUMBER,
                       question="Welches Jahr?")


def _scenario():
    return fields.Slot(name="scenario", kind=fields.CHOICE,
                       question="Welcher Zustand?", options=(
                           fields.Option(label="Bestand", uri="status_quo",
                                         synonyms=("Ist-Zustand",)),
                           fields.Option(label="Zielszenario", uri="target",
                                         synonyms=())))


def _bases(year=2022, axis="year"):
    return [{"state": "base", "axis": axis, "year": year, "quote": BASE_QUOTE,
             "source": ["section", 5], "index": 1}]


def _targets(*years):
    return [{"state": "target", "axis": "year", "year": year,
             "quote": TARGET_QUOTE.replace("2045", str(year)),
             "source": ["section", 6], "index": 2 + i}
            for i, year in enumerate(years or (2045,))]


def _merge(answer, bases, slot=None, text=ROW_TEXT):
    row = Row(label="R1", item_index=0, claim={"value": 4, "quote": text})
    source = Source("section", 9, text)
    got = merge_field([row], [source], slot or _year(),
                      {"answers": {"R1": answer}}, window=("own", 1),
                      bases=bases)
    return row.claim, got


def test_a_year_the_row_names_by_the_plans_word_is_read_from_the_base_year():
    claim, got = _merge({"value": 2022, "value_raw": "Basisjahr",
                         "quote": ROW_TEXT}, _bases())
    assert claim["year_state"] == fields.READ
    assert claim["year"] == 2022
    assert claim["year_raw"] == "Basisjahr"
    assert claim["year_quote"] == BASE_QUOTE, "the number's passage"
    assert claim["year_source"] == ["section", 5]
    assert claim["year_window"] == ["base_year", 1]
    assert claim["year_link_quote"] == ROW_TEXT, "the wording's passage"
    assert claim["year_link_source"] == ["section", 9]
    assert got["filled"] == 1 and got["via_base"] == 1
    assert not got["failed"]


@pytest.mark.parametrize("answer, bases", [
    # A number that is none of the base years.
    ({"value": 2019, "value_raw": "Basisjahr", "quote": ROW_TEXT}, _bases()),
    # A wording the quote does not carry.
    ({"value": 2022, "value_raw": "Bilanzjahr", "quote": ROW_TEXT}, _bases()),
    # No wording at all: nothing links the row to the state.
    ({"value": 2022, "quote": ROW_TEXT}, _bases()),
    # No base years for this document.
    ({"value": 2022, "value_raw": "Basisjahr", "quote": ROW_TEXT}, []),
    # A base year of another coordinate.
    ({"value": 2022, "value_raw": "Basisjahr", "quote": ROW_TEXT},
     _bases(axis="period")),
])
def test_without_both_halves_the_answer_fails_as_before(answer, bases):
    claim, got = _merge(answer, bases)
    assert claim["year_state"] == fields.UNBACKED
    assert "year" not in claim and "year_link_quote" not in claim
    assert [f["why"] for f in got["failed"]] == ["answer_not_in_quote"]
    assert got["via_base"] == 0


def test_a_quote_outside_the_shown_sources_is_no_link():
    claim, got = _merge({"value": 2022, "value_raw": "Basisjahr",
                         "quote": "Im Basisjahr lag der Verbrauch höher."},
                        _bases())
    assert claim["year_state"] == fields.UNBACKED
    assert [f["why"] for f in got["failed"]] == ["quote_not_in_source"]


def test_a_year_in_its_own_quote_is_read_as_before():
    text = "Im Basisjahr 2022 lag der Verbrauch bei 40 GWh."
    claim, got = _merge({"value": 2022, "value_raw": "Basisjahr",
                         "quote": text}, _bases(), text=text)
    assert claim["year_quote"] == text
    assert claim["year_window"] == ["own", 1]
    assert "year_link_quote" not in claim
    assert got["via_base"] == 0


def test_a_choice_never_takes_a_base_year():
    claim, got = _merge({"value": "Bestand", "value_raw": "Ist-Analyse",
                         "quote": ROW_TEXT}, _bases(), slot=_scenario())
    assert claim["scenario_state"] == fields.UNBACKED
    assert got["via_base"] == 0


def _pair(scenario, year, quote, source):
    return {"scenario": scenario, "scenario_raw": scenario,
            "scenario_quote": quote, "scenario_source": source,
            "year": year, "year_quote": quote, "year_source": source}


PAIRS = [_pair("status_quo", 2022, "Bilanzjahr 2022", ["section", 1]),
         _pair("target", 2045, "Zielszenario 2045", ["section", 2]),
         _pair("Bestand", 2022, "Bestand 2022", ["table", 3]),
         _pair("status_quo", 2019, "Stand 2019", ["section", 4]),
         _pair("Zielszenario", 2030, "Zwischenziel 2030", ["section", 7]),
         _pair("target", 2045, "Zielbild 2045", ["table", 8])]
BOTH = {"base": {"scenario": "status_quo"}, "target": {"scenario": "target"}}


def test_the_base_years_are_the_years_of_the_plans_own_state():
    frame = [_scenario(), _year()]
    got = state_years(PAIRS, frame, {"scenario": "status_quo"}, "base")
    assert got == [
        {"state": "base", "axis": "year", "year": 2022,
         "quote": "Bilanzjahr 2022", "source": ["section", 1], "index": 0},
        {"state": "base", "axis": "year", "year": 2019,
         "quote": "Stand 2019", "source": ["section", 4], "index": 3}], (
        "one entry per year, the first pair that proved it; a spelling of "
        "the state counts, a scenario does not")
    assert state_years(PAIRS, frame, None, "base") == [], "no state named"
    assert state_years(PAIRS, [_scenario()], {"scenario": "status_quo"},
                       "base") == [], "no number coordinate to date it with"


def test_the_target_years_are_the_years_of_the_plans_target_after_its_own():
    frame = [_scenario(), _year()]
    got = named_years(PAIRS, frame, BOTH)
    assert [(e["state"], e["year"], e["quote"], e["index"]) for e in got] == [
        ("base", 2022, "Bilanzjahr 2022", 0), ("base", 2019, "Stand 2019", 3),
        ("target", 2045, "Zielszenario 2045", 1),
        ("target", 2030, "Zwischenziel 2030", 4)], (
        "the plan's own years first, then its target's, one entry per year "
        "and state, by the entry a spelling resolves to")


@pytest.mark.parametrize("states, expected", [
    # A profile that names no target has no target years.
    ({"base": {"scenario": "status_quo"}}, ["base", "base"]),
    ({"base": {"scenario": "status_quo"}, "target": None}, ["base", "base"]),
    # One that names only a target has only those.
    ({"target": {"scenario": "target"}}, ["target", "target"]),
    # One that names neither has none.
    ({}, []), (None, []),
    # A target that is no entry of the list matches no pair.
    ({"target": {"scenario": "ziel"}}, []),
])
def test_a_state_the_profile_does_not_name_has_no_years(states, expected):
    got = named_years(PAIRS, [_scenario(), _year()], states)
    assert [e["state"] for e in got] == expected


def test_a_year_of_both_states_stands_once_under_each():
    pairs = [_pair("status_quo", 2025, "Stand 2025", ["section", 1]),
             _pair("target", 2025, "Ziel 2025", ["section", 2])]
    got = named_years(pairs, [_scenario(), _year()], BOTH)
    assert [(e["state"], e["quote"]) for e in got] == [
        ("base", "Stand 2025"), ("target", "Ziel 2025")]


def test_a_year_the_row_names_by_the_plans_word_for_its_target_is_read():
    claim, got = _merge({"value": 2045, "value_raw": "Zieljahr",
                         "quote": TARGET_ROW}, _bases() + _targets(),
                        text=TARGET_ROW)
    assert claim["year_state"] == fields.READ
    assert claim["year"] == 2045 and claim["year_raw"] == "Zieljahr"
    assert claim["year_quote"] == TARGET_QUOTE, "the number's passage"
    assert claim["year_source"] == ["section", 6]
    assert claim["year_window"] == ["target_year", 2], "the state, the pair"
    assert claim["year_link_quote"] == TARGET_ROW, "the wording's passage"
    assert claim["year_link_source"] == ["section", 9]
    assert got["filled"] == 1 and got["via_target"] == 1
    assert got["via_base"] == 0, "counted under its own state only"
    assert not got["failed"]


@pytest.mark.parametrize("answer, named", [
    # A number that is none of the years shown.
    ({"value": 2040, "value_raw": "Zieljahr", "quote": TARGET_ROW},
     _bases() + _targets()),
    # A wording the quote does not carry.
    ({"value": 2045, "value_raw": "Zielzustand", "quote": TARGET_ROW},
     _targets()),
    # No wording at all: nothing links the row to the state.
    ({"value": 2045, "quote": TARGET_ROW}, _targets()),
    # The document has base years and no target years.
    ({"value": 2045, "value_raw": "Zieljahr", "quote": TARGET_ROW}, _bases()),
])
def test_without_both_halves_a_target_year_fails_as_any_answer(answer, named):
    claim, got = _merge(answer, named, text=TARGET_ROW)
    assert claim["year_state"] == fields.UNBACKED
    assert "year" not in claim and "year_link_quote" not in claim
    assert [f["why"] for f in got["failed"]] == ["answer_not_in_quote"]
    assert got["via_target"] == 0 and got["via_base"] == 0


def test_the_model_chooses_among_several_target_years():
    """Three target years and a row that says "Zieljahr": each of them is an
    answer that is read, and each cites the passage of the year chosen."""
    named = _bases() + _targets(2030, 2040, 2045)
    for index, year in enumerate((2030, 2040, 2045)):
        claim, got = _merge({"value": year, "value_raw": "Zieljahr",
                             "quote": TARGET_ROW}, named, text=TARGET_ROW)
        assert claim["year"] == year and got["via_target"] == 1
        assert claim["year_quote"] == TARGET_QUOTE.replace("2045", str(year))
        assert claim["year_window"] == ["target_year", 2 + index]


def test_which_state_the_word_means_is_not_checked():
    """The row says "Zieljahr" and the answer is the plan's base year: read,
    under the state the number was offered for. Owner, 2026-09-22 and
    2026-10-06: the choice among the years shown is the model's reading."""
    claim, got = _merge({"value": 2022, "value_raw": "Zieljahr",
                         "quote": TARGET_ROW}, _bases() + _targets(),
                        text=TARGET_ROW)
    assert claim["year_state"] == fields.READ and claim["year"] == 2022
    assert claim["year_window"] == ["base_year", 1]
    assert got["via_base"] == 1 and got["via_target"] == 0


def test_a_target_year_in_its_own_quote_is_read_as_any_year():
    text = "Im Zieljahr 2045 entfallen 60 % der Wärme auf Wärmenetze."
    claim, got = _merge({"value": 2045, "value_raw": "Zieljahr",
                         "quote": text}, _targets(), text=text)
    assert claim["year_quote"] == text and claim["year_window"] == ["own", 1]
    assert "year_link_quote" not in claim
    assert got["via_target"] == 0


def test_only_the_year_request_carries_the_base_years():
    rows = [Row(label="R1", item_index=0, claim={"value": 4, "quote": ROW_TEXT})]
    shown = [Source("section", 9, ROW_TEXT)]
    asked = runner._field_payload(shown, rows, _year(), bases=_bases())
    assert asked["base_years"] == [{"year": 2022, "quote": BASE_QUOTE}]
    assert "target_years" not in asked, "the document has none"
    other = runner._field_payload(shown, rows, _scenario(), bases=_bases())
    assert "base_years" not in other
    none = runner._field_payload(shown, rows, _year(), bases=[])
    assert "base_years" not in none


def test_the_year_request_offers_each_states_years_under_its_own_key():
    rows = [Row(label="R1", item_index=0, claim={"value": 4, "quote": ROW_TEXT})]
    shown = [Source("section", 9, ROW_TEXT)]
    named = _bases() + _targets(2030, 2045)
    asked = runner._field_payload(shown, rows, _year(), bases=named)
    assert asked["base_years"] == [{"year": 2022, "quote": BASE_QUOTE}]
    assert asked["target_years"] == [
        {"year": 2030, "quote": TARGET_QUOTE.replace("2045", "2030")},
        {"year": 2045, "quote": TARGET_QUOTE}]
    assert list(asked) == ["sources", "rows", "base_years", "target_years",
                           "fields"]
    only = runner._field_payload(shown, rows, _year(), bases=_targets())
    assert "base_years" not in only and len(only["target_years"]) == 1
    other = runner._field_payload(shown, rows, _scenario(), bases=named)
    assert "base_years" not in other and "target_years" not in other


def test_the_run_reads_the_states_a_profile_names_and_none_it_does_not():
    assert runner.year_states_of(load_profile("kwp")) == {
        "base": {"scenario": "status_quo"}, "target": {"scenario": "target"}}
    assert runner.year_states_of(load_profile("scenarios")) == {
        "base": None, "target": None}, "a profile that names no state"
    assert set(runner.YEAR_STATE_CONSTANTS) == set(runner.YEAR_STATES), (
        "every state the fold knows has a constant a profile can name it by")


@pytest.mark.parametrize("constant", ["BASE_YEAR", "TARGET_YEAR"])
def test_the_states_kwp_names_are_entries_of_its_frame(constant):
    """A state that is no entry of the list matches no pair, and the rule
    would be off without a word: the names in the profile resolve, each to an
    entry of its own."""
    profile = load_profile("kwp")
    spec = load_spec(profile.component("extraction", "SPEC_PATH"))
    frame = {slot.name: slot for slot in fields.frame_slots(
        spec, profile.component("extraction", "FRAME"))}
    where = profile.component("extraction", constant)
    assert where, constant
    found = {name: option_named(frame[name], value)
             for name, value in where.items()}
    assert all(found.values()), found
    other = profile.component(
        "extraction", "TARGET_YEAR" if constant == "BASE_YEAR" else "BASE_YEAR")
    assert all(option_named(frame[name], other[name]) is not found[name]
               for name in where if name in other), "two different states"


def test_the_sweep_hands_the_documents_base_years_to_ask_and_merge():
    batch = Batch(document_id=7, parameter=None,
                  items=[NS(source=Source("section", 9, ROW_TEXT))])
    batch.bases = tuple(_bases())
    row = Row(label="R1", item_index=0, claim={"value": 4, "quote": ROW_TEXT})
    seen = []

    def ask(shown, rows, slots, corrections=None, document_id=None,
            usage_out=None, owner_of=None, bases=None):
        seen.append(bases)
        return {"fields": {"year": {"answers": {"R1": {
            "value": 2022, "value_raw": "Basisjahr", "quote": ROW_TEXT}}}}}

    totals = runner.make_sweeper(ask)(batch, [row], [_year()], "year")
    assert seen and seen[0] == _bases()
    assert row.claim["year_window"][0] == "base_year"
    assert totals["via_base"] == 1, "the sweep's total counts the link too"
    assert totals["via_target"] == 0


def test_the_sweep_counts_a_target_year_under_its_own_total():
    batch = Batch(document_id=7, parameter=None,
                  items=[NS(source=Source("section", 9, TARGET_ROW))])
    batch.bases = tuple(_bases() + _targets())
    row = Row(label="R1", item_index=0, claim={"value": 60, "quote": TARGET_ROW})

    def ask(shown, rows, slots, corrections=None, document_id=None,
            usage_out=None, owner_of=None, bases=None):
        return {"fields": {"year": {"answers": {"R1": {
            "value": 2045, "value_raw": "Zieljahr", "quote": TARGET_ROW}}}}}

    totals = runner.make_sweeper(ask)(batch, [row], [_year()], "year")
    assert row.claim["year_window"][0] == "target_year"
    assert totals["via_target"] == 1 and totals["via_base"] == 0


def _schema(slot):
    shape = runner.field_response_format(slot)
    assert shape["type"] == "json_schema"
    return jsonschema.Draft202012Validator(shape["json_schema"]["schema"])


@pytest.mark.parametrize("reply", [
    {"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"],
                                         "value": "Bestand",
                                         "value_raw": "Ist-Zustand 2022",
                                         "quote": "Tabelle 4: Ist-Zustand"}]}}},
    {"fields": {"scenario": {"answers": {"R3": {"value": fields.UNSTATED}}}},
     "need_more": ["Die Bilanz bezieht sich auf das Bilanzjahr 2021."]},
    # field.md rule 6: the wording without a value.
    {"fields": {"scenario": {"answers": {"R1": {"value_raw": "Szenario C"}}}}},
    {"fields": {"scenario": {}}},
])
def test_every_reply_the_parser_reads_is_one_the_grammar_allows(reply):
    assert _schema(_scenario()).is_valid(reply), reply


@pytest.mark.parametrize("reply", [
    {"fields": {"scenario": {"answers": {"R1": {"value": "Teilgebiet"}}}}},
    {"fields": {}},
    {"fields": {"scenario": {}}, "status": "complete"},
    {"fields": {"scenario": {"answers": {"R1": {"value": "Bestand",
                                                "source": "Q1"}}}}},
])
def test_an_answer_off_the_list_or_beside_the_contract_is_not(reply):
    assert not _schema(_scenario()).is_valid(reply), reply


def test_a_year_is_an_integer_or_not_stated():
    schema = _schema(_year())
    ok = {"fields": {"year": {"answers": {"R1": {"value": 2022},
                                         "R2": {"value": fields.UNSTATED}}}}}
    assert schema.is_valid(ok)
    for bad in ("2030-2045", "2022", 2022.5):
        assert not schema.is_valid(
            {"fields": {"year": {"answers": {"R1": {"value": bad}}}}}), bad


def test_every_field_request_goes_out_with_its_grammar(monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    sent = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    sent.append(kw.get("response_format"))
                    body = json.dumps({"fields": {"year": {"answers": {}}}})
                    return NS(choices=[NS(
                        message=NS(content=body, reasoning_content=""),
                        finish_reason="stop")], usage=None)

    monkeypatch.setattr(runner, "_client", lambda: _Client())
    rows = [NS(label="R1", claim={"value": 4, "quote": ROW_TEXT})]
    runner.make_field_asker()([], rows, _year())
    assert sent == [runner.field_response_format(_year())]
