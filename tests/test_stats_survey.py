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
                           "completion_tokens": 0, "second_rounds": 0,
                           "answered_once": 0}


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
                 {**base, "open": 5, "filled": 3, "exhausted": 0,
                  "judged": 3, "turned": 1},
                 {**base, "open": 4, "filled": 0, "exhausted": 4,
                  "listed": 2})["combing"]
    assert out["passages"] == 2
    assert out["coordinates_open"] == 9
    assert out["coordinates_filled"] == 3
    assert out["coordinates_exhausted"] == 4
    assert out["hits_shown"] == 8
    # The lists of the next passages the run added (owner decision
    # 2026-11-06), none in an event written before them.
    assert out["lists_added"] == 2
    # The checks of finds quoted from another passage and the finds they
    # turned (owner decision 2026-11-07), none in an event without them.
    assert (out["check_requests"], out["finds_turned"]) == (3, 1)
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


# Promise: every `<stage>_ask` kind is counted under its stage, one no list
# names as well, AND a known stage that asked nothing counts zero, AND an
# event that is no request counts as none (owner decision 2026-11-05).
def test_every_ask_kind_is_counted_under_its_stage(tmp_path):
    out = traced(tmp_path, ask("phrase_ask", parameter="p"),
                 ask("compute_ask"), ask("compute_ask", prompt_tokens=7),
                 ask("novel_ask"), {"t": "_ask", "attempt": 1},
                 {"t": "rows", "attempt": 1, "prompt_tokens": 100})[
        "requests_by_stage"]
    assert out["phrase"]["requests"] == 1
    assert out["compute"] == {"requests": 2, "prompt_tokens": 107,
                              "completion_tokens": 20, "second_rounds": 0,
                              "answered_once": 0}
    assert out["novel"]["requests"] == 1
    assert out["review"]["requests"] == 0
    assert "rows" not in out and "" not in out


def test_the_trace_schema_takes_the_ask_of_every_stage():
    trace = schema.trace_schema()
    for stage in ("phrase", "frame", "review", "compute", "comb_check"):
        jsonschema.validate({"t": f"{stage}_ask", "doc": 1, "attempt": 1,
                             "ms": 3, "prompt_tokens": 10,
                             "completion_tokens": 2}, trace)
    # by construction: a kind the schema does not name is refused
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"t": "novel_ask", "doc": 1, "attempt": 1}, trace)


# Promise: the cost estimate counts every answered request kind, the search
# sentences, the review, the compute step, the naming's request over all
# names, the plan's years and the comb's check too, AND a frame request once,
# by its frame event and not again by its ask.
def test_the_estimate_counts_every_request_kind_once(tmp_path):
    from docpipe import estimate
    (tmp_path / estimate.TRACE_DIR).mkdir()
    (tmp_path / estimate.TRACE_DIR / "plan.trace.jsonl").write_text("\n".join(
        json.dumps({"doc": 1, **ask(kind)}) for kind in (
            "phrase_ask", "review_ask", "compute_ask", "frame", "frame_ask",
            "survey_ask", "naming_groups_ask", "years_ask",
            "comb_check_ask")), encoding="utf-8")
    documents, sections, counted = estimate._trace_of(
        tmp_path, [("plan", 1)], {1: 10})
    assert (documents, sections) == (1, 10)
    assert {k: n[0] for k, n in counted.items() if n[0]} == {
        "phrase_ask": 1, "review_ask": 1, "compute_ask": 1, "frame": 1,
        "survey_ask": 1, "naming_groups_ask": 1, "years_ask": 1,
        "comb_check_ask": 1}


# Promise: a document's search for a parameter the survey named no passage for
# counts once however far the walk down its list went, AND each passage the
# walk read counts under its parameter; a trace from before the walk, which
# names no rank, counts once (owner decision 2026-11-05).
def seek(parameter, rank=None, owner=1):
    event = {"t": "seek", "parameter": parameter, "kind": "section",
             "owner": owner}
    return event if rank is None else {**event, "rank": rank}


def test_a_search_counts_once_a_document_and_each_passage_walked(tmp_path):
    out = traced(tmp_path, seek("p", 1), seek("p", 2, 2), seek("p", 3, 3),
                 seek("q"))
    assert out["parameters_sought_by_parameter"] == {"p": 1, "q": 1}
    assert out["passages_sought_by_parameter"] == {"p": 3, "q": 1}
    # the failure by construction: a walk's later passage alone is no search
    out = traced(tmp_path, seek("p", 2, 2))
    assert out["parameters_sought_by_parameter"] == {}
    assert out["passages_sought_by_parameter"] == {"p": 1}


