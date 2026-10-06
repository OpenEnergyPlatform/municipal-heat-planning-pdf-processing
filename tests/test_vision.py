"""Tests for the vision layer: the grammar, the one object that is read, the
base64 images, the chat call.

Promised for `call_vision`: the reply schema is the grammar of every request
on a server of one's own as on a hosted one AND exactly one JSON object is
read, with its key as text, nothing stripped, cut out or salvaged AND a reply
that is not that object is asked again with its cause named AND what is left
is a Hole with its cause, never content and never a second, unconstrained
request. Each AND has its own tests, each with a case built to break it.
"""
import base64
import json

import pytest

from docpipe import reading
from docpipe.reading import Hole
from docpipe.visuals import replies
from docpipe.visuals import vision as V

TABLE = replies.TABLE
GOOD = '{"markdown": "| a |", "caption": "C"}'


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    return p


def test_the_old_readers_and_the_plain_text_request_are_gone():
    """Removed means removed: nothing in this module strips a fence, cuts an
    object out of text, salvages a cut envelope or asks again without a schema."""
    for name in ("_parse_json_response", "call_vision_plain",
                 "_salvage_truncated", "looks_runaway", "_RUNAWAY"):
        assert not hasattr(V, name), name


def test_image_data_url_roundtrips(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"\x89PNG\r\n")
    url = V._image_data_url(p)
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG\r\n"


def test_check_model_available_requires_exact_match(make_client):
    client = make_client(lambda kw: None, model_id="my-model")
    assert V.check_model_available(client, "my-model")
    assert not V.check_model_available(client, "other-model")


def test_call_vision_happy_path(make_client, seq_responder, png):
    client = make_client(seq_responder([GOOD]))
    assert V.call_vision(client, "sys", "user", png, reply=TABLE) == {
        "markdown": "| a |", "caption": "C"}


def test_a_request_without_its_reply_schema_is_not_made(make_client,
                                                        seq_responder, png):
    """There is no default and no json_object any more: what the reply is
    has to be said."""
    rec: list = []
    client = make_client(seq_responder([GOOD]), recorder=rec)
    with pytest.raises(TypeError):
        V.call_vision(client, "sys", "user", png)
    assert rec == []


