"""The stats count what the harvest wrote to the trace: requests and tokens
per kind of request, the passages ordered and the readings that order
planned, passages read and not read, the pieces of the documents and the
search sentences that were questions, the fields asked once, the works a
publication names; and the stamp schema takes the flow's prompts and the
producer's flow.

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


# Promise: the requests and tokens of every kind are counted under it, a
# follow-up under its own kind, AND a kind that asked nothing counts zero.
def test_requests_and_tokens_are_counted_per_kind(tmp_path):
    out = traced(tmp_path, ask("find_ask", chunk=0),
                 ask("coord_ask", coordinate="year"),
                 ask("coord_ask", coordinate="unit", prompt_tokens=50),
                 ask("follow_ask", asked="coord"))["requests_by_stage"]
    assert out["coord"]["requests"] == 2
    assert out["coord"]["prompt_tokens"] == 150
    assert out["find"]["requests"] == 1 and out["follow"]["requests"] == 1
    # By construction: a kind that asked nothing counts nothing.
    assert out["names"] == {"requests": 0, "prompt_tokens": 0,
                            "completion_tokens": 0, "answered_once": 0}


def test_a_missing_token_count_adds_nothing(tmp_path):
    out = traced(tmp_path, ask("list_ask", prompt_tokens=None,
                               completion_tokens=None))["requests_by_stage"]
    assert out["list"]["requests"] == 1
    assert out["list"]["prompt_tokens"] == 0


def test_an_unread_reading_counts_under_its_reason_and_adds_no_values(
        tmp_path):
    base = {"t": "read", "parameter": "p", "kind": "table", "owner": 4,
            "asked": 1}
    out = traced(tmp_path,
                 {**base, "values": 0, "unread": True, "why": "cut_off"},
                 {**base, "values": 0, "unread": True, "why": "cut_off"},
                 {**base, "values": 0, "unread": True, "why": "no_answer"},
                 {**base, "values": 5, "failed": {"not_an_address": 1},
                  "unanswered": 1})["reading"]
    assert out["readings"] == 4
    assert out["unread_by_reason"] == {"cut_off": 2, "no_answer": 1}
    assert out["values"] == 5
    assert out["refused_first_by_reason"] == {"not_an_address": 1}
    # By construction: a passage read counts its values and no reason.
    read = traced(tmp_path, {**base, "values": 3})["reading"]
    assert read["values"] == 3 and read["unread_by_reason"] == {}


# Promise: the pieces of each document and the search sentences that were
# questions are counted (owner decision 2026-11-08), AND the fields asked
# once with their values, AND the works a publication names; by
# construction, a trace without such events counts none.
def test_pieces_questions_fields_asked_once_and_works_add_up(tmp_path):
    out = traced(
        tmp_path,
        {"t": "asked", "requests": {"find": 4}, "refused": {},
         "question_queries": 2, "chunks": 30, "scope": None},
        {"t": "asked", "requests": {"find": 1}, "refused": {},
         "question_queries": 0, "chunks": 12, "scope": "found"},
        {"t": "docfield", "parameter": "publication_title", "values": 1},
        {"t": "docfield", "parameter": "publication_doi", "values": 0,
         "why": "no_answer"},
        {"t": "works", "works": 4, "new": 3})
    assert out["pieces"] == {"documents": 2, "chunks": 42,
                             "question_queries": 2}
    assert out["asked_once"] == {"fields": 2, "values": 1, "unread": 1}
    assert out["works"] == {"documents": 1, "works": 4,
                            "asked_their_details": 3}
    empty = traced(tmp_path, ask("find_ask"))
    assert empty["pieces"]["documents"] == 0
    assert empty["asked_once"]["fields"] == 0


def test_the_order_events_add_up(tmp_path):
    # Owner decisions 2026-11-08: every piece for every field.
    out = traced(tmp_path,
                 {"t": "order", "scope": None, "passages": 10,
                  "parameters": 6, "first": {}},
                 {"t": "order", "scope": "found", "passages": 3,
                  "parameters": 2, "first": {}})["order"]
    assert out == {"documents": 2, "passages": 13,
                   "readings_planned": 10 * 6 + 3 * 2}
    # By construction: a trace that ordered nothing counts nothing.
    assert traced(tmp_path)["order"] == {"documents": 0, "passages": 0,
                                         "readings_planned": 0}


def stamp(**more):
    return {"spec": SHA, "model": "m", "anchors": "", **more}


def producer(**more):
    return {"pass": "harvest", "model": "m", **more}


def test_a_stamp_of_the_flow_piece_by_piece_validates():
    flow = {f"extraction/{kind}": SHA for kind in schema.PIECE_ASKS}
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


# Promise: the trace schema takes the events of the requests piece by piece
# with what each carries, AND refuses one that breaks their shape.
def test_the_trace_schema_takes_the_requests_piece_by_piece():
    trace = schema.trace_schema()
    read = {"t": "read", "doc": 1, "parameter": "p", "kind": "table",
            "owner": 2, "values": 0, "unread": True, "why": "cut_off",
            "asked": 1}
    for event in (
            read,
            {"t": "find_ask", "doc": 1, "attempt": 1, "parameter": "p",
             "kind": "table", "owner": 2, "chunk": 0},
            {"t": "list_ask", "doc": 1, "attempt": 1, "parameter": "p",
             "coordinate": "sector", "step": "group"},
            {"t": "follow_ask", "doc": 1, "attempt": 1, "asked": "coord",
             "coordinate": "year", "value": "R1"},
            {"t": "names_ask", "doc": 1, "attempt": 1, "kind": "scenario",
             "names": 12},
            {"t": "asked", "doc": 1, "requests": {"find": 3},
             "refused": {}, "question_queries": 1, "chunks": 9},
            {"t": "settled", "doc": 1, "settings": 2, "base": [2021],
             "target": [2040]},
            {"t": "works", "doc": 1, "works": 2, "new": 1}):
        jsonschema.validate(event, trace)
    for broken in (dict(read, why="bored"), dict(read, skipped=2),
                   {"t": "list_ask", "doc": 1, "attempt": 1,
                    "step": "third"},
                   {"t": "read_values_ask", "doc": 1, "attempt": 1},
                   {"t": "phrase_ask", "doc": 1, "attempt": 1, "chunk": 2},
                   {"t": "comb", "doc": 1, "parameter": "p"}):
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
                              "completion_tokens": 20, "answered_once": 0}
    assert out["novel"]["requests"] == 1
    assert out["review"]["requests"] == 0
    assert "rows" not in out and "" not in out


def test_the_trace_schema_takes_the_ask_of_every_stage():
    trace = schema.trace_schema()
    for stage in schema.ASK_STAGES:
        jsonschema.validate({"t": f"{stage}_ask", "doc": 1, "attempt": 1,
                             "ms": 3, "prompt_tokens": 10,
                             "completion_tokens": 2}, trace)
    # by construction: a kind the schema does not name is refused
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"t": "novel_ask", "doc": 1, "attempt": 1}, trace)


# Promise: the cost estimate counts every answered request kind, the
# requests piece by piece, the search sentences, the review and the compute
# step, AND a frame request once, by its frame event and not again by its
# ask.
def test_the_estimate_counts_every_request_kind_once(tmp_path):
    from docpipe import estimate
    (tmp_path / estimate.TRACE_DIR).mkdir()
    kinds = ("phrase_ask", "review_ask", "compute_ask", "frame", "frame_ask",
             *(f"{kind}_ask" for kind in schema.PIECE_ASKS))
    (tmp_path / estimate.TRACE_DIR / "plan.trace.jsonl").write_text("\n".join(
        json.dumps({"doc": 1, **ask(kind)}) for kind in kinds),
        encoding="utf-8")
    documents, sections, counted = estimate._trace_of(
        tmp_path, [("plan", 1)], {1: 10})
    assert (documents, sections) == (1, 10)
    assert {k: n[0] for k, n in counted.items() if n[0]} == {
        kind: 1 for kind in kinds if kind != "frame_ask"}


# Promise: the trace schema takes the order of a document, the sentences it
# is ranked with and the completion, AND refuses one that breaks their shape.
def test_the_trace_schema_takes_the_order_and_the_completion():
    trace = schema.trace_schema()
    ordered = {"t": "order", "doc": 1, "scope": None, "passages": 4,
               "parameters": 6, "first": {"emission": [["table", 2]]}}
    probe = {"t": "seek_probe", "doc": 1, "parameter": "p", "per": "run",
             "text": "Emissions are reported by sector."}
    done = {"t": "completion", "doc": 1, "outcome": "taken",
            "filled": ["publication_doi"], "open": [], "id": "W1",
            "key": "index_doi", "matched": ["liu"]}
    for event in (ordered, probe, done,
                  {"t": "completion", "doc": 1, "outcome": "offline",
                   "open": ["publication_doi"], "detail": "timed out"}):
        jsonschema.validate(event, trace)
    for broken in (dict(ordered, passages="4"),
                   {"t": "seek", "doc": 1, "parameter": "p",
                    "kind": "section", "owner": 1, "rank": 2},
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
        ask("coord_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("coord_ask", asked_at=5.0, sent_at=5.0, answered_at=15.0))[
        "requests_at_once"]
    assert overlap["most"] == 2
    assert overlap["mean"] == round(20 / 15, 2)
    follow = traced(
        tmp_path,
        ask("coord_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("coord_ask", asked_at=10.0, sent_at=10.0, answered_at=20.0))[
        "requests_at_once"]
    assert follow["most"] == 1 and follow["mean"] == 1.0


# Promise: a request waited for a place from its asking to its sending AND was
# with the server from its sending to its answer, per stage; one no queue held
# waited none; by construction, an error that ended without an answer was
# with the server too, and an event without times counts in none.
def test_waiting_and_serving_are_counted_per_stage(tmp_path):
    out = traced(
        tmp_path,
        ask("find_ask", asked_at=0.0, sent_at=4.0, answered_at=10.0),
        ask("list_ask", asked_at=0.0, answered_at=3.0),
        {"t": "error", "where": "search", "kind": "exception", "attempt": 1,
         "asked_at": 1.0, "sent_at": 1.0, "answered_at": 2.0},
        ask("find_ask"))["requests_at_once"]
    assert out["by_stage"]["find"] == {
        "seconds_with_the_server": 6.0, "seconds_waiting_for_a_place": 4.0}
    assert out["by_stage"]["list"] == {
        "seconds_with_the_server": 3.0, "seconds_waiting_for_a_place": 0.0}
    assert out["by_stage"]["search"]["seconds_with_the_server"] == 1.0
    assert out["seconds_waiting_for_a_place"] == 4.0
    untimed = traced(tmp_path, ask("find_ask"))["requests_at_once"]
    assert untimed == {"mean": 0.0, "most": 0, "seconds_with_the_server": 0.0,
                       "seconds_waiting_for_a_place": 0.0, "by_stage": {}}


# Promise: an answer given again (`once`) is no request, adds no tokens AND
# was not with the server; by construction, beside a request that was.
def test_an_answer_given_again_is_no_request_and_not_with_the_server(
        tmp_path):
    out = traced(
        tmp_path,
        ask("list_ask", asked_at=0.0, sent_at=0.0, answered_at=10.0),
        ask("list_ask", once=True, prompt_tokens=None,
            completion_tokens=None, asked_at=1.0, answered_at=9.0))
    assert out["requests_by_stage"]["list"]["requests"] == 1
    assert out["requests_by_stage"]["list"]["answered_once"] == 1
    assert out["requests_by_stage"]["list"]["prompt_tokens"] == 100
    assert out["requests_at_once"]["most"] == 1
    assert out["requests_at_once"]["seconds_with_the_server"] == 10.0


# Promise: the trace record takes a request's times and `once`; by
# construction, a time that is no number is refused.
def test_the_trace_schema_takes_the_times_and_once_of_a_request():
    record = {"t": "coord_ask", "doc": 1, "attempt": 1, "ms": 3,
              "prompt_tokens": None, "completion_tokens": None,
              "input": {}, "output": {}, "asked_at": 1.5, "sent_at": 1.6,
              "answered_at": 2.0, "once": True}
    record_schema = schema.trace_schema()
    jsonschema.validate(record, record_schema)
    jsonschema.validate({"t": "error", "doc": 1, "where": "coord",
                         "kind": "exception", "attempt": 1, "head": "",
                         "tail": "", "asked_at": 1.5, "answered_at": 2.0},
                        record_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**record, "asked_at": "soon"}, record_schema)
