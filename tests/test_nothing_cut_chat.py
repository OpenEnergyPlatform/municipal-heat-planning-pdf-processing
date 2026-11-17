"""
The chat and the example proposals cut nothing (owner decision 2026-11-17:
"Nichts kürzen, einfach ggf. clever aufteilen und darauf achten, dass die
Zuordnung zu Sektion und Seite etc. nicht verlieren gehen").

The promises, each with a case that breaks it by construction:

1. The follow-up context holds every turn of the conversation, AND every
   answer whole, however many turns and however long.
2. The error text of a failed sandbox run goes back to the model whole.
3. The app keeps every turn of a conversation as follow-up context.
4. A question is searched by every distinct word it has, in order.
5. A conversation that no longer fits the model's window makes the turn
   say so (a fault of its own, no request sent, nothing dropped), AND a
   conversation that fits is asked, AND a request that does not fit without
   the conversation is not blamed on it.
6. A proposed example shows the whole piece of the harvest that holds its
   quote, longer than the old 1800 characters where the piece is, AND with
   the lines the piece carries (a table's title and head), AND each of its
   sentences, AND a quote no one piece holds shows the whole passage.
"""
import sys
from unittest.mock import MagicMock

import pytest

from docpipe import window as windows
from docpipe.compile import examples
from docpipe.extraction.pipeline import Source
from docpipe.inference import lexical, llm_client


@pytest.fixture(autouse=True)
def no_server(monkeypatch):
    """No window is asked of a server unless a test sets one."""
    monkeypatch.setattr(llm_client, "_chat_window", lambda: None)


def turns(n: int, answer: str = "answer") -> list:
    return [{"task": f"question {i}", "phrase": f"anchor {i}",
             "answer": f"{answer} {i}"} for i in range(n)]


# -- 1 ------------------------------------------------------------------------

def test_every_turn_stays_in_the_follow_up_context():
    text = llm_client._history_context(turns(12))
    for i in range(12):
        assert f"question {i}" in text            # the oldest included


def test_an_answer_stays_whole_however_long():
    long = " ".join(f"word{i}" for i in range(3000))
    text = llm_client._history_context(
        [{"task": "q", "phrase": "", "answer": long}])
    assert long in text and len(long) > 800


# -- 2 ------------------------------------------------------------------------

def test_a_sandbox_error_goes_back_whole():
    error = "Traceback\n" + "\n".join(f"line {i} of the trace"
                                      for i in range(600))
    assert len(error) > 1500
    text = llm_client._format_exec_result({"ok": False, "error": error})
    assert error in text and "line 599 of the trace" in text


# -- 3 ------------------------------------------------------------------------

def test_the_app_keeps_every_turn():
    names = ("streamlit", "streamlit.runtime", "streamlit.runtime.scriptrunner")
    saved = {name: sys.modules.get(name) for name in names}
    sys.modules.update({name: MagicMock() for name in names})
    try:
        from docpipe.app import app
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    app.T["no_answer_context"] = "-"
    by_doc: dict = {}
    for i in range(12):
        app._remember(by_doc, 7, f"question {i}", {"answer": f"a{i}"})
    assert [t["task"] for t in by_doc[7]] == [f"question {i}"
                                              for i in range(12)]


# -- 4 ------------------------------------------------------------------------

def test_every_distinct_word_of_a_question_is_searched():
    names = [f"term{i}" for i in range(80)]
    asked = " ".join(names + names[:10])           # the first ten twice
    assert lexical.words(asked) == names


# -- 5 ------------------------------------------------------------------------

class Counted:
    """A `_chat_json` that records what it was asked."""
    def __init__(self):
        self.messages = []

    def __call__(self, messages, temperature):
        self.messages.append(messages)
        return {"statements": [], "complete": True}


def asked_with(monkeypatch, limit: int, history: list, items: list) -> tuple:
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(limit))
    sent = Counted()
    monkeypatch.setattr(llm_client, "_chat_json", sent)
    with llm_client.collecting() as faults:
        out = llm_client.answer_from_sources("q", items, history=history)
    return out, faults, sent


def test_a_conversation_too_long_for_the_window_says_so(monkeypatch):
    items = [{"index": 0, "text": "short excerpt"}]
    long = turns(40, "x" * 400)                    # about 16,000 bytes
    out, faults, sent = asked_with(monkeypatch, 12000, long, items)
    assert out["fault"] == llm_client.CONVERSATION_TOO_LONG
    assert [f["cause"] for f in faults] == [llm_client.CONVERSATION_TOO_LONG]
    assert sent.messages == []                     # nothing was sent
    # and no turn was dropped to make it fit
    assert "question 0" in llm_client._history_context(long)


def test_a_conversation_that_fits_is_asked(monkeypatch):
    items = [{"index": 0, "text": "short excerpt"}]
    out, faults, sent = asked_with(monkeypatch, 12000, turns(2), items)
    assert out["fault"] is None and faults == []
    assert len(sent.messages) == 1
    assert "question 0" in str(sent.messages[0])


def test_a_request_too_long_without_the_conversation_is_not_its_fault(
        monkeypatch):
    items = [{"index": 0, "text": "e" * 30000}]
    out, faults, sent = asked_with(monkeypatch, 12000, turns(2), items)
    assert llm_client.CONVERSATION_TOO_LONG not in [
        f["cause"] for f in faults]
    assert len(sent.messages) == 1                 # asked as it was


