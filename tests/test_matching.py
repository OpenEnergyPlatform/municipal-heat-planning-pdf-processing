"""A list the spec marks `matched_apart` is read as the document prints it and
matched in a request of its own (owner decision 2026-11-05): the reading
shows no list and asks the wording, AND the match chooses the entry, which
becomes the answer with the wording as its `value_raw`, AND the check takes
it as on any closed list. A reply that is no entry is asked once more with
the reason, AND one still none leaves the entry empty with the wording kept.
The combing matches what it answers the same way, with the passage the quote
stands in. A spec marks only a list the profile closes per document.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import combing, fields, matching, reading, runner
from docpipe.extraction.pipeline import Batch, Source, WorkItem
from docpipe.extraction.spec import SpecError, load as load_spec
from docpipe.extraction.wording import say
from profiles.scenarios.extraction import SCENARIO_OUT

SPEC_FILE = (Path(__file__).resolve().parent.parent / "profiles"
             / "scenarios" / "extraction_spec.json")
RUNS = {"EN_NPi2100": ["EN_NPi2100"],
        "EN_INDCi2030_1000f": ["EN_INDCi2030_1000f"], **SCENARIO_OUT}
# The spec as a document closes it (`runner.fill_dynamic_axes`).
SPEC = runner.fill_dynamic_axes(
    load_spec(json.loads(SPEC_FILE.read_text(encoding="utf-8"))),
    {"scenario": RUNS, "scenario_label": RUNS})
LABEL = SPEC.by_uri["scenario_label"]
YEAR = SPEC.by_uri["scenario_year"]

TEXT = Source("section", 6, "We analyse two pathways: the Current Policies "
              "scenario (CurPol) and the NDC scenario. Results for the "
              "CurPol scenario are reported for 2030.",
              {"document_id": 7, "section_title": "Scenarios"})
CURPOL = {"value": "CurPol", "quote": "the Current Policies scenario (CurPol)"}
Y2030 = {"value": "2030", "quote": "Results for the CurPol scenario are "
                                   "reported for 2030"}
NAMED = {"scenario": {"value": "CurPol",
                      "quote": "Results for the CurPol scenario"}}


def matcher(*entries):
    """A match that answers *entries* in turn, and what it was asked."""
    asked = []

    def match(document_id, parameter, slot, name, quote, source,
              around=None):
        asked.append({"name": name, "quote": quote, "source": source,
                      "slot": slot.name, "parameter": parameter.uri})
        return entries[min(len(asked), len(entries)) - 1]
    return match, asked


def read_of(parameter, values, groups=None, match=None):
    calls = []

    def ask_values(source, parameter, context, read, corrections=None):
        calls.append(("values", reading.values_payload(
            source, parameter, context, read, corrections),
            reading.values_response_format(parameter)))
        return values[min(sum(1 for c in calls if c[0] == "values"),
                          len(values)) - 1]

    def ask_text(source, parameter, group, slots, row, context,
                 corrections=None):
        calls.append((group.name, reading.text_payload(
            source, parameter, slots, row, group.where, context,
            corrections), reading.text_response_format(slots)))
        return (groups or {}).get(group.name) or {
            slot.name: {"value": fields.UNSTATED} for slot in slots}

    reader = reading.Reader(SPEC, ask_values, ask_text, [], match=match)
    read = reader.read(7, parameter, TEXT, [], [],
                       {(TEXT.owner_kind, TEXT.owner_id): TEXT})
    return read, calls


def test_a_value_is_read_as_printed_and_matched_onto_the_list():
    match, asked = matcher("EN_NPi2100")
    read, calls = read_of(LABEL, ({"next": CURPOL}, {"next": None}),
                          match=match)
    payload, shape = calls[0][1], calls[0][2]
    assert "value_classes" not in payload["parameter"]
    value = shape["json_schema"]["schema"]["properties"]["next"]["anyOf"][0]
    assert value["properties"]["value"] == {"type": "string"}
    assert [(a["name"], a["quote"]) for a in asked] \
        == [("CurPol", CURPOL["quote"])]
    claim = read.claims[0]
    assert (claim["value"], claim["value_raw"]) == ("EN_NPi2100", "CurPol")
    # The next round sees what was read in both forms.
    assert calls[1][1]["read"][0]["value_raw"] == "CurPol"


def test_a_value_no_entry_fits_keeps_its_wording_without_an_entry():
    match, _ = matcher("")
    read, _ = read_of(LABEL, ({"next": CURPOL}, {"next": None}), match=match)
    claim = read.claims[0]
    assert (claim["value"], claim["value_raw"]) == ("", "CurPol")


def test_a_coordinate_is_asked_by_its_wording_and_takes_the_entry():
    match, asked = matcher("EN_NPi2100")
    read, calls = read_of(YEAR, ({"next": Y2030}, {"next": None}),
                          groups={"scenario": NAMED}, match=match)
    (_task, payload, shape), = [c for c in calls if c[0] == "scenario"]
    assert payload["coordinates"]["scenario"].get("options") is None
    assert payload["coordinates"]["scenario"]["kind"] == fields.TEXT
    assert shape["json_schema"]["schema"]["properties"]["scenario"][
        "properties"]["value"] == {"type": "string"}
    assert [(a["slot"], a["name"]) for a in asked] == [("scenario", "CurPol")]
    claim = read.claims[0]
    assert claim["scenario_state"] == fields.READ
    assert (claim["scenario"], claim["scenario_raw"]) \
        == ("EN_NPi2100", "CurPol")
    assert claim["scenario_quote"] == NAMED["scenario"]["quote"]
    # Unmatched, a wording is no entry of the list and is not read.
    alone, _ = read_of(YEAR, ({"next": Y2030}, {"next": None}),
                       groups={"scenario": NAMED})
    assert alone.claims[0]["scenario_state"] == fields.UNBACKED


def test_a_coordinate_no_entry_fits_keeps_the_wording_it_saw():
    match, _ = matcher("")
    read, _ = read_of(YEAR, ({"next": Y2030}, {"next": None}),
                      groups={"scenario": NAMED}, match=match)
    claim = read.claims[0]
    assert claim["scenario_state"] == fields.SAID_UNSTATED
    assert claim["scenario_seen"] == "CurPol"


def test_a_reply_that_is_no_entry_is_asked_once_more_then_none():
    slot = next(s for s in fields.asked_slots(YEAR) if s.name == "scenario")
    replies, payloads, shapes = [{"value": "EN_NPi"}, {"value": "EN_NPi2100"}],\
        [], []

    def ask(payload, shape, document_id, source, parameter):
        payloads.append(payload)
        shapes.append(shape)
        return replies[len(payloads) - 1]
    match = matching.Matcher(ask)
    assert match(7, YEAR, slot, "CurPol", "the CurPol scenario",
                 TEXT) == "EN_NPi2100"
    assert fields.UNSTATED not in payloads[0]["options"]
    assert set(payloads[0]["options"]) == set(
        shapes[0]["json_schema"]["schema"]["properties"]["value"]["enum"])
    assert "corrections" not in payloads[0]
    assert payloads[1]["corrections"] == [
        {"value": "EN_NPi", "what": say("not_an_option", given="EN_NPi")}]
    replies[1] = {"value": "EN_NPi"}
    payloads.clear()
    assert match(7, YEAR, slot, "CurPol", "the CurPol scenario", TEXT) == ""
    assert len(payloads) == 2


def test_the_combing_matches_its_answers_with_the_passage_quoted():
    claim = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
             "scenario_state": fields.SAID_UNSTATED}
    batch = Batch(7, YEAR, [WorkItem(7, YEAR, TEXT)], spec=SPEC)
    reads = [reading.Read(batch, [claim], probes=[{}])]
    reply = {"rows": [{"row": "R1", **NAMED}]}
    match, asked = matcher("EN_NPi2100")
    made = combing.Comber(SPEC, lambda *a, **k: reply, None,
                          lambda claim, names: {}, match=match)
    made(7, reads, {(TEXT.owner_kind, TEXT.owner_id): TEXT}, [])
    assert [(a["name"], a["source"].owner_id) for a in asked] \
        == [("CurPol", 6)]
    assert (claim["scenario"], claim["scenario_raw"]) \
        == ("EN_NPi2100", "CurPol")
    assert claim["scenario_state"] == fields.READ
    # A quote that stands in nothing shown is left to the check, unmatched.
    stray = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
             "scenario_state": fields.SAID_UNSTATED}
    reads = [reading.Read(batch, [stray], probes=[{}])]
    elsewhere = {"rows": [{"row": "R1", "scenario": {
        "value": "CurPol", "quote": "the CurPol run of another study"}}]}
    match, asked = matcher("EN_NPi2100")
    combing.Comber(SPEC, lambda *a, **k: elsewhere, None,
                   lambda claim, names: {}, match=match)(
        7, reads, {(TEXT.owner_kind, TEXT.owner_id): TEXT}, [])
    assert asked == [] and stray["scenario_state"] == fields.UNBACKED


def test_only_a_list_closed_per_document_is_matched_apart():
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    assert matching.matched_apart(load_spec(raw))
    sector = next(p for p in raw["parameters"] if p["uri"] == "study_sector")
    sector["matched_apart"] = True
    with pytest.raises(SpecError):
        load_spec(raw)


def test_a_list_matched_apart_is_not_read_in_the_survey():
    # The survey shows a coordinate's list and has no match.
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    raw["groups"]["scenario"]["read_in"] = "survey"
    with pytest.raises(SpecError):
        load_spec(raw)
