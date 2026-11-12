"""A request the server failed is asked again after the long wait, a refused
one is asked again three times at most after the short wait, and one given up
on that the server never served or refused to the end leaves its document
unfinished (owner decision 2026-11-09). The rule stands once
(`runner.Failures`), and every request of the stage follows it; a search
refused to the end fails its document (`runner.persistently`). Each promise
has a case that breaks it beside the one that keeps it."""
import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from docpipe.extraction import runner

from conftest import in_turn
from docpipe.prompts import Prompt

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "docpipe" / "extraction"
# The clients every other client of the stage is made of: they pass a request
# on and send none of their own.
WRAPPERS = {"scheduler.py", "throttle.py"}


class Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def slow():
    return openai.APITimeoutError(request=httpx.Request("POST", "http://x"))


@pytest.fixture
def waits(monkeypatch):
    """The curve of each wait, (attempt, the server's failure), and a count of
    unfinished documents of this test's own."""
    taken = []
    monkeypatch.setattr(runner, "retry_wait",
                        lambda n, transport=False:
                        taken.append((n, transport)) or 0.0)
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    return taken


# -- the rule ----------------------------------------------------------------

def test_a_server_error_is_asked_again_after_the_long_wait(waits):
    failures = runner.Failures(7)
    assert failures.failed(Status(500)) is True
    failures.wait(1)
    assert waits == [(1, True)]


def test_a_reply_after_it_waits_the_short_curve(waits):
    failures = runner.Failures(7)
    failures.failed(Status(500))
    failures.answered()
    failures.wait(2)
    assert waits == [(2, False)]


def test_a_refusal_is_asked_again_three_times_at_most_after_the_short_wait(
        waits):
    failures = runner.Failures(7)
    said = [failures.failed(Status(400)) for _ in range(runner.reply_limit())]
    assert runner.reply_limit() == 3
    assert said == [True, True, False]
    failures.wait(1)
    assert waits == [(1, False)]
    # Refused to the end: its document is left unfinished.
    failures.given_up()
    assert runner.UNSERVED.of(7) == 1


def test_an_answer_after_a_refusal_leaves_nothing_unfinished(waits):
    failures = runner.Failures(7)
    assert failures.failed(Status(422)) is True
    failures.answered()
    failures.given_up()
    assert runner.UNSERVED.of(7) == 0


def test_a_refusal_is_known_by_the_status_of_its_response_too():
    request = httpx.Request("POST", "http://x/rerank")
    refusal = httpx.HTTPStatusError(
        "400", request=request,
        response=httpx.Response(400, request=request))
    assert runner.refused(refusal) and not runner.server_side(refusal)
    # the failure by construction: a rate limit, a server error and a
    # request that never arrived are no refusals
    assert not runner.refused(Status(429))
    assert not runner.refused(Status(503))
    assert not runner.refused(ConnectionError("refused"))


@pytest.mark.parametrize("failure", [Status(503), Status(429), slow()])
def test_a_request_given_up_unserved_leaves_its_document_unfinished(
        waits, failure):
    failures = runner.Failures(7)
    assert failures.failed(failure) is True
    failures.given_up()
    assert runner.UNSERVED.of(7) == 1


def test_an_answer_after_a_server_error_leaves_nothing_unfinished(waits):
    failures = runner.Failures(7)
    failures.failed(Status(503))
    failures.answered()
    failures.given_up()
    assert runner.UNSERVED.of(7) == 0


def test_a_request_whose_end_is_told_another_way_is_not_noted(waits):
    failures = runner.Failures(7, noted=False)
    assert failures.failed(Status(503)) is True
    failures.given_up()
    assert runner.UNSERVED.of(7) == 0


# -- requests that had no part of it -----------------------------------------

def flaky(first, reply):
    """A client that raises *first* at the first request of each conversation
    and answers *reply* after, and how often each conversation was asked."""
    lock, asked = threading.Lock(), {}

    def create(**request):
        text = request["messages"][-1]["content"]
        with lock:
            asked[text] = asked.get(text, 0) + 1
            first_time = asked[text] == 1
        if first_time:
            raise first
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=reply))])

    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), asked


PHRASE = Prompt("phrase", "x", {}, "", Path("phrase.md"))
SENTENCE = json.dumps({"phrase": "Ein Satz."})


def parameters(*uris):
    return SimpleNamespace(parameters=[
        SimpleNamespace(uri=uri, label=uri, description=f"Was {uri} ist",
                        vocabulary={})
        for uri in uris])


def refusing(failure):
    """A client that raises *failure* at every request, and its requests."""
    asked = []

    def create(**request):
        asked.append(request)
        raise failure

    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), asked


def test_a_refused_search_sentence_is_asked_again_after_the_short_wait(waits):
    client, asked = flaky(Status(400), SENTENCE)
    out = runner.document_anchor(parameters("a", "b"), client=client,
                                 prompt=PHRASE, document_id=7)
    assert sorted(asked.values()) == [2, 2]
    assert out == {"a": ["Ein Satz."], "b": ["Ein Satz."]}
    assert waits == [(1, False), (1, False)]
    assert runner.UNSERVED.of(7) == 0


def test_a_search_sentence_refused_to_the_end_leaves_its_document_unfinished(
        waits):
    client, asked = refusing(Status(400))
    out = runner.document_anchor(parameters("a"), client=client,
                                 prompt=PHRASE, document_id=7)
    assert len(asked) == runner.reply_limit()
    assert out == {}
    assert runner.UNSERVED.of(7) == 1


