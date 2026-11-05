"""The trace keeps every model request with what came back (owner decision
2026-11-05): an event that reports a request carries it as it was sent and
what came back, a text the requests repeat stands once per document, the
request comes back character for character, and a file a killed run left is
read up to where it ends."""
import gzip
import json
import threading
from types import SimpleNamespace

import jsonschema
import pytest

from docpipe.extraction import scheduler, schema, trace

PASSAGE = "| Endenergieverbrauch Wärme | 4.367.575 kWh |\n" * 20
SYSTEM = "Lies EINE Passage und nenne den nächsten Wert. " * 20
FORMAT = {"type": "json_schema", "json_schema": {
    "name": "values_reply",
    "schema": {"type": "object",
               "properties": {"next": {"type": ["object", "null"]}}}}}
ASKED = {"attempt": 1, "round": 1, "prompt_tokens": 10,
         "completion_tokens": 2}


def reply(content, finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                 finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))


def client_answering(*answers):
    """The stage's own wrapper (`scheduler.Repeats`) around a server that
    gives *answers* in turn, an exception raised."""
    queue = list(answers)

    def create(**request):
        got = queue.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    return scheduler.repeating(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), 60, 30)


def request(payload, **extra):
    return {"model": "m", "temperature": 0.0, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": payload}],
            "response_format": FORMAT, **extra}


@pytest.fixture
def traced(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "ENABLED", True)
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    trace.open_trace(tmp_path, lambda document_id: f"plan{document_id}")
    yield tmp_path
    trace.close()
    trace._thread.exchange = None


def events_of(directory, name):
    return list(trace.lines(trace.path_of(directory, name)))


def test_a_reported_request_comes_back_as_it_was_sent(traced):
    payloads = [
        json.dumps({"source": PASSAGE, "parameter": {"uri": "energy"},
                    "read": []}, ensure_ascii=False, indent=2),
        json.dumps({"source": PASSAGE, "value": 4367575.5},
                   ensure_ascii=False),
        json.dumps({"source": PASSAGE}, indent=2),
        "Die Antwort war kein JSON-Objekt. Antworte nur mit dem Objekt.",
        "{ kein JSON, nur eine Klammer am Anfang " + PASSAGE,
    ]
    picture = {"type": "image_url",
               "image_url": {"url": "data:image/png;base64," + "QUJD" * 300}}
    asked = [request(p) for p in payloads]
    asked.append({**request("x"), "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": [{"type": "text", "text": payloads[0]},
                                     picture]},
        {"role": "assistant", "content": None}]})
    client = client_answering(*(reply('{"next": null}') for _ in asked))
    for one in asked:
        client.chat.completions.create(**one)
        trace.event("read_values_ask", 7, **ASKED)
    trace.close()
    events = events_of(traced, "plan7")
    pieces = trace.pieces_of(events)
    asks = [e for e in events if e["t"] == "read_values_ask"]
    assert [trace.sent(e, pieces) for e in asks] == asked
    assert all(e["output"] == {"content": '{"next": null}', "finish": "stop"}
               for e in asks)


def test_a_repeated_text_stands_once_in_each_document(traced):
    payload = json.dumps({"source": PASSAGE, "round": 1}, ensure_ascii=False,
                         indent=2)
    client = client_answering(*(reply("{}") for _ in range(5)))
    for document in (7, 7, 7, 8, 8):
        client.chat.completions.create(**request(payload))
        trace.event("read_values_ask", document, **ASKED)
    trace.close()
    for name, asks in (("plan7", 3), ("plan8", 2)):
        events = events_of(traced, name)
        texts = [e["text"] for e in events if e["t"] == trace.PIECE]
        assert len(texts) == len(set(texts))
        assert SYSTEM in texts
        assert json.dumps(PASSAGE, ensure_ascii=False) in texts
        assert sum(e["t"] == "read_values_ask" for e in events) == asks
        # Every request of the document is still whole.
        pieces = trace.pieces_of(events)
        assert all(trace.sent(e, pieces)["messages"][1]["content"] == payload
                   for e in events if e["t"] == "read_values_ask")


def test_the_request_goes_to_the_report_of_its_own_thread(traced):
    client = client_answering(reply("{}"))
    client.chat.completions.create(**request(PASSAGE))
    other = threading.Thread(target=trace.event,
                             args=("read_values_ask", 7), kwargs=ASKED)
    other.start()
    other.join()
    trace.event("read", 7, parameter="energy", values=1)
    trace.event("read_values_ask", 7, **ASKED)
    trace.close()
    events = [e for e in events_of(traced, "plan7") if e["t"] != trace.PIECE]
    assert [e["t"] for e in events] == ["read_values_ask", "read",
                                        "read_values_ask"]
    assert ["input" in e for e in events] == [False, False, True]


