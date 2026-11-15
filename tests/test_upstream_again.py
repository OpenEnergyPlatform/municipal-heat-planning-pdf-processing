"""A download whose server fails (a status of the rule
`server_failure_statuses`: 429, 5xx) or that gets no reply (no connection,
one that broke off, a timeout) is asked again, without a limit, after the
wait of a model request whose server failed (`runner.retry_wait`), AND a
download the server refuses otherwise (a 404) or that fails in our own code
raises at once, asked once (owner decision 2026-11-14, "Wiederholen wie
Modell")."""
import http.client
import io
import socket
import urllib.error
from types import SimpleNamespace

import pytest

from docpipe import rules, upstream
from docpipe.extraction import runner


def http_error(code: int, location: str = None) -> urllib.error.HTTPError:
    headers = {"Location": location} if location else {}
    return urllib.error.HTTPError("https://x.test/f", code, "said", headers,
                                  io.BytesIO(b""))


class Answers:
    """A server that answers each request with the next of *said*: an
    exception is raised, bytes are the body read."""

    def __init__(self, *said):
        self.said = list(said)
        self.asked = 0

    def __call__(self, request, timeout=None):
        self.asked += 1
        one = self.said.pop(0)
        if isinstance(one, BaseException):
            raise one
        return io.BytesIO(one)


@pytest.fixture
def waits(monkeypatch):
    rules.reset()
    waited: list = []
    monkeypatch.setattr(upstream.time, "sleep", waited.append)
    return waited


def test_a_failing_server_and_no_reply_are_asked_again_after_the_long_wait(
        monkeypatch, waits):
    answers = Answers(
        http_error(522), http_error(429),
        urllib.error.URLError(ConnectionRefusedError(111, "refused")),
        socket.timeout("timed out"), http.client.IncompleteRead(b"par"),
        b"the file")
    monkeypatch.setattr(upstream.urllib.request, "urlopen", answers)
    assert upstream._get("https://x.test/f") == b"the file"
    assert answers.asked == 6
    # the wait of a model request whose server failed, growing each time
    assert waits == [runner.retry_wait(n, transport=True) for n in range(1, 6)]
    assert waits[0] < waits[1]


@pytest.mark.parametrize("failure, status", [
    (http_error(404), 404), (http_error(403), 403),
    # an address urllib cannot ask: no network failed, our own code did
    (urllib.error.URLError("unknown url type: htp"), None)])
def test_a_refused_download_and_a_fault_of_ours_raise_at_once(
        monkeypatch, waits, failure, status):
    answers = Answers(failure, b"never read")
    monkeypatch.setattr(upstream.urllib.request, "urlopen", answers)
    with pytest.raises(upstream.UpstreamError) as raised:
        upstream._get("https://x.test/f")
    assert raised.value.status == status
    assert answers.asked == 1 and waits == []


def test_which_statuses_are_the_servers_failure_is_the_rule_of_model_requests(
        monkeypatch, waits):
    # without 429 in the rule, a 429 is a refusal like any other
    monkeypatch.setattr(upstream.urllib.request, "urlopen",
                        Answers(http_error(429), b"never read"))
    with rules.overlaid(server_failure_statuses=["500-599", "timeout"]):
        with pytest.raises(upstream.UpstreamError) as raised:
            upstream._get("https://x.test/f")
    assert raised.value.status == 429 and waits == []


def test_how_often_is_the_rule_of_model_requests(monkeypatch, waits):
    # a limit in the rule gives up after as many failures as a model
    # request does; the failure by construction: the answer after them
    # would be read if the rule were not
    answers = Answers(http_error(503), http_error(503), b"never read")
    monkeypatch.setattr(upstream.urllib.request, "urlopen", answers)
    with rules.overlaid(server_retry_most=2):
        with pytest.raises(upstream.UpstreamError) as raised:
            upstream._get("https://x.test/f")
    assert raised.value.status == 503
    assert answers.asked == 2 and waits == [runner.retry_wait(1, True)]


def test_the_latest_release_is_read_after_a_failing_server(monkeypatch,
                                                           waits):
    answers = Answers(http_error(503), http_error(
        302, "https://github.com/o/r/releases/tag/v1"))
    monkeypatch.setattr(upstream.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=answers))
    assert upstream.latest_release("o/r") == "v1"
    assert answers.asked == 2 and waits == [runner.retry_wait(1, True)]
    # a repository the server does not know is refused at once
    missing = Answers(http_error(404))
    monkeypatch.setattr(upstream.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=missing))
    with pytest.raises(upstream.UpstreamError):
        upstream.latest_release("o/gone")
    assert missing.asked == 1