# Promise: the trace schema takes the events of that search, its sentences
# and the completion, AND refuses one that breaks their shape.
def test_the_trace_schema_takes_the_search_and_the_completion():
    trace = schema.trace_schema()
    walked = {"t": "seek", "doc": 1, **seek("p", 2, 3)}
    probe = {"t": "seek_probe", "doc": 1, "parameter": "p", "per": "run",
             "text": "Emissions are reported by sector."}
    done = {"t": "completion", "doc": 1, "outcome": "taken",
            "filled": ["publication_doi"], "open": [], "id": "W1",
            "key": "index_doi", "matched": ["liu"]}
    for event in (walked, probe, done,
                  {"t": "completion", "doc": 1, "outcome": "offline",
                   "open": ["publication_doi"], "detail": "timed out"}):
        jsonschema.validate(event, trace)
    for broken in (dict(walked, rank=0),
                   {k: v for k, v in walked.items() if k != "rank"},
                   dict(probe, per="page"), dict(done, record={}),
                   {k: v for k, v in done.items() if k != "open"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, trace)


# Promise: the requests with the server at once are their seconds with it
# over the time from the first sending to the last answer, AND the most at one
# moment, AND an answer and a sending at the same moment do not overlap; by
# construction, two requests that overlap and two that follow each other.
def test_requests_at_once_are_their_mean_and_their_most(tmp_path):
    overlap = traced(
        tmp_path,
        ask("comb_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("comb_ask", asked_at=5.0, sent_at=5.0, answered_at=15.0))[
        "requests_at_once"]
    assert overlap["most"] == 2
    assert overlap["mean"] == round(20 / 15, 2)
    follow = traced(
        tmp_path,
        ask("comb_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("comb_ask", asked_at=10.0, sent_at=10.0, answered_at=20.0))[
        "requests_at_once"]
    assert follow["most"] == 1 and follow["mean"] == 1.0


# Promise: a request waited for a place from its asking to its sending AND was
# with the server from its sending to its answer, per stage; one no queue held
# waited none; by construction, an error that ended without an answer was
# with the server too, and an event without times counts in none.
def test_waiting_and_serving_are_counted_per_stage(tmp_path):
    out = traced(
        tmp_path,
        ask("read_values_ask", asked_at=0.0, sent_at=4.0, answered_at=10.0),
        ask("survey_ask", asked_at=0.0, answered_at=3.0),
        {"t": "error", "where": "comb", "kind": "exception", "attempt": 1,
         "asked_at": 1.0, "sent_at": 1.0, "answered_at": 2.0},
        ask("read_values_ask"))["requests_at_once"]
    assert out["by_stage"]["read_values"] == {
        "seconds_with_the_server": 6.0, "seconds_waiting_for_a_place": 4.0}
    assert out["by_stage"]["survey"] == {
        "seconds_with_the_server": 3.0, "seconds_waiting_for_a_place": 0.0}
    assert out["by_stage"]["comb"]["seconds_with_the_server"] == 1.0
    assert out["seconds_waiting_for_a_place"] == 4.0
    untimed = traced(tmp_path, ask("read_values_ask"))["requests_at_once"]
    assert untimed == {"mean": 0.0, "most": 0, "seconds_with_the_server": 0.0,
                       "seconds_waiting_for_a_place": 0.0, "by_stage": {}}


# Promise: every event that reports a request with its times counts, whatever
# its kind, under its stage: `<stage>_ask` names it, an error says where it
# was, any other is its own; by construction, requests of the frame, the
# rows and a field beside one of the comb, all four out at one moment.
def test_every_request_with_its_times_counts_whatever_its_kind(tmp_path):
    out = traced(
        tmp_path,
        ask("comb_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        {"t": "frame", "attempt": 1, "prompt_tokens": 9, "asked_at": 0.0,
         "sent_at": 2.0, "answered_at": 6.0},
        {"t": "rows", "attempt": 1, "prompt_tokens": 9, "asked_at": 1.0,
         "sent_at": 1.0, "answered_at": 4.0},
        {"t": "field", "slot": "year", "stage": "own", "attempt": 1,
         "prompt_tokens": 9, "asked_at": 3.0, "answered_at": 5.0})[
        "requests_at_once"]
    assert set(out["by_stage"]) == {"comb", "frame", "rows", "field"}
    assert out["by_stage"]["frame"] == {
        "seconds_with_the_server": 4.0, "seconds_waiting_for_a_place": 2.0}
    assert out["most"] == 4


# Promise: an answer given again (`once`) is no request, adds no tokens AND
# was not with the server; by construction, beside a request that was.
def test_an_answer_given_again_is_no_request_and_not_with_the_server(
        tmp_path):
    out = traced(
        tmp_path,
        ask("comb_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("comb_ask", once=True, prompt_tokens=None,
            completion_tokens=None, asked_at=1.0, answered_at=9.0))
    assert out["requests_by_stage"]["comb"]["requests"] == 1
    assert out["requests_by_stage"]["comb"]["answered_once"] == 1
    assert out["requests_by_stage"]["comb"]["prompt_tokens"] == 100
    assert out["requests_at_once"]["most"] == 1
    assert out["requests_at_once"]["seconds_with_the_server"] == 10.0


# Promise: the trace record takes a request's times and `once`; by
# construction, a time that is no number is refused.
def test_the_trace_schema_takes_the_times_and_once_of_a_request():
    record = {"t": "comb_ask", "doc": 1, "attempt": 1, "ms": 3,
              "prompt_tokens": None, "completion_tokens": None,
              "input": {}, "output": {}, "asked_at": 1.5, "sent_at": 1.6,
              "answered_at": 2.0, "once": True}
    record_schema = schema.trace_schema()
    jsonschema.validate(record, record_schema)
    jsonschema.validate({"t": "error", "doc": 1, "where": "comb",
                         "kind": "exception", "attempt": 1, "head": "",
                         "tail": "", "asked_at": 1.5, "answered_at": 2.0},
                        record_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "asked_at": "soon"}, record_schema)
