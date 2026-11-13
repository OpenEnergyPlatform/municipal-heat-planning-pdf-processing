"""editor.requests: a trace is read once per state of its file, and the filter
and the sent text are the ones chat_view had."""
import gzip
import json
import os

import pytest

from docpipe.editor import requests as rq


def _ask(kind, user, **notes):
    return {"t": kind + "_ask", "doc": 1, "input": {"messages": [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": user}]},
        "output": {"content": '{"at": "1.1"}', "finish": "stop"}, **notes}


EVENTS = [{"t": "piece", "id": "p1", "text": "x"},
          _ask("find", "Heizoel in Tabelle", parameter="energy", owner=4),
          _ask("coord", "year 2019", parameter="area", owner=5, value="R1")]


def _write(path, events):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("".join(json.dumps(e) + "\n" for e in events))


def test_load_is_cached_until_the_file_changes(tmp_path):
    path = tmp_path / "a.trace.jsonl.gz"
    _write(path, EVENTS)
    traces = rq.Traces(tmp_path)
    first = traces.load("a")
    assert traces.load("a") is first
    _write(path, EVENTS[:2])            # the file changes: one request less
    os.utime(path, ns=(1, 1))
    again = traces.load("a")
    assert again is not first and len(again.requests) == 1


def test_names_need_a_folder_and_load_needs_a_known_name(tmp_path):
    assert rq.Traces(None).names() == []
    assert rq.Traces(tmp_path / "none").names() == []
    _write(tmp_path / "a.trace.jsonl.gz", EVENTS)
    names = rq.Traces(tmp_path).names()
    assert [n["name"] for n in names] == ["a"] and names[0]["bytes"] > 0
    with pytest.raises(KeyError):
        rq.Traces(tmp_path).load("b")


def _requests():
    return rq.requests_of(EVENTS)


@pytest.mark.parametrize("args, kept, dropped", [
    ({"kinds": ["coord_ask"]}, 1, 0),
    ({"fields": ["energy"]}, 0, 1),
    ({"owners": [4]}, 0, 1),
    ({"values": ["R1"]}, 1, 0),
    ({"contains": ["HEIZOEL"]}, 0, 1),
])
def test_keep_decides_per_argument(args, kept, dropped):
    reqs = _requests()
    assert rq.keep(reqs[kept], **args) is True
    assert rq.keep(reqs[dropped], **args) is False
    assert rq.keep(reqs[0]) is True     # no argument keeps everything


def test_the_chain_of_a_value_is_its_own_requests_and_no_others():
    events = [
        _ask("find", "{}", parameter="area", owner=5),
        _ask("coord", "{}", parameter="area", owner=5, value="R1",
             coordinate="year"),
        _ask("search", "{}", parameter="area", owner=5, value="R1",
             coordinate="year"),
        _ask("coord", "{}", parameter="area", owner=5, value="R2",
             coordinate="year"),
        # two requests that read no value: a detail of a work each
        _ask("coord", "{}", parameter="title", coordinate="work"),
        _ask("coord", "{}", parameter="title", coordinate="work"),
    ]
    reqs = rq.requests_of(events)
    assert rq.chain_of(reqs, 1) == rq.chain_of(reqs, 2) == [0, 1, 2]
    assert rq.chain_of(reqs, 3) == [0, 3]
    # the failure by construction: without a value there is nothing to
    # chain, however many requests of the field name none either
    assert rq.chain_of(reqs, 4) == [4] and rq.chain_of(reqs, 5) == [5]


def test_sent_gives_the_messages_character_for_character(tmp_path):
    t = rq.Trace(tmp_path / "a.jsonl", EVENTS)
    assert len(t.event_of) == len(t.requests) == 2
    assert t.sent(1)["messages"][1]["content"] == "year 2019"
    assert t.sent(1)["messages"][1]["content"] != t.sent(0)["messages"][1]["content"]
    assert t.kinds() == ["coord", "find"] and t.fields() == ["area", "energy"]
