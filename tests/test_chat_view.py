"""chat_view: every request of a trace is shown with what became of it."""
import importlib.util
import json
import re
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "chat_view", Path(__file__).resolve().parent.parent / "scripts" / "chat_view.py")
chat_view = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chat_view)

PASSAGE = {"passage": {"kind": "table", "lines": [
    "1 Tabelle 4", "2 | Gebaeude | Erdgas MWh/a |", "3 | Rathaus | 1.200 | 27 |"]}}
LIST = {"words": "Heizoel", "list": ["1 Erdgas (means: natural gas)", "2 Heizoel",
                                     "3 Strom"]}


def _record(t, user, content, **notes):
    return {"t": t, "doc": 7, "attempt": 1, "ms": 10, "input": {"messages": [
        {"role": "system", "content": "instruction"},
        {"role": "user", "content": user}]}, "output": content, **notes}


def _trace():
    text = json.dumps(PASSAGE, indent=2)
    coord = {**PASSAGE, "value": {"words": "1.200", "at": "3.2"}}
    follow = {**coord, "answer": {"at": "3.2", "words": "1.200"},
              "what": [{"why": "not_in_quote"}]}
    return [
        {"t": "piece", "id": "p1", "text": text},
        _record("find_ask", {"piece": "p1"},
                {"content": '{"found": [{"at": "3.2", "words": "1.200"}]}',
                 "finish": "stop"}, parameter="energy", owner=4, kind="table"),
        _record("coord_ask", json.dumps(coord),
                {"content": '{"at": "3.2", "words": "1.200"}', "finish": "stop"},
                parameter="energy", coordinate="year", owner=4, value="R1"),
        {"t": "doc_done", "doc": 7},
        _record("follow_ask", json.dumps(follow),
                {"content": '{"at": "3.3", "words": "27"}', "finish": "stop"},
                parameter="energy", coordinate="year", owner=4, value="R1",
                asked="coord"),
        _record("list_ask", json.dumps(LIST), {"error": "Timeout: slow"},
                parameter="energy", coordinate="carrier"),
    ]


def _answered_entry():
    events = _trace()
    events.append(_record("list_ask", json.dumps(LIST),
                          {"content": '{"entry": 2}', "finish": "stop"},
                          parameter="energy", coordinate="carrier"))
    return events


def test_every_ask_is_one_request_in_order():
    reqs = chat_view.requests_of(_trace())
    assert [r["kind"] for r in reqs] == ["find", "coord", "follow", "list"]


def test_check_of_each_request():
    find, coord, follow, lst = chat_view.requests_of(_trace())
    assert lst["answer"] is None and lst["check"] == "no answer"
    assert find["check"] == "taken"
    assert "not_in_quote" in coord["check"] and coord["check"] != "taken"
    assert follow["check"] == "taken"


def test_piece_user_text_is_resolved():
    find = chat_view.requests_of(_trace())[0]
    assert json.loads(find["user"]) == PASSAGE


def test_unreadable_reply_is_named_by_its_error_event():
    events = _trace()
    events.insert(3, {"t": "error", "where": "coord", "kind": "unreadable",
                      "cause": "cut_off", "attempt": 1})
    coord = chat_view.requests_of(events)[1]
    assert coord["check"] == "unreadable: cut_off"


def test_list_entry_is_written_out_with_its_label():
    last = chat_view.requests_of(_answered_entry())[-1]
    assert last["spelled"] == ["2 = Heizoel"]
    wrong = chat_view.requests_of(_trace())[0]
    assert wrong["spelled"] == []


def test_chain_holds_find_and_follow_but_not_unrelated_lists():
    reqs = chat_view.requests_of(_trace())
    assert chat_view.chain_of(reqs, 1) == [0, 1, 2]
    assert chat_view.chain_of(reqs, 2) == [0, 1, 2]
    assert chat_view.chain_of(reqs, 3) == [3]


def test_chain_takes_the_list_entry_asked_for_an_answered_word():
    events = _trace()
    events[-1] = _record("list_ask", json.dumps({**LIST, "words": "1.200"}),
                         {"content": '{"entry": 1}', "finish": "stop"},
                         parameter="energy", coordinate="carrier")
    reqs = chat_view.requests_of(events)
    assert chat_view.chain_of(reqs, 1) == [0, 1, 2, 3]


def test_render_embeds_every_request():
    reqs = chat_view.requests_of(_trace())
    page = chat_view.render(reqs)
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                     page, re.S).group(1)
    assert len(json.loads(data.replace("<\\/", "</"))) == len(reqs)
    assert "</script></script>" not in page


def test_render_of_nothing_has_no_requests():
    page = chat_view.render([])
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                     page, re.S).group(1)
    assert json.loads(data) == []
