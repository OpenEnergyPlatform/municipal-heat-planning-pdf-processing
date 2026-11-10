"""A request that timed out is repeated with the time of a repeat, and every
request of the extraction stage is: the rule stands once, in the client each
request goes out on (`runner._client`, `scheduler.Repeats`). Each promise has
a case that breaks it beside the one that keeps it."""
import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from docpipe import providers
from docpipe.extraction import runner, scheduler
from docpipe.inference import pool
from docpipe.prompts import Prompt

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "docpipe" / "extraction"
# The clients every other client of the stage is made of: they pass a request
# on and send none of their own.
WRAPPERS = {"scheduler.py", "throttle.py"}


def answered(content="{}"):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=content))])


def slow():
    return openai.APITimeoutError(request=httpx.Request("POST", "http://x"))


class Failed(Exception):
    status_code = 500


def transport(*outcomes):
    """A client answering *outcomes* in turn, raising the exceptions among
    them, and the time each request was given."""
    left, times = list(outcomes), []

    def create(**request):
        times.append(request.get("timeout"))
        outcome = left.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), times


def stage_client(monkeypatch, *outcomes):
    """The stage's own client (`runner._client`) over *outcomes*."""
    client, times = transport(*outcomes)
    monkeypatch.setattr(providers, "client", lambda *a, **k: client)
    monkeypatch.setattr(runner, "SCHEDULER", None)
    monkeypatch.setattr(pool, "wide", lambda: False)
    return runner._client(), times


def ask(client, text="x", **request):
    try:
        return client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": text}],
            **request)
    except Exception:
        return None


# -- the rule ----------------------------------------------------------------

def test_a_request_that_timed_out_is_repeated_with_the_time_of_a_repeat(
        monkeypatch):
    client, times = stage_client(monkeypatch, slow(), answered())
    ask(client)
    assert ask(client) is not None
    assert times == [None, runner.retry_timeout()]


def test_a_server_error_is_repeated_with_the_time_it_had(monkeypatch):
    client, times = stage_client(monkeypatch, Failed(), answered())
    ask(client)
    ask(client)
    assert times == [None, None]


def test_another_request_after_a_timeout_keeps_its_time(monkeypatch):
    # After a reply, a retry loop asks with one more message: what was wrong.
    client, times = stage_client(monkeypatch, slow(), answered())
    ask(client, "x")
    ask(client, "x, und was daran falsch war")
    assert times == [None, None]


def test_the_time_of_a_repeat_holds_until_the_request_is_answered(
        monkeypatch):
    client, times = stage_client(monkeypatch, slow(), slow(), answered(),
                                 answered())
    for _ in range(4):
        ask(client)
    assert times == [None, runner.retry_timeout(), runner.retry_timeout(), None]


def test_a_longer_time_of_its_own_stays_on_a_repeat(monkeypatch):
    longer = runner.retry_timeout() * 3
    client, times = stage_client(monkeypatch, slow(), answered(), slow(),
                                 answered())
    ask(client, "a", timeout=longer)
    ask(client, "a", timeout=longer)
    ask(client, "b", timeout=1)
    ask(client, "b", timeout=1)
    assert times == [longer, longer, 1, runner.retry_timeout()]


def test_a_repeat_is_the_next_request_of_the_same_thread(monkeypatch):
    client, times = stage_client(monkeypatch, slow(), answered(), answered())
    ask(client)
    other = threading.Thread(target=ask, args=(client,))
    other.start()
    other.join()
    ask(client)
    # The other thread asked the same and was no repeat; this thread's repeat
    # still is one, whatever the other thread asked in between.
    assert times == [None, None, runner.retry_timeout()]


def test_a_client_is_made_repeating_once():
    client, _times = transport()
    once = runner._repeating(client)
    assert runner._repeating(once) is once
    assert isinstance(once, scheduler.Repeats)


# -- every request of the stage ----------------------------------------------

def test_a_request_handed_a_client_repeats_by_the_rule_in_every_thread():
    # The search sentence of a document: one request per parameter, all at
    # once, with a plain client handed in. Each one's first try times out.
    lock, seen, times = threading.Lock(), set(), {}

    def create(**request):
        text = request["messages"][-1]["content"]
        with lock:
            times.setdefault(text, []).append(request.get("timeout"))
            first = text not in seen
            seen.add(text)
        if first:
            raise slow()
        return answered(json.dumps({"phrase": "Ein Satz."}))

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    spec = SimpleNamespace(parameters=[
        SimpleNamespace(uri=uri, label=uri, description=f"Was {uri} ist",
                        vocabulary={})
        for uri in ("a", "b", "c")])
    out = runner.document_anchor(spec, client=client,
                                 prompt=Prompt("phrase", "x", {}, "",
                                               Path("phrase.md")))
    assert set(out) == {"a", "b", "c"}
    assert list(times.values()) == [[None, runner.retry_timeout()]] * 3


def _receiver(call: ast.Call):
    """The client a `<client>.chat.completions.create(...)` goes out on, or
    None for any other call."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "create"):
        return None
    completions = func.value
    if not (isinstance(completions, ast.Attribute)
            and completions.attr == "completions"
            and isinstance(completions.value, ast.Attribute)
            and completions.value.attr == "chat"):
        return None
    return completions.value.value


def _made_repeating(top: ast.AST, name: str) -> bool:
    """Whether *top* binds *name* to `_client()` or `_repeating(...)`."""
    for node in ast.walk(top):
        if not (isinstance(node, ast.Assign) and isinstance(node.value,
                                                            ast.Call)):
            continue
        made = node.value.func
        if (isinstance(made, ast.Name)
                and made.id in ("_client", "_repeating")
                and any(isinstance(t, ast.Name) and t.id == name
                        for t in node.targets)):
            return True
    return False


def requests_without_the_rule(root: Path = STAGE) -> list:
    """Every request of the stage whose client was not made repeating, as
    "file:function:line"."""
    missing = []
    for path in sorted(root.rglob("*.py")):
        if path.name in WRAPPERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for top in tree.body:
            for node in ast.walk(top):
                if not isinstance(node, ast.Call):
                    continue
                client = _receiver(node)
                if client is None:
                    continue
                if not (isinstance(client, ast.Name)
                        and _made_repeating(top, client.id)):
                    missing.append(f"{path.name}:{getattr(top, 'name', '?')}"
                                   f":{node.lineno}")
    return missing


def test_every_request_of_the_stage_goes_out_on_a_repeating_client():
    found = requests_without_the_rule()
    assert found == []


def test_a_request_on_a_client_made_otherwise_is_found(tmp_path):
    (tmp_path / "made.py").write_text(
        "def ask():\n"
        "    client = providers.client('llm')\n"
        "    return client.chat.completions.create(model='m')\n"
        "def kept():\n"
        "    client = _client()\n"
        "    return client.chat.completions.create(model='m')\n",
        encoding="utf-8")
    assert requests_without_the_rule(tmp_path) == ["made.py:ask:3"]
