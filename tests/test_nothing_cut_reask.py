"""
What a re-ask and a round of the answer loop send is judged as it is sent,
and nothing of it is cut (owner decision 2026-11-17: "Nichts kürzen, einfach
ggf. clever aufteilen und darauf achten, dass die Zuordnung ... nicht
verlieren gehen").

The promises, each with a case that breaks it by construction:

1. A reply that is shown whole as the model's turn is in the request once:
   the correction names the place and the message and does not quote it
   again; where the reply is not shown as a turn, the correction quotes it.
2. A request is judged with the reply room it is sent with: after a cut-off
   the room is doubled, and a request that fits the first room and not the
   doubled one does not fit.
3. The output of a code run is shown whole where the round fits the window;
   where it does not, none of it is in the request and the model is told in
   one sentence its size and to print less; where even that leaves the
   round too long, the turn says the conversation is full.
"""
from unittest.mock import MagicMock

from docpipe import reading, window as windows
from docpipe.inference import llm_client, wording


def choice_of(content: str):
    message = MagicMock()
    message.content, message.reasoning_content = content, None
    made = MagicMock()
    made.message, made.finish_reason = message, "stop"
    return made


def texts(messages: list) -> list:
    return [str(m["content"]) for m in messages]


# -- 1 ------------------------------------------------------------------------

def test_a_reply_shown_as_a_turn_is_not_quoted_in_the_correction():
    reply = '{"a": "' + "x" * 60 + '" "b"}'
    with reading.speaking(wording.chat_profile()):
        _, cause, said = reading.read(choice_of(reply))
        assert cause == "syntax"
        shown = reading.again([{"role": "user", "content": "ask"}], reply,
                              said, cause, echo=True)
    assert sum(t.count("x" * 50) for t in texts(shown)) == 1
    assert [m["role"] for m in shown] == ["user", "assistant", "user"]
    assert "breaks at character" in shown[-1]["content"]   # place and message


def test_text_beside_the_object_is_not_quoted_where_the_reply_is_shown():
    reply = '{"a": 1} ' + "trailing " * 8
    with reading.speaking(wording.chat_profile()):
        _, cause, said = reading.read(choice_of(reply))
        assert cause == "outside_text"
        shown = reading.again([{"role": "user", "content": "ask"}], reply,
                              said, cause, echo=True)
    assert sum(t.count("trailing") for t in texts(shown)) == 8   # once


def test_a_reply_not_shown_as_a_turn_is_quoted_in_the_correction():
    reply = '{"a": "' + "x" * 60 + '" "b"}'
    with reading.speaking(wording.chat_profile()):
        _, cause, said = reading.read(choice_of(reply))
        quoted = reading.again([{"role": "user", "content": "ask"}], None,
                               said, cause, echo=False)
    assert [m["role"] for m in quoted] == ["user"]
    assert sum(t.count("x" * 50) for t in texts(quoted)) == 1


# -- 2 ------------------------------------------------------------------------

def test_a_request_is_judged_with_the_doubled_room(monkeypatch):
    # 6,000 tokens, 2,048 reserved: 3,952 left; 4,096 reserved: 1,904 left
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(6000, frame=2048))
    request = [{"role": "user", "content": "r" * 3000}]
    assert llm_client._fits_chat(request)
    token = llm_client._ROOM.set(4096)
    try:
        assert not llm_client._fits_chat(request)
    finally:
        llm_client._ROOM.reset(token)
    assert llm_client._fits_chat(request)


def test_a_conversation_is_judged_with_the_doubled_room(monkeypatch):
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(6000, frame=2048))
    assert not llm_client._too_long("q", "r" * 100, "h" * 3000)
    token = llm_client._ROOM.set(4096)
    try:
        assert llm_client._too_long("q", "r" * 100, "h" * 3000)
    finally:
        llm_client._ROOM.reset(token)


# -- 3 ------------------------------------------------------------------------

class Script:
    """A `_chat_json` that answers from a list and records its messages."""
    def __init__(self, *replies):
        self.replies = list(replies)
        self.messages = []

    def __call__(self, messages, temperature):
        self.messages.append(messages)
        return self.replies.pop(0)


def run(monkeypatch, limit: int, code: str, output: str):
    monkeypatch.setattr(llm_client, "_chat_window",
                        lambda: windows.Window(limit))
    sent = Script({"action": "python", "code": code},
                  {"statements": [], "complete": True})
    monkeypatch.setattr(llm_client, "_chat_json", sent)
    runner = lambda code, context: {"ok": True, "stdout": output}
    with llm_client.collecting() as faults:
        out = llm_client.answer_from_sources(
            "q", [{"index": 0, "text": "excerpt"}], code_runner=runner,
            max_compute=1)
    return out, faults, sent


def test_an_output_that_fits_goes_back_whole(monkeypatch):
    output = "y" * 5000
    out, faults, sent = run(monkeypatch, 40000, "print(1)", output)
    assert out["fault"] is None and len(sent.messages) == 2
    assert output in sent.messages[1][0]["content"]


def test_an_output_that_does_not_fit_is_not_cut_into_the_request(
        monkeypatch):
    output = "y" * 30000 + "\nlast line"
    out, faults, sent = run(monkeypatch, 20000, "print(1)", output)
    body = sent.messages[1][0]["content"]
    assert "yyyyyyyyyy" not in body                # nothing of it, not cut
    assert "print(1)" in body                      # the round itself stays
    # the one sentence of the profile with the output's size in its place
    assert llm_client._w()["exec_too_long"].format(
        characters=30010, lines=2) in body
    assert out["fault"] is None and faults == []


def test_rounds_too_long_even_without_the_output_say_the_conversation_is_full(
        monkeypatch):
    out, faults, sent = run(monkeypatch, 20000, "c" * 30000, "short")
    assert out["fault"] == llm_client.CONVERSATION_TOO_LONG
    assert [f["cause"] for f in faults] == [llm_client.CONVERSATION_TOO_LONG]
    assert len(sent.messages) == 1                 # the second was not sent
