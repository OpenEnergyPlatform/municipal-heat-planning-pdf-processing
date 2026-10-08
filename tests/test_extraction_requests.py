"""What the model is sent, request kind by request kind, and in which grammar.

Promised: every request a harvest sends carries the system message of its own
prompt AND the temperature of that prompt's front matter AND, for the rows
request, the reply grammar it has always asked in; and the check sees every
kind, so a kind that stopped sending is found.

The six kinds are the ones the harvest sends as a request of its own: the
rows, one field of them, the frame of a document, the sentence a document is
searched with, the anchor questions, and the second reading of a stored value.
They are built by their own builders against a recording client, with the
reply grammar switched on for every request (LLM_SCHEMA=all), so that the
grammar is part of what is held. The rows grammar is held by a digest as well
as by comparison, because a digest is what survives a refactor of the file
that builds it: sha256 over the schema as sorted JSON, first 16 hex.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from docpipe import prompts
from docpipe.extraction import fields, replies, runner
from docpipe.extraction.pipeline import (Row, Source, WorkItem, group_items)
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ("kwp", "scenarios")
# The grammar of the rows request, with and without the sandbox round, as it
# stood when this check was written. The same for both profiles: it names no
# coordinate of any spec.
GRAMMAR_DIGESTS = {True: "3eb03d2c6a0f12fc", False: "1665cb34f03e1e0d"}
PROMPT_OF = {"rows": runner.ROWS_PROMPT_ID, "field": runner.FIELD_PROMPT_ID,
             "frame": runner.FRAME_PROMPT_ID,
             "phrase": runner.PHRASE_PROMPT_ID,
             "anchors": runner.ANCHORS_PROMPT_ID,
             "review": runner.REVIEW_PROMPT_ID}


def digest(grammar: dict) -> str:
    return hashlib.sha256(json.dumps(grammar, sort_keys=True).encode(
        "utf-8")).hexdigest()[:16]


class Recorder:
    """The model, as far as a request goes: it keeps every keyword it is sent
    and answers with an object no builder takes, so each builder asks on."""

    def __init__(self):
        self.sent: list = []
        recorder = self

        class _Msg:
            content = '{"x": 1}'
            reasoning_content = ""

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = None

        class _Completions:
            @staticmethod
            def create(**kw):
                recorder.sent.append(json.loads(json.dumps(
                    kw, ensure_ascii=False, default=str)))
                return _Resp()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()

    def take(self) -> list:
        sent, self.sent = self.sent, []
        return sent


def _requests(name: str, patch: MonkeyPatch) -> dict:
    """{kind: [request keywords]} for what one profile's harvest sends."""
    patch.setenv("DOCPIPE_PROFILE", name)
    patch.setenv("LLM_SCHEMA", "all")
    spec = load_spec(json.loads((ROOT / "profiles" / name
                                 / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    frame = fields.frame_slots(
        spec, load_profile(name).component("extraction", "FRAME") or ())
    client = Recorder()
    patch.setattr(runner, "_client", lambda: client)
    patch.setattr(runner.time, "sleep", lambda s: None)
    # A retry asks again at a higher temperature: held at the prompt's own, so
    # every request of a kind can be held to it.
    patch.setattr(runner, "RETRY_TEMPERATURE_STEP", 0.0)
    patch.setattr(runner, "CODE_ROUNDS", 2)
    shown = [Source("table", 1, "| Erdgas | 1 |", {"document_id": 7,
                                                   "page": 1}),
             Source("section", 2, "Das Zielszenario 2045.",
                    {"document_id": 7, "page": 2})]
    row = Row("R1", 0, {"value": 1, "quote": "| Erdgas | 1 |",
                        "unit": "MWh/a"})
    out: dict = {}

    harvest = runner.make_harvester(spec=spec)
    for parameter in (spec.parameters[0], None):
        harvest(group_items([WorkItem(7, parameter, shown[0]),
                             WorkItem(7, parameter, shown[1])])[0], [])
    out["rows"] = client.take()

    ask = runner.make_field_asker()
    parameter = spec.parameters[0]
    unit = fields.unit_slot(spec, parameter)
    for slot in [*fields.asked_slots(parameter),
                 *([unit] if unit is not None else [])]:
        ask(shown, [row], slot)
    ask(shown[:1], [row], fields.parameter_slot(spec))
    out["field"] = client.take()

    if frame:
        runner.make_frame_asker()(shown, frame)
    out["frame"] = client.take()

    runner.make_anchors(spec, client=client)
    out["anchors"] = client.take()
    runner.document_anchor(spec, {"name": "Plan"}, client=client)
    out["phrase"] = client.take()

    review = runner.make_review_asker()
    review({"value": 1, "quote": "| Erdgas | 1 |", "unit": "MWh/a",
            "parameter": parameter.uri}, shown, parameter,
           list(fields.asked_slots(parameter)))
    out["review"] = client.take()
    out["_framed"] = bool(frame)
    return out


@pytest.fixture(scope="module", params=PROFILES)
def sent(request):
    with MonkeyPatch.context() as patch:
        yield request.param, _requests(request.param, patch)


def faults_in_text(requests: list, prompt_id: str, profile: str) -> list:
    """The requests whose system message is not the prompt's text, char for
    char."""
    want = prompts.load(prompt_id, load_profile(profile)).text
    return [r for r in requests
            if [m["role"] for m in r["messages"]][:1] != ["system"]
            or r["messages"][0]["content"] != want]


def faults_in_temperature(requests: list, prompt_id: str,
                          profile: str) -> list:
    want = float(prompts.load(prompt_id, load_profile(profile))
                 .meta["temperature"])
    return [r for r in requests if r["temperature"] != want]


def _expected(sent_by_profile) -> list:
    name, got = sent_by_profile
    return [(kind, prompt_id) for kind, prompt_id in PROMPT_OF.items()
            if kind != "frame" or got["_framed"]]


def test_every_kind_of_request_is_seen(sent):
    """A check over no request passes anything. Each kind has at least one,
    and the frame only for the profile that has a frame."""
    name, got = sent
    for kind, _prompt_id in _expected(sent):
        assert got[kind], f"{name}: no {kind} request was sent"
    assert (name == "kwp") is got["_framed"] is bool(got["frame"])


def test_a_request_carries_exactly_the_text_of_its_prompt(sent):
    name, got = sent
    for kind, prompt_id in _expected(sent):
        assert not faults_in_text(got[kind], prompt_id, name), (name, kind)


def test_a_builder_that_appends_text_to_its_prompt_is_found(sent):
    """Built to fail: the request of each kind with one sentence more than
    the prompt has, and the same check over it."""
    name, got = sent
    for kind, prompt_id in _expected(sent):
        longer = copy.deepcopy(got[kind])
        longer[0]["messages"][0]["content"] += " Antworte kurz."
        assert faults_in_text(longer, prompt_id, name) == [longer[0]], kind
        # And a request of another kind is not this kind's prompt either.
        other = next(p for k, p in _expected(sent) if p != prompt_id)
        assert len(faults_in_text(got[kind], other, name)) == len(got[kind])


def test_a_request_carries_the_temperature_of_its_prompt(sent):
    name, got = sent
    for kind, prompt_id in _expected(sent):
        assert not faults_in_temperature(got[kind], prompt_id, name), (
            name, kind)


def test_a_builder_that_changes_the_temperature_is_found(sent):
    name, got = sent
    for kind, prompt_id in _expected(sent):
        warmer = copy.deepcopy(got[kind])
        warmer[0]["temperature"] += 0.1
        assert faults_in_temperature(warmer, prompt_id, name) == [warmer[0]]


def test_the_rows_request_asks_in_the_grammar_it_always_did(sent):
    name, got = sent
    asked = {json.dumps(r["response_format"]["json_schema"]["schema"],
                        sort_keys=True) for r in got["rows"]}
    # Every request of the kind, with the sandbox round (CODE_ROUNDS is 2).
    assert asked == {json.dumps(replies.rows(sandbox=True), sort_keys=True)}
    assert {r["response_format"]["json_schema"]["name"]
            for r in got["rows"]} == {"rows_reply"}


@pytest.mark.parametrize("sandbox", [True, False])
def test_the_rows_grammar_is_the_one_it_was(sandbox):
    assert digest(replies.rows(sandbox=sandbox)) == GRAMMAR_DIGESTS[sandbox]


def test_a_key_added_to_the_rows_grammar_moves_its_digest():
    """Built to fail: one key more in a row, and the digest is another."""
    grammar = copy.deepcopy(replies.rows(sandbox=True))
    grammar["properties"]["tuples"]["items"]["properties"]["parameter"] = {
        "type": ["string", "null"]}
    assert digest(grammar) != GRAMMAR_DIGESTS[True]
    dropped = copy.deepcopy(replies.rows(sandbox=True))
    del dropped["properties"]["need_more"]
    assert digest(dropped) != GRAMMAR_DIGESTS[True]