def test_a_failed_request_goes_to_its_error_with_what_went_wrong(traced):
    client = client_answering(TimeoutError("read timed out"))
    with pytest.raises(TimeoutError):
        client.chat.completions.create(**request("{}"))
    trace.event("error", 7, where="read_values", kind="exception",
                attempt=1, detail="read timed out")
    trace.close()
    events = events_of(traced, "plan7")
    error = next(e for e in events if e["t"] == "error")
    assert error["output"] == {"error": "TimeoutError: read timed out"}
    sent = trace.sent(error, trace.pieces_of(events))
    assert sent["messages"][1]["content"] == "{}"


def test_a_request_no_event_reported_goes_to_none_after_it(traced):
    client = client_answering(reply("first"), reply("second"))
    client.chat.completions.create(**request("one " * 20))
    client.chat.completions.create(**request("two " * 20))
    trace.event("read_values_ask", 7, **ASKED)
    trace.event("read_values_ask", 7, **{**ASKED, "attempt": 2})
    trace.close()
    asks = [e for e in events_of(traced, "plan7")
            if e["t"] == "read_values_ask"]
    assert [e.get("output", {}).get("content") for e in asks] == ["second",
                                                                  None]


def test_a_trace_cut_off_is_read_up_to_the_cut(tmp_path):
    path = tmp_path / f"plan{trace.SUFFIX}"
    events = [{"t": "read", "doc": 7, "values": n} for n in range(2000)]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events[:1000]:
            handle.write(json.dumps(event) + "\n")
        handle.flush()
        flushed = path.stat().st_size
        for event in events[1000:]:
            handle.write(json.dumps(event) + "\n")
    data = path.read_bytes()
    path.write_bytes(data[:(flushed + len(data)) // 2])
    got = list(trace.lines(path))
    assert got == events[:len(got)]
    assert 1000 <= len(got) < len(events)
    path.write_bytes(data)
    assert list(trace.lines(path)) == events


def test_the_readers_take_both_files_and_the_later_one_first(tmp_path):
    (tmp_path / f"a{trace.PLAIN}").write_text(
        json.dumps({"t": "rows", "doc": 1}) + "\n", encoding="utf-8")
    with gzip.open(tmp_path / f"a{trace.SUFFIX}", "wt",
                   encoding="utf-8") as handle:
        handle.write(json.dumps({"doc": 2, "t": "rows"}) + "\n"
                     + json.dumps({"t": "rowsx", "doc": 2}) + "\n"
                     + json.dumps({"t": "plan", "doc": 2, "of": "rows"})
                     + "\n")
    (tmp_path / f"b{trace.PLAIN}").write_text(
        json.dumps({"t": "plan", "doc": 3}) + "\n" + '{"t": "pl\n'
        + json.dumps({"t": "plan", "doc": 4}) + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text("{}\n", encoding="utf-8")
    assert [p.name for p in trace.files(tmp_path)] == [f"a{trace.SUFFIX}",
                                                       f"b{trace.PLAIN}"]
    # A line broken in the middle of a file costs that line alone.
    assert [e["doc"] for e in trace.lines(trace.path_of(tmp_path, "b"))] \
        == [3, 4]
    assert [e["t"] for e in trace.lines(trace.path_of(tmp_path, "a"),
                                        kinds=("rows",))] == ["rows"]
    assert trace.path_of(tmp_path, "c") is None
    assert list(trace.lines(tmp_path / f"c{trace.SUFFIX}")) == []


def test_a_new_trace_replaces_the_plain_one_of_its_name_and_keeps_it(traced):
    earlier = traced / f"plan7{trace.PLAIN}"
    earlier.write_text(json.dumps({"t": "rows", "doc": 7}) + "\n",
                       encoding="utf-8")
    trace.event("read", 7, parameter="energy", values=1)
    trace.close()
    assert not earlier.exists()
    assert [p.name for p in trace.files(traced)] == [f"plan7{trace.SUFFIX}"]
    assert list(traced.glob(f"archive/*/plan7{trace.PLAIN}"))


def test_the_schema_takes_a_request_with_what_came_back_and_a_piece(traced):
    client = client_answering(reply("{}"))
    client.chat.completions.create(**request(json.dumps({"source": PASSAGE},
                                                        indent=2)))
    trace.event("read_values_ask", 7, **ASKED)
    trace.close()
    events = events_of(traced, "plan7")
    assert {e["t"] for e in events} == {trace.PIECE, "read_values_ask"}
    for event in events:
        jsonschema.validate(event, schema.trace_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"t": trace.PIECE, "doc": 7, "id": "x"},
                            schema.trace_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"t": "read", "doc": 7, "parameter": "energy",
                             "kind": "table", "owner": 1, "values": 1,
                             "asked": 1, "input": {}},
                            schema.trace_schema())
