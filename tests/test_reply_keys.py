"""A reply that parses but lacks a key its schema requires at the top is not
the object that was asked for: it is asked again as missing_key, the retry
naming the key, in every kind of request of the harvest piece by piece
(addressed.py). A reply that has every key the top requires is taken as it
is. A coordinate's answer that says nothing shown states it (at 0) is taken
as it is: the sentence a search goes with is a request of its own (owner
decision 2026-11-09). Each promise has a case that breaks it by
construction beside the one that keeps it."""
import json
from types import SimpleNamespace

import pytest

from docpipe.extraction import addressed, runner

PROMPT = SimpleNamespace(meta={}, text="x", placeholders=frozenset())
# (grammar, kind, the key a fault names, a whole reply)
REQUESTS = (
    (addressed.found_format(), "find", "found",
     {"found": [{"at": "3.2", "words": "750.940"}]}),
    (addressed.coord_format(False), "coord", "at",
     {"at": "3", "words": "2019"}),
    (addressed.coord_format(True), "coord", "found",
     {"found": [{"at": "3", "words": "Erdgas"}]}),
    (addressed.entry_format(), "list", "entry", {"entry": 2}),
    (addressed.entry_format(several=True, new=True), "names", "entry",
     {"entry": ["new"]}),
    (addressed.lines_format(), "transcribe", "caption",
     {"caption": ["Titel"], "numbers": ["2019 | Erdgas | 245 GWh"]}),
    (addressed.about_format(), "check", "about", {"about": "no"}),
    (addressed.found_format(closed=True), "find", "found",
     {"found": [{"entry": 2, "at": "3.2", "words": "Erdgas"}]}),
    (addressed.work_format(), "work", "found",
     {"found": [{"at": "3.1", "words": "IRENA 2018"}], "own": {"at": 0}}),
    (addressed.work_choice_format(), "coord", "entry",
     {"entry": 1, "at": "2", "words": "our scenarios"}),
    (addressed.phrase_format(), "phrase", "phrase",
     {"phrase": "Der Endenergieverbrauch betrug 2022 rund 512 GWh/a."}),
)


def replying(*said):
    """A client answering *said* in turn; the conversations it was sent."""
    told = iter(said)
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=next(told)))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), sent


@pytest.fixture
def faults(monkeypatch):
    """The causes the requests trace for the replies they could not take."""
    causes = []
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "answer_room", lambda *a, **k: 4096)
    monkeypatch.setattr(runner.trace, "event", lambda name, *a, **f: (
        causes.append(f.get("cause")) if name == "error" else None))
    return causes


def told(conversation) -> str:
    """What the retry said to the model: the last message it was sent."""
    return conversation[-1]["content"]


def test_a_reply_without_its_keys_is_asked_again_naming_the_key(faults):
    for shape, where, key, whole in REQUESTS:
        faults.clear()
        client, sent = replying("{}", json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert faults == ["missing_key"] and len(sent) == 2, where
        assert f'"{key}"' in told(sent[1])


def test_a_reply_with_every_key_the_top_requires_is_taken_as_it_is(faults):
    for shape, where, key, whole in REQUESTS:
        client, sent = replying(json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert len(sent) == 1 and faults == [], where


def test_a_coordinate_found_nowhere_is_taken_without_a_sentence(faults):
    for shape, where, whole in (
            (addressed.coord_format(False), "coord", {"at": 0}),
            (addressed.coord_format(False, more=True), "search",
             {"at": 0, "more": [{"get": "next"}]})):
        faults.clear()
        client, sent = replying(json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     "at") == whole
        assert len(sent) == 1 and faults == [], where
    # the failure by construction: an answer without its address is asked
    # again
    faults.clear()
    client, sent = replying(json.dumps({"words": "2019"}),
                            json.dumps({"at": 0}))
    assert runner.ask_in_grammar(client, PROMPT, [],
                                 addressed.coord_format(False), 7, "coord",
                                 "at") == {"at": 0}
    assert faults == ["missing_key"] and '"at"' in told(sent[1])
