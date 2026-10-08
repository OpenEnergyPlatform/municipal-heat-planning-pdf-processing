"""Who the retry loop's wait is for.

It was paid after every failed attempt. Three of those attempts are a request
the server already refused, and the 30 s of idle come out of eight transcription
slots — the wait belongs to a server that needs time, not to a verdict.
"""
import openai  # real SDK or the conftest stub
import pytest

from docpipe.reading import Hole
from docpipe.visuals import replies
from docpipe.visuals import vision as V

OK = '{"markdown": "M"}'
ASKED = dict(reply=replies.TABLE)


class _Refused(openai.APIError):
    """An API error carrying an HTTP status, built without an httpx request."""

    def __init__(self, message="image too large", status_code=400):
        Exception.__init__(self, message)
        self.status_code = status_code


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"\x89PNG\r\n")
    return p


@pytest.fixture
def slept(monkeypatch):
    """Every sleep the loop asks for, in seconds."""
    seconds = []
    monkeypatch.setattr(V.time, "sleep", lambda s: seconds.append(s))
    return seconds


def test_a_refused_request_is_not_retried_and_does_not_sleep(
        make_client, seq_responder, png, slept):
    """A 400 is the request being wrong — image too large, context exceeded,
    bad parameter. The same request comes back refused however long we wait."""
    rec = []
    client = make_client(seq_responder([_Refused()]), recorder=rec)

    assert V.call_vision(client, "sys", "user", png, **ASKED) == Hole(
        "refused", "HTTP 400")
    assert len(rec) == 1, "the other three were guaranteed to be refused too"
    assert slept == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_busy_or_broken_server_is_still_waited_out(
        make_client, seq_responder, png, slept, status):
    client = make_client(seq_responder([_Refused("later", status), OK]))

    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "M"}
    assert slept == [5]


def test_a_server_that_stays_busy_is_a_hole_that_says_it_did_not_serve(
        make_client, seq_responder, png, slept):
    client = make_client(seq_responder([_Refused("later", 503)]))

    got = V.call_vision(client, "sys", "user", png, **ASKED)
    assert got.cause == "not_served" and "503" in got.detail
    assert len(slept) == V.MAX_RETRIES - 1


def test_a_server_that_only_times_out_is_a_hole_that_says_it_did_not_serve(
        make_client, seq_responder, openai_error, png):
    client = make_client(seq_responder([openai_error("t", timeout=True)]))
    got = V.call_vision(client, "sys", "user", png, **ASKED)
    assert (got.cause, got.detail) == ("not_served", "timeout")


def test_a_connection_that_never_comes_up_is_a_hole_that_says_it_did_not_serve(
        make_client, seq_responder, png):
    client = make_client(seq_responder([RuntimeError("no route to host")]))
    got = V.call_vision(client, "sys", "user", png, **ASKED)
    assert (got.cause, got.detail) == ("not_served", "RuntimeError")


def test_the_last_attempt_decides_what_the_hole_is(
        make_client, seq_responder, openai_error, png):
    """A server that answered and then went quiet did not serve the item; one
    that was quiet and then answered with something nobody can read did, and
    the cause is the reply's."""
    quiet_last = make_client(seq_responder(
        ["garbage", openai_error("t", timeout=True)]))
    assert V.call_vision(quiet_last, "sys", "user", png, **ASKED).cause == \
        "not_served"
    answered_last = make_client(seq_responder(
        [openai_error("t", timeout=True), "garbage"]))
    assert V.call_vision(answered_last, "sys", "user", png, **ASKED).cause == \
        "no_object"


def test_a_connection_failure_is_still_waited_out(
        make_client, seq_responder, png, slept):
    """No status at all: nothing says the request itself was wrong."""
    client = make_client(seq_responder([RuntimeError("no route to host"), OK]))

    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "M"}
    assert slept == [5]


def test_a_parse_failure_retries_at_once(make_client, seq_responder, png, slept):
    """It came back 200 OK inside the second: the server is healthy and the next
    attempt costs nothing but the request."""
    rec = []
    client = make_client(seq_responder(["no json here", OK]), recorder=rec)

    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "M"}
    assert len(rec) == 2
    assert slept == []