def test_call_vision_sends_base64_image_and_the_schema_as_grammar(
        make_client, seq_responder, png, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_SCHEMA", raising=False)
    rec = []
    client = make_client(seq_responder([GOOD]), recorder=rec)
    V.call_vision(client, "sys", "user", png, reply=TABLE)
    content = rec[0]["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # on a server of one's own with LLM_SCHEMA unset: not the json_object it
    # used to be
    assert rec[0]["response_format"] != {"type": "json_object"}
    assert rec[0]["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "table_reply", "schema": replies.TABLE[1]}}


@pytest.mark.parametrize("reply", [replies.TABLE, replies.FIGURE, replies.PAGE])
def test_every_reply_is_sent_under_its_own_name(make_client, seq_responder, png,
                                               reply):
    rec = []
    (key,) = reply[1]["required"]
    client = make_client(seq_responder([json.dumps({key: "x"})]), recorder=rec)
    assert V.call_vision(client, "sys", "user", png, reply=reply) == {key: "x"}
    assert rec[0]["response_format"]["json_schema"] == {
        "name": reply[0], "schema": reply[1]}


def test_call_vision_timeout_escalates_repetition_penalty(
        make_client, seq_responder, openai_error, png):
    rec = []
    client = make_client(
        seq_responder([openai_error("t", timeout=True), GOOD]), recorder=rec)
    assert V.call_vision(client, "sys", "user", png, reply=TABLE) == {
        "markdown": "| a |", "caption": "C"}
    assert rec[1]["extra_body"]["repetition_penalty"] == 1.1


def test_call_vision_exhausts_to_a_hole_that_says_the_server_did_not_serve(
        make_client, seq_responder, openai_error, png):
    client = make_client(seq_responder([openai_error("boom")]))
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got.cause == "not_served"


# ---------------------------------------------------------------------------
# AND 2: exactly one object, its key as text
# ---------------------------------------------------------------------------

def test_a_reply_wrapped_in_prose_is_asked_again_with_its_cause(
        make_client, seq_responder, png):
    """The old code cut the object out of the prose and used it."""
    rec = []
    wrapped = 'Here is the table: {"markdown": "WRONG"} done.'
    client = make_client(seq_responder([wrapped, GOOD]), recorder=rec)
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got["markdown"] == "| a |"
    assert len(rec) == 2
    echo, said = rec[1]["messages"][2:]
    assert echo == {"role": "assistant", "content": wrapped}
    assert "text beside the JSON object" in said["content"]
    assert said["content"].endswith(reading.say("shape_rule"))


@pytest.mark.parametrize("answer", [
    '```json\n{"markdown": "WRONG"}\n```',
    '<think>x</think>{"markdown": "WRONG"}',
    '{"markdown": "WRONG"}{"markdown": "WRONG"}',
])
def test_a_fence_a_think_block_or_a_second_object_is_not_unwrapped(
        make_client, seq_responder, png, answer):
    client = make_client(seq_responder([answer]))
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got == Hole("outside_text")


def test_a_reply_object_without_its_key_is_a_missing_key_not_empty_content(
        make_client, seq_responder, png):
    """V6: `response.get("markdown", "")` read this as an empty table."""
    rec = []
    client = make_client(seq_responder(['{"caption": "only a caption"}']),
                         recorder=rec)
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got == Hole("missing_key")
    assert len(rec) == V.MAX_RETRIES
    assert 'lacked "markdown"' in rec[1]["messages"][3]["content"]


def test_the_key_has_to_be_text(make_client, seq_responder, png):
    client = make_client(seq_responder(['{"markdown": ["a"]}']))
    assert V.call_vision(client, "sys", "user", png, reply=TABLE) == Hole(
        "missing_key")


def test_an_empty_string_is_an_answer(make_client, seq_responder, png):
    """A page that holds no prose answers with an empty markdown; the item or
    the page, not the reader, decides what that is worth."""
    client = make_client(seq_responder(['{"markdown": ""}']))
    assert V.call_vision(client, "sys", "user", png, reply=replies.PAGE) == {
        "markdown": ""}


# ---------------------------------------------------------------------------
# AND 3: what is left is a hole, and nothing fills it in
# ---------------------------------------------------------------------------

def test_four_plain_text_answers_end_as_a_hole_and_no_second_request_is_made(
        make_client, seq_responder, png):
    """The August 2026 shape: the model answers within the second, on a 200,
    in plain markdown. The old code asked a fifth time, without a schema, and
    took the text as content."""
    rec = []
    client = make_client(seq_responder(["| a | b |\n|---|---|\n| 1 | 2 |"]),
                         recorder=rec)
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got == Hole("no_object")
    assert len(rec) == V.MAX_RETRIES, "exactly the retries, and no fifth"
    assert all(r.get("response_format") for r in rec), (
        "none without the schema")


def test_a_cut_envelope_is_never_content(make_client, seq_responder, png):
    cut = '{\n  "markdown": "| Jahr | MWh |\n| --- | --- |\n| 2024 | 12 | | | | |'
    client = make_client(seq_responder([cut]))
    # no finish reason: a server that cut it and said "stop" is a syntax
    # error, asked again like one; the content up to the cut is not taken
    got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got == Hole("syntax")
    assert not isinstance(got, dict)


def test_an_error_of_our_own_after_the_reply_is_a_hole_and_not_an_outage(
        make_client, seq_responder, png, monkeypatch, caplog):
    def broken(choice, key=None, of=list):
        raise ValueError("our own bug")

    monkeypatch.setattr(V.reading, "read", broken)
    rec = []
    client = make_client(seq_responder([GOOD]), recorder=rec)
    with caplog.at_level("ERROR"):
        got = V.call_vision(client, "sys", "user", png, reply=TABLE)
    assert got == Hole("error", "ValueError: our own bug")
    assert len(rec) == 1
    assert "Traceback" in caplog.text
