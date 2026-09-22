"""A row's year from the plan's base year, and the grammar of a field reply.

The promise of the first, in one sentence: a year answer whose quote carries
the answer's wording but not its number is read when, AND only when, the
number is one of the document's base years; it then cites the frame's passage
for the number AND keeps the row's passage as its link. corpus_m5 dropped
127,233 year answers whose wording stood in their quote and whose number did
not, "Basisjahr" among the most common.

The promise of the second: every reply shape the parser reads is one the
server may generate, AND an answer off the closed list or beside the object is
not.
"""
import json
from types import SimpleNamespace as NS

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (Batch, Row, Source, base_years,
                                         merge_field)

jsonschema = pytest.importorskip("jsonschema")

ROW_TEXT = ("Die Sektoren GHD & Sonstiges emittierten im Basisjahr 4 % der "
            "gesamten CO2-Emissionen.")
BASE_QUOTE = ("Die Energie- und Treibhausgasbilanz wurde für das Bilanzjahr "
              "2022 erstellt.")


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
    return [{"axis": axis, "year": year, "quote": BASE_QUOTE,
             "source": ["section", 5], "index": 1}]


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


def test_the_base_years_are_the_years_of_the_plans_own_state():
    pairs = [_pair("status_quo", 2022, "Bilanzjahr 2022", ["section", 1]),
             _pair("target", 2045, "Zielszenario 2045", ["section", 2]),
             _pair("Bestand", 2022, "Bestand 2022", ["table", 3]),
             _pair("status_quo", 2019, "Stand 2019", ["section", 4])]
    frame = [_scenario(), _year()]
    got = base_years(pairs, frame, {"scenario": "status_quo"})
    assert got == [
        {"axis": "year", "year": 2022, "quote": "Bilanzjahr 2022",
         "source": ["section", 1], "index": 0},
        {"axis": "year", "year": 2019, "quote": "Stand 2019",
         "source": ["section", 4], "index": 3}], (
        "one entry per year, the first pair that proved it; a spelling of "
        "the state counts, a scenario does not")
    assert base_years(pairs, frame, None) == [], "no base state named"
    assert base_years(pairs, [_scenario()], {"scenario": "status_quo"}) == [], (
        "no number coordinate to date it with")


def test_only_the_year_request_carries_the_base_years():
    rows = [Row(label="R1", item_index=0, claim={"value": 4, "quote": ROW_TEXT})]
    shown = [Source("section", 9, ROW_TEXT)]
    asked = runner._field_payload(shown, rows, _year(), bases=_bases())
    assert asked["base_years"] == [{"year": 2022, "quote": BASE_QUOTE}]
    other = runner._field_payload(shown, rows, _scenario(), bases=_bases())
    assert "base_years" not in other
    none = runner._field_payload(shown, rows, _year(), bases=[])
    assert "base_years" not in none


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
