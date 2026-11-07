"""A request sent word for word a second time in the same document gets the
first one's answer and is not sent, and one sent while its twin is still out
waits for that answer; a request whose twin ended without an answer is sent;
the answer given again costs nothing and its event says so; and every
request is traced with when it was asked, sent and answered (owner decision
2026-11-07, `scheduler.Once`, `scheduler.Repeats`).

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import threading
import time
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from docpipe.extraction import scheduler, stats, trace
from docpipe.extraction.throttle import AdaptiveLimit


def reply(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                 finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=7))


def chat_completion(content):
    """The answer as the client hands it over in a run."""
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 7,
                  "total_tokens": 107}})


class Server:
    """A server that answers each request with what it was asked, numbered,
    and counts what reached it; *fail* the first so many requests, *hold*
    each request until set, *kind* the form of its answers."""

    def __init__(self, fail: int = 0, hold: threading.Event = None,
                 kind=reply):
        self.sent = []
        self.fail = fail
        self.hold = hold
        self.kind = kind
        self.inside = threading.Event()
        self._lock = threading.Lock()

    def create(self, **request):
        with self._lock:
            self.sent.append(request)
            n = len(self.sent)
        self.inside.set()
        if self.hold is not None:
            self.hold.wait(5)
        if n <= self.fail:
            raise ConnectionError("refused")
        return self.kind(
            f"answer {n}: {request['messages'][-1]['content']}")


def client_of(server):
    return scheduler.repeating(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=server.create))), 60, 30)


def request(text, **extra):
    return {"model": "m", "temperature": 0.0, "max_tokens": 400,
            "messages": [{"role": "system", "content": "Read one value."},
                         {"role": "user", "content": text}], **extra}


def asked(client, document, payload, **extra):
    with scheduler.on_behalf(document):
        return client.chat.completions.create(**request(payload, **extra))


# Promise: a request sent again word for word in its document is answered
# with the first answer AND is not sent; by construction, one that differs
# in a word, in a setting or in its document is sent.
def test_a_request_sent_again_in_its_document_is_answered_and_not_sent():
    server = Server()
    client = client_of(server)
    first = asked(client, 7, "the year of 4.367 MWh")
    again = asked(client, 7, "the year of 4.367 MWh")
    assert len(server.sent) == 1
    assert again.choices[0].message.content \
        == first.choices[0].message.content
    asked(client, 7, "the year of 4.368 MWh")            # one word differs
    asked(client, 7, "the year of 4.367 MWh", temperature=0.3)
    asked(client, 8, "the year of 4.367 MWh")            # another document
    assert len(server.sent) == 4


# Promise: a document's answers are kept while it is read, however many
# documents are read at once; by construction, a hundred documents asked in
# turn, each asked again after all the others.
def test_every_document_read_at_once_keeps_its_answers():
    server = Server()
    client = client_of(server)
    for _ in range(2):
        for document in range(100):
            asked(client, document, "the unit of 12")
    assert len(server.sent) == 100


# Promise: a document that is done forgets its answers, so its request sent
# again is sent, AND every other document keeps its own; by construction,
# two documents asked the same, one read out.
def test_a_document_read_out_forgets_its_answers_and_only_its_own():
    server = Server()
    client = client_of(server)
    asked(client, 7, "the sector of 80 GWh")
    asked(client, 8, "the sector of 80 GWh")
    scheduler.read_out(7)
    asked(client, 7, "the sector of 80 GWh")
    asked(client, 8, "the sector of 80 GWh")
    assert len(server.sent) == 3


# Promise: only a request of a document is answered again; by construction,
# the same request of no document (anchors, a run's own questions), sent
# twice, goes out twice.
def test_a_request_of_no_document_is_sent_every_time():
    server = Server()
    client = client_of(server)
    with scheduler.on_behalf(None):
        for _ in range(2):
            client.chat.completions.create(
                **request("an anchor sentence"))
    assert len(server.sent) == 2


# Promise: the answer given again costs nothing: no usage, so no tokens are
# counted, as the client's own answer and as a plain one, AND it is the same
# reply; by construction, the first answer keeps its usage.
@pytest.mark.parametrize("kind", [chat_completion, reply])
def test_the_answer_given_again_costs_nothing(kind):
    client = client_of(Server(kind=kind))
    first = asked(client, 7, "x" * 40)
    again = asked(client, 7, "x" * 40)
    assert first.usage.prompt_tokens == 100
    assert again.usage is None
    assert again.choices[0].message.content \
        == first.choices[0].message.content


# Promise: a request sent while its twin is still out waits for that answer
# and is not sent; by construction, the twin held at the server, two
# requests, one sending.
def test_a_twin_still_out_is_waited_for_and_not_sent_again():
    hold = threading.Event()
    server = Server(hold=hold)
    client = client_of(server)
    got = {}

    def ask(name):
        got[name] = asked(client, 7, "the scenario of 2050")
    first = threading.Thread(target=ask, args=("first",))
    first.start()
    assert server.inside.wait(5)
    second = threading.Thread(target=ask, args=("second",))
    second.start()
    time.sleep(0.2)
    assert len(server.sent) == 1 and "second" not in got
    hold.set()
    first.join(5)
    second.join(5)
    assert len(server.sent) == 1
    assert got["second"].choices[0].message.content \
        == got["first"].choices[0].message.content


# Promise: a twin that ended without an answer leaves the next one to be
# sent, which gets an answer of its own; by construction, the first sending
# is refused.
def test_a_twin_without_an_answer_leaves_the_next_to_be_sent():
    server = Server(fail=1)
    client = client_of(server)
    with pytest.raises(ConnectionError):
        asked(client, 7, "the region of 12 %")
    again = asked(client, 7, "the region of 12 %")
    assert len(server.sent) == 2
    assert again.choices[0].message.content.startswith("answer 2")
    assert again.usage.prompt_tokens == 100
    # The answer it got is the one its next twin gets.
    third = asked(client, 7, "the region of 12 %")
    assert len(server.sent) == 2
    assert third.choices[0].message.content.startswith("answer 2")


# Promise: a waiting twin whose first sending fails is sent itself, and
# never waits without end; by construction, the held first is refused.
def test_a_waiting_twin_whose_first_fails_is_sent_itself():
    hold = threading.Event()
    server = Server(fail=1, hold=hold)
    client = client_of(server)
    got, failed = {}, []

    def ask(name):
        try:
            got[name] = asked(client, 7, "the year of the target")
        except ConnectionError:
            failed.append(name)
    first = threading.Thread(target=ask, args=("first",))
    first.start()
    assert server.inside.wait(5)
    second = threading.Thread(target=ask, args=("second",))
    second.start()
    time.sleep(0.2)
    hold.set()
    first.join(5)
    second.join(5)
    assert failed == ["first"]
    assert len(server.sent) == 2
    assert got["second"].choices[0].message.content.startswith("answer 2")


@pytest.fixture
def traced(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "ENABLED", True)
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    trace.open_trace(tmp_path, lambda document_id: f"plan{document_id}")
    yield tmp_path
    trace.close()
    trace._thread.exchange = None


def reported(response):
    """The event a stage writes for a request it got an answer to."""
    usage = response.usage
    return {"attempt": 1, "ms": 1,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None)}


# Promise: the event of an answer given again says `once` AND the stats count
# it as answered once and not as a request, with no tokens; by construction,
# the first answer's event says neither.
def test_an_answer_given_again_is_traced_once_and_not_counted_as_a_request(
        traced):
    client = client_of(Server())
    for _ in range(3):
        trace.event("read_text_ask", 7,
                    **reported(asked(client, 7, "the scenario of 4 %")))
    trace.close()
    events = [e for e in trace.lines(trace.path_of(traced, "plan7"))
              if e["t"] == "read_text_ask"]
    assert [e.get("once", False) for e in events] == [False, True, True]
    out = stats.from_traces([traced])["requests_by_stage"]["read_text"]
    assert out["requests"] == 1 and out["answered_once"] == 2
    assert out["prompt_tokens"] == 100


# Promise: every reported request carries when it was asked, when it left
# the run's queue and when its answer came, in that order, AND the wait for
# a place shows; by construction, a queue held by another request, and a
# client without a queue, whose wait is not known.
def test_a_request_carries_when_it_was_asked_sent_and_answered(traced):
    limit = AdaptiveLimit(start=1, minimum=1, maximum=1)
    queue = scheduler.Scheduler(limit)
    server = Server()
    client = scheduler.repeating(scheduler.Scheduled(SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            create=server.create))), queue), 60, 30)
    release = threading.Event()
    blocker = queue.submit(lambda: release.wait(5), document=9)
    while limit.in_flight == 0:
        time.sleep(0.01)
    threading.Timer(0.3, release.set).start()
    trace.event("comb_ask", 7, **reported(asked(client, 7, "the year")))
    blocker.result(5)
    plain = client_of(Server())
    trace.event("comb_ask", 7, **reported(asked(plain, 7, "the region")))
    trace.close()
    held, free = [e for e in trace.lines(trace.path_of(traced, "plan7"))
                  if e["t"] == "comb_ask"]
    assert held["asked_at"] <= held["sent_at"] <= held["answered_at"]
    assert held["sent_at"] - held["asked_at"] >= 0.2
    assert "sent_at" not in free
    assert free["asked_at"] <= free["answered_at"]
    flight = stats.from_traces([traced])["requests_at_once"]
    assert flight["seconds_waiting_for_a_place"] >= 0.2
    assert flight["by_stage"]["comb"]["seconds_waiting_for_a_place"] \
        == flight["seconds_waiting_for_a_place"]