def test_the_pick_and_the_phrase_do_not_ask_a_conversation_too_long(
        monkeypatch):
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(12000))
    sent = Counted()
    monkeypatch.setattr(llm_client, "_chat_json", sent)
    long = turns(40, "x" * 400)
    with llm_client.collecting() as faults:
        assert llm_client.pick_values("q", [{"id": "a"}], history=long) == []
        phrase, again = llm_client.make_search_phrase("the task",
                                                      history=long)
    assert (phrase, again) == ("the task", False)
    assert sent.messages == []
    assert len(faults) == 2


# -- 6 ------------------------------------------------------------------------

def sentences(n: int, width: int = 12) -> str:
    return " ".join(f"Sentence number {i} " + "stuff " * width + "ends."
                    for i in range(n))


def test_an_example_shows_the_whole_piece_of_its_quote():
    text = sentences(40, width=40)                 # far over 1800 characters
    quote = "Sentence number 20 "
    shown = examples.snippet(text, [quote], piece_lines=8)
    # the piece of the quote: sentences 16 to 23, each whole
    assert all(f"Sentence number {i} " in shown for i in range(16, 24))
    assert "Sentence number 15 " not in shown
    assert "Sentence number 24 " not in shown
    assert len(shown) > 1800                       # the old cap
    assert shown.count("ends.") == 8               # every sentence ends whole


def test_a_table_piece_carries_its_title_and_head():
    rows = "\n".join(f"| Row{i} | {i * 10} |" for i in range(30))
    text = ("Table 4: Demand by sector\n| Sector | GWh |\n| --- | --- |\n"
            + rows)
    item = Source("table", 1, text)
    shown = examples.snippet(text, ["| Row20 | 200 |"], piece_lines=8,
                             item=item)
    assert "Table 4: Demand by sector" in shown and "| Sector | GWh |" in shown
    assert "| Row20 | 200 |" in shown
    assert "| Row0 | 0 |" not in shown               # another piece


def test_a_quote_no_piece_holds_shows_the_whole_passage():
    text = sentences(30)
    # a real substring of the passage that crosses from the end of the first
    # piece (sentences 0-7) into the second (8-15): no one piece holds it
    quote = ("Sentence number 7 " + "stuff " * 12 + "ends. "
             "Sentence number 8 ")
    assert quote in text
    shown = examples.snippet(text, [quote], piece_lines=8)
    assert shown == text                           # not the first piece only
    assert quote in shown and "Sentence number 29 " in shown
    # and a quote that is not in the passage at all is no piece's either
    assert examples.snippet(text, ["not in it at all"], piece_lines=8) == text


def test_quotes_in_two_pieces_show_both_in_order():
    text = sentences(30)
    shown = examples.snippet(
        text, ["Sentence number 2 ", "Sentence number 26 "], piece_lines=8)
    assert shown.index("Sentence number 2 ") < shown.index(
        "Sentence number 26 ")
    assert "Sentence number 12 " not in shown      # the pieces between


def test_a_proposal_keeps_the_tuple_whose_quote_stands_in_a_long_piece():
    text = sentences(30, width=60)
    quote = "Sentence number 20 " + "stuff " * 60 + "ends."
    spec = {"parameters": [{"uri": "p", "label": "L", "value_type": "string"}]}

    def find(_parameter):
        return [{"document": "d", "text": text, "where": ["section", 1]}]

    def ask(_parameter, _passage):
        return {"tuples": [{"value": "20", "value_raw": "20",
                            "quote": quote}]}
    review = examples.propose(spec, find, ask, piece_lines=8)
    proposals = review["parameters"]["p"]["proposals"]
    assert len(proposals) == 1 and quote in proposals[0]["source"]
    assert review["parameters"]["p"]["dropped"] == {}


# -- 7 ------------------------------------------------------------------------

class Reply:
    """A response with one choice."""
    def __init__(self, content: str, finish: str = "stop"):
        message = MagicMock()
        message.content, message.reasoning_content = content, None
        choice = MagicMock()
        choice.message, choice.finish_reason = message, finish
        self.choices = [choice]


class Server:
    """A client whose chat completions answer from a list, and record the
    messages they were asked."""
    def __init__(self, *contents):
        self.contents = list(contents)
        self.asked = []
        self.chat = MagicMock()
        self.chat.completions.create = self.create

    def create(self, **kw):
        self.asked.append(kw["messages"])
        return Reply(self.contents.pop(0))


def test_a_reply_that_does_not_fit_is_not_shown_and_asked_anew(monkeypatch):
    """The re-ask of a broken reply that cannot be shown whole starts the
    request anew with the cause named; the reply is in no message."""
    broken = '{"a": "' + "x" * 1800 + '" "b"}'      # breaks after the string
    server = Server(broken, '{"ok": 1}')
    monkeypatch.setattr(llm_client, "get_client", lambda: server)
    monkeypatch.setattr(llm_client, "request_extras", lambda: {})
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(2000))
    base = [{"role": "user", "content": "the request"}]
    assert llm_client._chat_json(base, temperature=0) == {"ok": 1}
    second = server.asked[1]
    assert not any("x" * 100 in str(m.get("content")) for m in second)
    assert [m["role"] for m in second] == ["user"]
    assert "could not be read (syntax)" in second[-1]["content"]
    assert second[-1]["content"].startswith("the request")
