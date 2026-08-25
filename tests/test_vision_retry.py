"""Who the retry loop's wait is for.

It was paid after every failed attempt. Three of those attempts are a request
the server already refused, and the 30 s of idle come out of eight transcription
slots — the wait belongs to a server that needs time, not to a verdict.
"""
import openai  # real SDK or the conftest stub
import pytest

from docpipe.visuals import vision as V


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

    assert V.call_vision(client, "sys", "user", png) is None
    assert len(rec) == 1, "the other three were guaranteed to be refused too"
    assert slept == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_busy_or_broken_server_is_still_waited_out(
        make_client, seq_responder, png, slept, status):
    client = make_client(seq_responder([_Refused("later", status), '{"a": 1}']))

    assert V.call_vision(client, "sys", "user", png) == {"a": 1}
    assert slept == [5]


def test_a_connection_failure_is_still_waited_out(
        make_client, seq_responder, png, slept):
    """No status at all: nothing says the request itself was wrong."""
    client = make_client(seq_responder([RuntimeError("no route to host"),
                                        '{"a": 1}']))

    assert V.call_vision(client, "sys", "user", png) == {"a": 1}
    assert slept == [5]


def test_a_parse_failure_retries_at_once(make_client, seq_responder, png, slept):
    """It came back 200 OK inside the second: the server is healthy and the next
    attempt costs nothing but the request."""
    rec = []
    client = make_client(seq_responder(["no json here", '{"a": 1}']), recorder=rec)

    assert V.call_vision(client, "sys", "user", png) == {"a": 1}
    assert len(rec) == 2
    assert slept == []
