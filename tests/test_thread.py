"""Each request is sent the words of its own task, and what asks again about
an answer goes after it in the same conversation (thread.py, owner decisions
2026-11-07).

Promise: the system prompt of a conversation is what every request of its
kind is told AND the part of each field its first message carries, never
the words of a follow-up; a follow-up carries the words of each of its
fields AND those fields as JSON AND the reply of its request where its words
show one; a field whose follow-ups have no words, or a part marked twice,
stops the run at its start, and an empty follow-up is an error; a request of
a conversation goes after the answer that stands AND under the system prompt
the conversation began with, AND the conversation keeps every message sent
with the answer that stands last.

Each promise has a case that breaks it by construction beside the one that
keeps it.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner, thread
from docpipe.prompts import Prompt

TEXT = """Gemeinsam.

<!-- with: table_before -->
Die Tabelle davor.

<!-- follow-up: corrections -->
Korrektur.

<!-- with: whole_table around -->
Ganze Tabelle.

<!-- follow-up: more hits -->
Mehr.

<!-- follow-up: next -->
Der nächste Wert, so: {{example}}
"""
FOLLOWS = ("corrections", "more", "hits", "next")


def prompt_of(text: str = TEXT) -> Prompt:
    return Prompt(id="extraction/read_values", text=text, meta={}, sha256="",
                  path=Path("read_values.md"))


PARTS = thread.cut(prompt_of(), follows=FOLLOWS)


def test_the_system_prompt_is_the_common_part_and_the_parts_it_carries():
    assert PARTS.system().text == "Gemeinsam.\n"
    assert PARTS.system({"table_before": "T"}).text \
        == "Gemeinsam.\n\nDie Tabelle davor.\n"
    # In the order of the file, a part once whichever of its fields come.
    assert PARTS.system({"around": 1, "whole_table": 1,
                         "table_before": 1}).text \
        == "Gemeinsam.\n\nDie Tabelle davor.\n\nGanze Tabelle.\n"
    # The words of a follow-up never, whatever the first message carries.
    assert PARTS.system({key: 1 for key in FOLLOWS}).text == "Gemeinsam.\n"


def test_a_follow_up_carries_the_words_of_its_fields_and_the_fields():
    said = PARTS.follow_up({"corrections": [{"what": "x"}]})
    words, data = said.split("\n\n", 1)
    assert words == "Korrektur."
    assert json.loads(data) == {"corrections": [{"what": "x"}]}
    # One part for two of its fields, once.
    both = PARTS.follow_up({"more": [1], "hits": [2]})
    assert both.count("Mehr.") == 1
    assert json.loads(both.split("\n\n", 1)[1]) == {"more": [1], "hits": [2]}
    # A field without a value is told by its words alone, with the reply of
    # the request where they show one, and only there.
    assert PARTS.follow_up({"next": None}, {"value": 1}) \
        == 'Der nächste Wert, so: {"value":1}'
    assert PARTS.follow_up({"corrections": ["x"]}, {"value": 1}) \
        == PARTS.follow_up({"corrections": ["x"]})
    # The failures by construction: nothing to carry, a field without
    # words, words that show a reply and none to show.
    with pytest.raises(ValueError):
        PARTS.follow_up({})
    with pytest.raises(LookupError, match="around"):
        PARTS.follow_up({"around": "x"})
    with pytest.raises(KeyError):
        PARTS.follow_up({"next": None})


def test_a_prompt_that_cannot_word_its_follow_ups_stops_at_the_start():
    thread.cut(prompt_of(), follows=FOLLOWS)
    # "next" only as a part of the system prompt: no words to follow with.
    with pytest.raises(LookupError, match="next"):
        thread.cut(prompt_of(TEXT.replace("<!-- follow-up: next -->",
                                          "<!-- with: next -->")),
                   follows=FOLLOWS)
    # A part marked twice is no prompt either.
    with pytest.raises(LookupError, match="corrections"):
        thread.cut(prompt_of(TEXT + "\n<!-- follow-up: corrections -->\n"
                                    "Noch einmal.\n"))


def test_a_follow_up_needs_an_answer_and_a_branch_leaves_its_thread():
    with pytest.raises(ValueError):
        thread.Thread().then("x")
    begun = thread.Thread("S", [{"role": "user", "content": "a"},
                                {"role": "assistant", "content": "b"}])
    branch = begun.branch()
    branch.messages = branch.then("c")
    assert len(begun.messages) == 2 and len(branch.messages) == 3
    assert branch.system == begun.system


def replying(*said):
    """A client answering *said* in turn; the messages of each request."""
    told = iter(said)
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=next(told)))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create))), sent


SHAPE = {"type": "json_schema", "json_schema": {
    "name": "reply", "schema": {"type": "object", "required": ["value"]}}}


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0)
    monkeypatch.setattr(runner, "answer_room", lambda *a, **k: 4096)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)


def ask(client, conversation, payload=None, follow=None):
    prompt, messages = runner.threaded(PARTS, conversation, payload, follow,
                                       example={"value": 0})
    return runner.ask_in_grammar(client, prompt, messages, SHAPE, 7,
                                 "read_values", "value", thread=conversation)


def test_a_follow_up_goes_after_the_answer_under_the_first_system_prompt(
        quiet):
    first, nxt = '{"value": 300}', '{"value": 27}'
    client, sent = replying(first, nxt)
    conversation = thread.Thread()
    assert ask(client, conversation,
               payload={"source": "S", "table_before": "T"}) == {"value": 300}
    assert ask(client, conversation, follow={"next": None}) == {"value": 27}
    opening, then = sent
    # The system prompt the conversation began with, the part of the field
    # its first message carried in it, the follow-up's words not.
    assert then[0] == opening[0]
    assert "Die Tabelle davor." in opening[0]["content"]
    assert "Der nächste Wert" not in opening[0]["content"]
    # After the answer it follows, which the model sees as it gave it.
    assert then[:len(opening)] == opening
    assert then[len(opening)] == {"role": "assistant", "content": first}
    assert then[-1]["content"] == 'Der nächste Wert, so: {"value":0}'
    assert conversation.messages[-1] == {"role": "assistant", "content": nxt}
    # The failure by construction: without the thread a request starts
    # anew, its system prompt without the part of a field it does not carry.
    client, sent = replying(first)
    prompt, messages = runner.threaded(PARTS, thread.Thread(), {"source": 1})
    runner.ask_in_grammar(client, prompt, messages, SHAPE, 7, "read_values",
                          "value")
    assert "Die Tabelle davor." not in sent[0][0]["content"]


def test_the_conversation_keeps_a_retry_with_the_answer_that_stood(quiet):
    lacking, kept = '{"quote": "x"}', '{"value": 27}'
    client, sent = replying('{"value": 300}', lacking, kept, '{"value": null}')
    conversation = thread.Thread()
    ask(client, conversation, payload={"source": "S"})
    assert ask(client, conversation, follow={"next": None}) == {"value": 27}
    # The unreadable reply and what it was told stay in the conversation,
    # the answer that stood last.
    assert [m["role"] for m in conversation.messages] == [
        "user", "assistant", "user", "assistant", "user", "assistant"]
    assert conversation.messages[3]["content"] == lacking
    assert conversation.messages[-1]["content"] == kept
    # The next request is all of it, then its own message.
    ask(client, conversation, follow={"next": None})
    assert sent[-1][1:] == conversation.messages[:-1]
    assert sent[-1][-2] == {"role": "assistant", "content": kept}
