"""
Requests of a kind share their beginning (owner decision 2026-11-17, from
the literature on requests that share their beginning: BatchLLM, SGLang):
the example reply carries the request's own address, so with it in the
system prompt two requests differ early and the server's prefix cache serves
little. The rule `example_place` puts it in the message instead.

The promises, each with a case that breaks it by construction:

1. With "message" two requests of one kind with different examples send the
   SAME system prompt, AND each example stands in the payload of its
   message, as its last keys.
2. With "prompt" (the standard) the example stands in the system prompt as
   before AND the message carries no example key.
3. The example in the message follows `reply_order`, AND a request asked
   again (its message with words after the payload) keeps the keys.
4. A prompt without a place for an example gets no key.
5. scripts/prefix_share.py reports per kind the cached tokens of a trace,
   says so for a trace without them, and counts a request answered again
   as no request.
"""
import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import runner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import prefix_share  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


class Prompt:
    id = "extraction/x"
    text = "Reply in this form: {{example}}"
    placeholders = ("example",)

    @staticmethod
    def render(example):
        return f"Reply in this form: {example}"


class Bare:
    id, text, placeholders = "extraction/y", "No example.", ()

    @staticmethod
    def render():
        return "No example."


def sent(prompt, example, content=None):
    """(system text, last message) of a request as it goes out."""
    out = {}

    def create(**kwargs):
        out.update(kwargs)
        reply = SimpleNamespace(
            message=SimpleNamespace(content='{"a": 1}'),
            finish_reason="stop")
        return SimpleNamespace(choices=[reply], usage=None)
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    content = content or json.dumps({"field": "f"}, indent=1)
    runner._ask_in_grammar(client, prompt,
                           [{"role": "user", "content": content}],
                           None, 1, "coord", "a", example)
    system, *_, last = out["messages"]
    return system["content"], last["content"]


def test_message_keeps_the_system_prompt_the_same():
    with rules.overlaid(example_place="message"):
        one = sent(Prompt, {"at": "3.1", "words": "10"})
        two = sent(Prompt, {"at": "7.4", "words": "99"})
    assert one[0] == two[0]
    assert one[0] == 'Reply in this form: "example"'
    payload = json.loads(one[1])
    assert list(payload) == ["field", "example"]
    assert payload["example"] == {"at": "3.1", "words": "10"}
    assert json.loads(two[1])["example"] == {"at": "7.4", "words": "99"}


def test_prompt_keeps_the_example_in_the_system_prompt():
    one = sent(Prompt, {"at": "3.1", "words": "10"})
    two = sent(Prompt, {"at": "7.4", "words": "99"})
    assert one[0] != two[0]
    assert '{"at":"3.1","words":"10"}' in one[0]
    assert list(json.loads(one[1])) == ["field"]


def test_a_pair_goes_to_example_and_nothing_in_the_order_of_the_form():
    class Pair(Prompt):
        text = "{{example}} or {{nothing}}"
        placeholders = ("example", "nothing")

        @staticmethod
        def render(example, nothing):
            return f"{example} or {nothing}"
    pair = ({"at": "1", "words": "a"}, {"found": []})
    with rules.overlaid(example_place="message", reply_order="words_first"):
        system, content = sent(Pair, pair)
    assert system == '"example" or "nothing"'
    payload = json.loads(content)
    assert list(payload) == ["field", "example", "nothing"]
    assert list(payload["example"]) == ["words", "at"]


def test_the_words_after_the_payload_stay_after_it():
    content = json.dumps({"field": "f"}, indent=1) + "\n\nFollow up words."
    with rules.overlaid(example_place="message"):
        _system, last = sent(Prompt, {"at": "1", "words": "a"}, content)
    assert last.endswith("\n\nFollow up words.")
    assert list(json.loads(last[:last.index("\n\nFollow")])) == [
        "field", "example"]


def test_a_prompt_without_a_place_gets_no_key():
    with rules.overlaid(example_place="message"):
        system, content = sent(Bare, {"at": "1", "words": "a"})
    assert system == "No example."
    assert list(json.loads(content)) == ["field"]


def event(kind, **more):
    return json.dumps({"t": kind, "doc": 1, **more})


def test_prefix_share_reports_per_kind(tmp_path):
    lines = [event("coord_ask", prompt_tokens=1000, cached_tokens=900),
             event("coord_ask", prompt_tokens=1000, cached_tokens=100),
             event("coord_ask", prompt_tokens=5000, cached_tokens=0,
                   once=True),
             event("find_ask", prompt_tokens=400, cached_tokens=0)]
    with gzip.open(tmp_path / "d1.trace.jsonl.gz", "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    rows, unreported = prefix_share.shares([tmp_path])
    assert rows[("coord", "")] == [2, 2000, 1000]
    assert rows[("find", "")] == [1, 400, 0]
    assert unreported == 0
    assert "50.0%" in prefix_share.report(rows, unreported)


def test_prefix_share_says_where_a_trace_has_no_cached_tokens(tmp_path):
    (tmp_path / "d1.trace.jsonl").write_text(
        event("coord_ask", prompt_tokens=1000) + "\n", encoding="utf-8")
    rows, unreported = prefix_share.shares([tmp_path])
    assert unreported == 1
    assert "no cached_tokens" in prefix_share.report(rows, unreported)
