"""A reply that parses but lacks a key its schema requires at the top is not
the object that was asked for: it is asked again as missing_key, the retry
naming the key, in every request of the stage that goes out with a schema
(the two reading requests, the places and the field requests). A
reply that has every key the top requires is taken as it is, whatever it
leaves out below. Each promise has a case that breaks it by construction
beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import reading, runner
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = reading.slots_of(SPEC, EMISSION)
PROMPT = SimpleNamespace(meta={}, text="x")
SOURCE = Source(owner_kind="section", owner_id=5, provenance={},
                text="Die Emissionen betragen 300 t CO2.")


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
             "next", {"next": None}),
            (reading.text_response_format(SLOTS), "read_text", SLOTS[0].name,
             {slot.name: {"value": "out:unstated"} for slot in SLOTS}))


def test_a_reply_without_its_keys_is_asked_again_naming_the_key(faults):
    for shape, where, key, whole in REQUESTS:
        faults.clear()
        client, sent = replying("{}", json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert faults == ["missing_key"] and len(sent) == 2, where
        assert f'"{key}"' in told(sent[1])


def test_a_reply_with_every_key_the_top_requires_is_taken_as_it_is(faults):
    # Below the top it may leave out what the schema asks there: the
    # reading asks for that by name, the request does not.
    for shape, where, key, whole in REQUESTS:
        client, sent = replying(json.dumps(whole))
        assert runner.ask_in_grammar(client, PROMPT, [], shape, 7, where,
                                     key) == whole
        assert len(sent) == 1 and faults == [], where


def test_a_places_reply_without_its_hits_is_asked_again(monkeypatch, faults,
                                                       tmp_path):
    client, sent = replying("{}", '{"hits": []}')
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(runner.prompts, "load", lambda *a, **k: PROMPT)
    places = runner.make_places(None, SPEC, tmp_path,
                                every=lambda *a, **k: [SOURCE])
    assert places.ask([SOURCE], 7) == {"hits": []}
    assert faults == ["missing_key"] and '"hits"' in told(sent[1])


def test_a_field_reply_without_its_fields_is_asked_again(monkeypatch, faults):
    slot = next(s for s in SLOTS if s.name == "unit")
    answered = {"fields": {"unit": {"answers": {"R1": {
        "value": "t CO2", "quote": "300 t CO2"}}}}}
    client, sent = replying("{}", json.dumps(answered))
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(runner.prompts, "load", lambda *a, **k: PROMPT)
    ask = runner.make_field_asker()
    rows = [Row(label="R1", item_index=0, claim={"value": 300})]
    got = ask([SOURCE], rows, [slot], document_id=7)
    assert got["fields"]["unit"]["answers"]["R1"]["value"] == "t CO2"
    assert faults == ["missing_key"] and '"fields"' in told(sent[1])
