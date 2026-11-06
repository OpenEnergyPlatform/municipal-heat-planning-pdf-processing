"""A list the spec marks `matched_apart` is read as the document prints it and
matched in a request of its own (owner decision 2026-11-05): the reading
shows no list and asks the wording, AND the match chooses the entry, which
becomes the answer with the wording as its `value_raw`, AND the check takes
it as on any closed list. A reply that is no entry is asked once more with
the reason, AND one still none leaves the entry empty with the wording kept.
The combing matches what it answers the same way, with the passage the quote
stands in. A spec marks only a list the profile closes per document.

A request that reads such a list shows only the wording, never the entry the
match chose (owner decision 2026-11-06). A value stated for several wordings
is one row per wording, each matched and checked on its own, AND a
correction for one of them names its wording, AND the combing's rows join
their value's reading; a pass over a stored harvest takes the first wording.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import combing, fields, matching, reading, runner
from docpipe.extraction.pipeline import READ, Batch, Row, Source, WorkItem
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


def read_of(parameter, values, groups=None, match=None, spec=None):
    """A Reader over TEXT: *values* the replies of the rounds in turn,
    *groups* {group: a reply, or [replies in turn]}."""
    calls = []
    given = {name: (list(reply) if isinstance(reply, list) else [reply])
             for name, reply in (groups or {}).items()}

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
        replies = given.get(group.name)
        if not replies:
            return {slot.name: {"value": fields.UNSTATED} for slot in slots}
        return replies.pop(0) if len(replies) > 1 else replies[0]

    reader = reading.Reader(spec or SPEC, ask_values, ask_text, [],
                            match=match)
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
    # The next round sees what was read by its wording, never the entry.
    later = calls[1][1]
    assert later["read"] == [{"value": "CurPol", "quote": CURPOL["quote"]}]
    assert "EN_NPi2100" not in json.dumps(later)
    # A value of any other parameter as it was read.
    _other, calls = read_of(YEAR, ({"next": Y2030}, {"next": None}))
    assert calls[1][1]["read"] == [{"value": "2030",
                                    "quote": Y2030["quote"]}]


def test_a_correction_in_a_round_names_the_wording_never_the_entry():
    match, _ = matcher("EN_NPi2100")
    stray = {"value": "CurPol", "quote": "the CurPol run of another study"}
    read, calls = read_of(LABEL, ({"next": stray}, {"next": CURPOL},
                                  {"next": None}), match=match)
    corrected = calls[1][1]
    assert corrected["corrections"][0]["value"] == "CurPol"
    assert "EN_NPi2100" not in json.dumps(corrected)
    assert read.claims[0]["value"] == "EN_NPi2100"


def test_a_value_of_a_list_matched_apart_is_shown_by_its_wording():
    row = Row("R1", 0, {"value": "EN_NPi2100", "value_raw": "CurPol",
                        "quote": CURPOL["quote"]})
    shown = reading.text_payload(TEXT, LABEL, [], row, "", {})["value"]
    assert shown == {"value": "CurPol", "quote": CURPOL["quote"]}
    year = Row("R1", 0, {"value": 2030, "value_raw": "2030",
                         "quote": Y2030["quote"]})
    shown = reading.text_payload(TEXT, YEAR, [], year, "", {})["value"]
    assert (shown["value"], shown["value_raw"]) == (2030, "2030")


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
        "anyOf"][0]["properties"]["value"] == {"type": "string"}
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


# -- a value stated for several scenarios --------------------------------------

TWO = {"scenario": [{"value": "CurPol",
                     "quote": "Results for the CurPol scenario"},
                    {"value": "NDC", "quote": "the NDC scenario"}]}


def scenario_slot(spec):
    year = spec.by_uri["scenario_year"]
    return next(s for s in fields.axis_slots(year) if s.name == "scenario")


def unmatched_spec():
    """The spec with the scenario of scenario_year shown as a list again."""
    raw = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    year = next(p for p in raw["parameters"] if p["uri"] == "scenario_year")
    year["axes"]["scenario"].pop("matched_apart")
    return runner.fill_dynamic_axes(load_spec(raw), {"scenario": RUNS,
                                                     "scenario_label": RUNS})


def test_a_list_splits_only_where_the_coordinate_is_matched_apart():
    slot = scenario_slot(SPEC)
    a, b = TWO["scenario"]
    assert reading.answers_each(TWO, [slot]) == [{"scenario": a},
                                                 {"scenario": b}]
    assert reading.answers_each({"scenario": a}, [slot]) == [{"scenario": a}]
    assert reading.answers_each({"scenario": []}, [slot]) \
        == [{"scenario": None}]
    plain = scenario_slot(unmatched_spec())
    assert reading.answers_each(TWO, [plain]) == [TWO]
    assert "anyOf" in reading.answer_schema(slot)
    assert reading.answer_schema(plain)["type"] == "object"


def test_a_value_stated_for_several_scenarios_is_one_row_each():
    match, asked = matcher("EN_NPi2100", "EN_INDCi2030_1000f")
    read, _ = read_of(YEAR, ({"next": Y2030}, {"next": None}),
                      groups={"scenario": TWO}, match=match)
    assert [a["name"] for a in asked] == ["CurPol", "NDC"]
    assert [(c["value"], c["scenario"], c["scenario_raw"],
             c["scenario_state"]) for c in read.claims] == [
        ("2030", "EN_NPi2100", "CurPol", READ),
        ("2030", "EN_INDCi2030_1000f", "NDC", READ)]
    assert read.claims[1]["scenario_quote"] == "the NDC scenario"
    assert len(read.probes) == len(read.claims)
    # A list for a coordinate whose list the reading shows is not split: it
    # is no answer, and the value stays one row.
    shown = unmatched_spec()
    alone, _ = read_of(shown.by_uri["scenario_year"],
                       ({"next": Y2030}, {"next": None}),
                       groups={"scenario": TWO}, spec=shown)
    assert len(alone.claims) == 1
    assert alone.claims[0]["scenario_state"] != READ


def test_a_correction_for_one_of_several_scenarios_names_its_wording():
    match, _ = matcher("EN_NPi2100", "EN_INDCi2030_1000f",
                       "EN_INDCi2030_1000f")
    stray = {"scenario": [TWO["scenario"][0],
                          {"value": "NDC",
                           "quote": "the NDC pathway of another study"}]}
    fixed = {"scenario": {"value": "NDC", "quote": "the NDC scenario"}}
    read, calls = read_of(YEAR, ({"next": Y2030}, {"next": None}),
                          groups={"scenario": [stray, fixed]}, match=match)
    (_task, corrected, _shape), = [c for c in calls if c[0] == "scenario"
                                   and c[1].get("corrections")]
    named = corrected["corrections"][0]
    assert (named["coordinate"], named["value"], named["quote"]) \
        == ("scenario", "NDC", "the NDC pathway of another study")
    assert [(c["scenario"], c["scenario_state"]) for c in read.claims] \
        == [("EN_NPi2100", READ), ("EN_INDCi2030_1000f", READ)]


def test_the_combing_makes_one_row_per_scenario_for_the_reading():
    claim = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
             "scenario_state": fields.SAID_UNSTATED}
    batch = Batch(7, YEAR, [WorkItem(7, YEAR, TEXT)], spec=SPEC)
    read = reading.Read(batch, [claim], probes=[{"scenario": "a sentence"}])
    reply = {"rows": [{"row": "R1", **TWO}]}
    match, _ = matcher("EN_NPi2100", "EN_INDCi2030_1000f")
    passages = {(TEXT.owner_kind, TEXT.owner_id): TEXT}
    combing.Comber(SPEC, lambda *a, **k: reply, lambda *a: [],
                   lambda claim, names: {}, match=match)(
        7, [read], passages, [])
    assert [(c["scenario"], c["scenario_raw"], c["scenario_state"])
            for c in read.claims] == [
        ("EN_NPi2100", "CurPol", READ),
        ("EN_INDCi2030_1000f", "NDC", READ)]
    assert read.probes == [{"scenario": "a sentence"}] * 2
    # A pass over a stored harvest re-reads its row in place: the first.
    stored = {"source": "Q1", "value": "2030", "quote": Y2030["quote"],
              "scenario_state": fields.SAID_UNSTATED}
    match, _ = matcher("EN_NPi2100", "EN_INDCi2030_1000f")
    claims = [stored]
    combed = combing.Comber(SPEC, lambda *a, **k: reply, None,
                            lambda claim, names: {}, match=match).comb_groups(
        7, YEAR, TEXT, reading.slots_of(SPEC, YEAR), claims, passages, [],
        coordinates=["scenario"])
    assert claims == [stored] and not combed[0].made
    assert (stored["scenario"], stored["scenario_state"]) \
        == ("EN_NPi2100", READ)