def test_a_search_sentence_the_server_failed_is_asked_again(waits):
    client, asked = flaky(Status(503), SENTENCE)
    out = runner.document_anchor(parameters("a", "b"), client=client,
                                 prompt=PHRASE, document_id=7)
    assert sorted(asked.values()) == [2, 2]
    assert out == {"a": ["Ein Satz."], "b": ["Ein Satz."]}
    assert waits == [(1, True), (1, True)]


def test_a_request_of_the_harvest_refused_to_the_end_leaves_its_document_unfinished(
        waits):
    # Every request of the harvest goes out here (a find, a coordinate, a
    # list entry): refused each time, it is given up as the rule says.
    client, asked = refusing(Status(400))
    prompt = Prompt("extraction/find", "Find.", {"max_tokens": 2048}, "",
                    Path("find.md"))
    out = runner.ask_in_grammar(client, prompt,
                                [{"role": "user", "content": "{}"}],
                                {"type": "object"}, 7, "find", "found")
    assert out is None
    assert len(asked) == runner.reply_limit()
    assert runner.UNSERVED.of(7) == 1


# -- a search, an embedding, a reranker (`runner.persistently`) --------------

def calling(*said):
    """A call that answers or raises *said* in turn, and its calls."""
    told, calls = in_turn(said, "the call"), []

    def call(*args):
        calls.append(args)
        out = told()
        if isinstance(out, Exception):
            raise out
        return out

    return call, calls


def test_a_search_the_server_failed_is_asked_again_until_it_answers(waits):
    call, calls = calling(Status(503), ConnectionError("gone"), ["p1"])
    assert runner.persistently("search", call)(7) == ["p1"]
    assert len(calls) == 3
    assert waits == [(1, True), (2, True)]


def test_a_search_refused_to_the_end_fails_its_document(waits):
    call, calls = calling(*[Status(400)] * runner.reply_limit(), ["p1"])
    with pytest.raises(Status):
        runner.persistently("search", call)(7)
    assert len(calls) == runner.reply_limit()
    assert waits == [(1, False), (2, False)]
    # the failure by construction: a refusal fewer than three times is
    # asked again and answered
    call, calls = calling(Status(400), ["p1"])
    assert runner.persistently("search", call)(7) == ["p1"]


# -- every request of the stage ----------------------------------------------

RULE = {"failed", "answered", "wait", "given_up"}


def _request(call: ast.Call) -> bool:
    """Whether *call* sends a request: `<client>.chat.completions.create(...)`
    or `send_request(...)`, the one function of the harvest that makes the
    first (`runner.send_request`)."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "send_request":
        return True
    return (isinstance(func, ast.Attribute) and func.attr == "create"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "completions"
            and isinstance(func.value.value, ast.Attribute)
            and func.value.value.attr == "chat")


def _lacking(top: ast.AST) -> set:
    """What of the rule *top* does not follow: no `Failures` made, or the
    parts of it it never calls; its attempts (`Failures.attempts`) wait as
    the rule says."""
    names = {target.id for node in ast.walk(top)
             if isinstance(node, ast.Assign)
             and isinstance(node.value, ast.Call)
             and isinstance(node.value.func, ast.Name)
             and node.value.func.id == "Failures"
             for target in node.targets if isinstance(target, ast.Name)}
    if not names:
        return {"Failures"}
    called = {node.func.attr for node in ast.walk(top)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name)
              and node.func.value.id in names}
    if "attempts" in called:
        called.add("wait")
    return RULE - called


def requests_without_the_rule(root: Path = STAGE) -> list:
    """Every function of the stage that sends a request and does not follow
    the rule, as "file:function:what it lacks"."""
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.name in WRAPPERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for top in tree.body:
            if getattr(top, "name", "") == "send_request":
                continue            # the callers follow the rule, not it
            if not any(isinstance(node, ast.Call) and _request(node)
                       for node in ast.walk(top)):
                continue
            lacking = _lacking(top)
            if lacking:
                found.append(f"{path.name}:{getattr(top, 'name', '?')}:"
                             f"{','.join(sorted(lacking))}")
    return found


def test_every_request_of_the_stage_follows_the_rule():
    assert requests_without_the_rule() == []


def test_a_request_without_the_rule_or_part_of_it_is_found(tmp_path):
    (tmp_path / "made.py").write_text(
        "def ask():\n"
        "    client = _client()\n"
        "    try:\n"
        "        return client.chat.completions.create(model='m')\n"
        "    except Exception:\n"
        "        return None\n"
        "def unwaited():\n"
        "    failures = Failures(1)\n"
        "    client = _client()\n"
        "    try:\n"
        "        client.chat.completions.create(model='m')\n"
        "        failures.answered()\n"
        "    except Exception as exc:\n"
        "        failures.failed(exc)\n"
        "    failures.given_up()\n"
        "def kept():\n"
        "    failures = Failures(1)\n"
        "    client = _client()\n"
        "    try:\n"
        "        client.chat.completions.create(model='m')\n"
        "        failures.answered()\n"
        "    except Exception as exc:\n"
        "        if failures.failed(exc):\n"
        "            failures.wait(1)\n"
        "    failures.given_up()\n"
        "def attempted():\n"
        "    failures = Failures(1)\n"
        "    client = _client()\n"
        "    for attempt in failures.attempts():\n"
        "        try:\n"
        "            return client.chat.completions.create(model='m')\n"
        "        except Exception as exc:\n"
        "            failures.answered()\n"
        "            if not failures.failed(exc):\n"
        "                break\n"
        "    failures.given_up()\n",
        encoding="utf-8")
    assert requests_without_the_rule(tmp_path) == ["made.py:ask:Failures",
                                                    "made.py:unwaited:wait"]
