"""A reply that parses but lacks a key its schema requires at the top is not
the object that was asked for: it is asked again as missing_key, the retry
naming the key, in every request of the stage that goes out with a schema
(the survey and the two reading requests). A
reply that has every key the top requires is taken as it is, whatever it
leaves out below. The combing requires no key: a coordinate it did not find
is left out, so `{}` is its reply that found nothing and asks for nothing
(owner decision 2026-11-06). Each promise has a case that breaks it by
construction beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import combing, reading, runner, survey
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = reading.slots_of(SPEC, EMISSION)
PROMPT = SimpleNamespace(meta={}, text="x")


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


REQUESTS = ((reading.values_response_format(EMISSION, True), "read_values",
             "value", {"value": None}),
            (survey.response_format(survey.parameters_of(SPEC),
                                    survey.tuple_slots(SPEC)), "survey",
             "parameters", {"parameters": ["out:none"]}),
            (reading.text_response_format(SLOTS), "read_text", SLOTS[0].name,
             {slot.name: {"value": "out:unstated"} for slot in SLOTS}))
COMB = combing.comb_response_format(SLOTS)


def test_a_reply_without_its_keys_is_asked_again_naming_the_key(faults):
    for shape, where, key, whole in REQUESTS:
        faults.clear()
        client, sent = replying("{}", json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert faults == ["missing_key"] and len(sent) == 2, where
        assert f'"{key}"' in told(sent[1])


def test_a_reply_in_a_wrapper_the_reply_lost_is_asked_again(faults):
    # Owner decision 2026-11-06: no wrapper. The survey's reply as it was
    # before and a value inside "next" lack the key their top requires.
    for shape, where, key, wrapped, whole in (
            (REQUESTS[1][0], "survey", "parameters",
             {"passages": {"P1": {"parameters": ["out:none"]}}},
             {"parameters": ["out:none"]}),
            (REQUESTS[0][0], "read_values", "value", {"next": None},
             {"value": None})):
        faults.clear()
        client, sent = replying(json.dumps(wrapped), json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert faults == ["missing_key"] and f'"{key}"' in told(sent[1])


def test_a_reply_with_every_key_the_top_requires_is_taken_as_it_is(faults):
    # Below the top it may leave out what the schema asks there: the
    # reading asks for that by name, the request does not.
    for shape, where, key, whole in REQUESTS:
        client, sent = replying(json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert len(sent) == 1 and faults == [], where
    # The combing requires no key: {} found nothing and asks for nothing.
    assert "required" not in COMB["json_schema"]["schema"]
    for whole in ({}, {"year": {"value": 2030, "quote": "für 2030"}}):
        client, sent = replying(json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], COMB, 7, "comb",
                                     "year") == whole
        assert len(sent) == 1 and faults == []


