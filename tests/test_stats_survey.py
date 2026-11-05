"""The stats count what the survey flow wrote to the trace: requests and
tokens per stage with their second rounds, passages read and not read, the
coordinates the combing found open and filled; and the stamp schema takes the
flow's prompts and the producer's flow.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json

import jsonschema
import pytest

from docpipe.extraction import schema, stats

SHA = "a" * 64


def traced(tmp_path, *events):
    """A trace directory with one document's events."""
    (tmp_path / "plan.trace.jsonl").write_text(
        "\n".join(json.dumps({"doc": 1, **e}) for e in events),
        encoding="utf-8")
    return stats.from_traces([tmp_path])


def ask(t, **fields):
    return {"t": t, "attempt": 1, "ms": 5, "prompt_tokens": 100,
            "completion_tokens": 10, **fields}


def test_requests_and_tokens_are_counted_per_stage(tmp_path):
    out = traced(tmp_path, ask("survey_ask"), ask("read_values_ask", round=1),
                 ask("read_values_ask", round=2, prompt_tokens=50))[
        "requests_by_stage"]
    assert out["read_values"]["requests"] == 2
    assert out["read_values"]["prompt_tokens"] == 150
    assert out["survey"]["requests"] == 1
    # By construction: a stage that asked nothing counts nothing.
    assert out["comb"] == {"requests": 0, "prompt_tokens": 0,
                           "completion_tokens": 0, "second_rounds": 0}


def test_only_an_event_with_corrections_is_a_second_round(tmp_path):
    out = traced(tmp_path, ask("read_text_ask"),
                 ask("read_text_ask", corrections=0),
                 ask("read_text_ask", corrections=3))["requests_by_stage"]
    assert out["read_text"]["requests"] == 3
    assert out["read_text"]["second_rounds"] == 1


def test_a_missing_token_count_adds_nothing(tmp_path):
    out = traced(tmp_path, ask("comb_ask", prompt_tokens=None,
                               completion_tokens=None))["requests_by_stage"]
    assert out["comb"]["requests"] == 1
    assert out["comb"]["prompt_tokens"] == 0


def test_an_unread_reading_counts_under_its_reason_and_adds_no_values(
        tmp_path):
    base = {"t": "read", "parameter": "p", "kind": "table", "owner": 4,
            "asked": 1}
    out = traced(tmp_path,
                 {**base, "values": 0, "unread": True, "why": "cut_off"},
                 {**base, "values": 0, "unread": True, "why": "cut_off"},
                 {**base, "values": 0, "unread": True, "why": "no_answer"},
                 {**base, "values": 5, "failed": {"unquoted": 1},
                  "unanswered": 1})["reading"]
    assert out["readings"] == 4
    assert out["unread_by_reason"] == {"cut_off": 2, "no_answer": 1}
    assert out["values"] == 5
    assert out["refused_first_by_reason"] == {"unquoted": 1}
    # By construction: a passage read counts its values and no reason.
    read = traced(tmp_path, {**base, "values": 3})["reading"]
    assert read["values"] == 3 and read["unread_by_reason"] == {}


def test_comb_events_add_up_open_filled_and_exhausted_coordinates(tmp_path):
    base = {"t": "comb", "parameter": "p", "kind": "section", "owner": 2,
            "rows": 3, "asked": 1, "hits": 4, "fetched": 1, "searched": 1,
            "missed": 0, "corrected": 0}
    out = traced(tmp_path,
                 {**base, "open": 5, "filled": 3, "exhausted": 0},
                 {**base, "open": 4, "filled": 0, "exhausted": 4})["combing"]
    assert out["passages"] == 2
    assert out["coordinates_open"] == 9
    assert out["coordinates_filled"] == 3
    assert out["coordinates_exhausted"] == 4
    assert out["hits_shown"] == 8
    # By construction: no comb event, no combed coordinate.
    empty = traced(tmp_path, ask("comb_ask"))["combing"]
    assert empty["passages"] == 0 and empty["coordinates_open"] == 0


def test_the_survey_events_add_up(tmp_path):
    base = {"t": "survey", "scope": None, "contexts": 2, "budget": 1000,
            "tuples": 3}
    out = traced(tmp_path,
                 {**base, "passages": 10, "none": 4, "dropped": 1,
                  "unanswered": 0, "complete": True,
                  "by_parameter": {"a": 5, "b": 1}},
                 {**base, "passages": 6, "none": 2, "dropped": 0,
                  "unanswered": 2, "complete": False,
                  "by_parameter": {"a": 2}})["survey"]
    assert out["documents"] == 2
    assert out["complete"] == 1
    assert out["passages"] == 16
    assert out["passages_without_parameter"] == 6
    assert out["passages_unanswered"] == 2
    assert out["answers_not_taken"] == 1
    assert out["passages_by_parameter"] == {"a": 7, "b": 1}


def stamp(**more):
    body = {"spec": SHA, "model": "m", "anchors": "",
            "extraction/queries": SHA, "extraction/anchors": SHA,
            "extraction/rows": SHA, "extraction/field": SHA}
    return {**body, **more}


def producer(**more):
    return {"pass": "harvest", "model": "m", **more}


def test_a_stamp_of_the_survey_flow_validates():
    flow = {"extraction/survey": SHA, "extraction/read_values": SHA,
            "extraction/read_text": SHA, "extraction/comb": SHA}
    jsonschema.validate(
        stamp(**flow, producers=[producer(flow="survey")]),
        schema.stamp_schema())
    for gone in ("extraction/other", "extraction/read_cells",
                 "extraction/read_table"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(stamp(**{gone: SHA}), schema.stamp_schema())


def test_a_producer_flow_off_the_list_is_refused():
    jsonschema.validate(stamp(producers=[producer(flow="fieldwise")]),
                        schema.stamp_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(stamp(producers=[producer(flow="other")]),
                            schema.stamp_schema())


def test_the_trace_schema_takes_the_new_kinds_and_refuses_a_broken_one():
    trace = schema.trace_schema()
    jsonschema.validate({"t": "comb", "doc": 1, "parameter": "p",
                         "kind": "table", "owner": 2, "rows": 1, "open": 1,
                         "filled": 0, "asked": 1, "hits": 0, "fetched": 0,
                         "searched": 0, "missed": 0, "corrected": 0,
                         "exhausted": 1}, trace)
    read = {"t": "read", "doc": 1, "parameter": "p", "kind": "table",
            "owner": 2, "values": 0, "unread": True, "why": "cut_off",
            "asked": 1}
    jsonschema.validate(read, trace)
    jsonschema.validate({"t": "comb_ask", "doc": 1, "attempt": 1}, trace)
    # A values request counts its round, a group request names its value.
    jsonschema.validate({"t": "read_values_ask", "doc": 1, "attempt": 1,
                         "round": 2}, trace)
    jsonschema.validate({"t": "read_text_ask", "doc": 1, "attempt": 1,
                         "group": "frame", "value": "R1"}, trace)
    for broken in (dict(read, why="bored"), dict(read, skipped=2),
                   dict(read, table=True),
                   {"t": "read_values_ask", "doc": 1, "attempt": 1},
                   {"t": "read_text_ask", "doc": 1, "attempt": 1},
                   {"t": "read_table_ask", "doc": 1, "attempt": 1}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, trace)
