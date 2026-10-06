"""How the chat reads a model's reply: one JSON object, nothing repaired.

What is promised, sentence by sentence:

  * a reply is read as exactly one JSON object, by the reader the other stages
    use (`docpipe.reading`): no fence, no think block, no text around the
    object is removed, no bracket is closed, nothing is carved out;
  * AND anything else is asked again, in the same single user turn with the
    cause named, and not after a pause;
  * AND the cause is the harvest's own (the two classifiers do not drift);
  * AND a request that stays unreadable ends with its cause, after the
    attempts the setting allows, and the turn's fault list has it once;
  * AND a reply cut off at its token limit is not asked again as it stands;
  * AND a request that stays unreadable is reported as unread and never as
    "nothing found in the sources", whether it is the answer or one of the
    small requests around it.

Every request goes out through the one client below, the real `_chat_json`
reading what it returns: nothing in this file stands in for the reader.
"""
import json
import types

import pytest

from docpipe import prompts, reading
from docpipe.extraction import runner
from docpipe.inference import (answer, config, llm_client, replies,
                               request_log)
from docpipe.llm_preflight import request_extras
from docpipe.profile import load_profile
from docpipe.providers import base

GOOD = json.dumps({"statements": [
    {"statement": "Der Bedarf war 100 GWh.", "basis": "text", "index": 0,
     "quote": "Der Wärmebedarf betrug 100 GWh."}], "complete": True})
ITEMS = [{"index": 0, "source": "s", "text": "Der Wärmebedarf betrug 100 GWh."}]


class Client:
    """What the chat talks to: it hands out the replies it was given, in
    order, and notes every request. An exception is raised, not returned."""

    def __init__(self, *replies_):
        self.queue = list(replies_)
        self.requests = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        got = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(got, BaseException):
            raise got
        if isinstance(got, str):
            return base.reply(got, "stop")
        return got


@pytest.fixture
def client(monkeypatch):
    def install(*replies_):
        made = Client(*replies_)
        monkeypatch.setattr(llm_client, "get_client", lambda: made)
        return made

    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    slept = []
    monkeypatch.setattr(llm_client.time, "sleep", slept.append)
    install.slept = slept
    return install


def ask(shape=None):
    """One request with the given shape, the way the chat makes it."""
    return llm_client._ask(shape or replies.answer(actions=False),
                           [{"role": "user", "content": "FRAGE"}],
                           temperature=0.1)


# What each cause looks like, and what the model is told. The reply that
# violates the promise is the one in the first column.
FAULTS = {
    "empty": ("", "was empty"),
    "reasoning_only": (base.reply("", "stop", reasoning="ich denke nach"),
                       "only thought"),
    "no_object": ("Das weiß ich nicht.", "no JSON object"),
    "syntax": ('{"statements": [1, 2,, 3]}', "breaks at character"),
    "outside_text": ('Hier: {"statements": [], "complete": false} fertig',
                     "text beside the JSON object"),
    "not_an_object": ("[1, 2]", "list structure"),
    # the task's own format spec won over the envelope
    "missing_key": ('{"Firmname": "X GmbH", "Postleitzahl": 32278}',
                    'lacked "statements"'),
    # the key is there and is not the list that was asked for
    "wrong_kind": ('{"statements": "Der Bedarf war 100 GWh."}',
                   '"statements" was not a list'),
}


@pytest.mark.parametrize("name", sorted(FAULTS))
def test_a_reply_that_is_not_the_object_is_asked_again_naming_the_cause(
        client, name):
    bad, said = FAULTS[name]
    made = client(bad, GOOD)
    got = ask()
    assert got["statements"][0]["index"] == 0           # the second reply
    assert len(made.requests) == 2
    first, second = (r["messages"] for r in made.requests)
    assert first == [{"role": "user", "content": "FRAGE"}]
    # the same single user turn, with what was wrong appended
    assert len(second) == 1 and second[0]["role"] == "user"
    assert second[0]["content"].startswith("FRAGE\n\n")
    assert said in second[0]["content"], second[0]["content"]
    assert "Output ONLY the JSON object" in second[0]["content"]
    # no assistant turn is echoed, in either request
    assert all(m["role"] != "assistant" for r in made.requests
               for m in r["messages"])
    assert client.slept == []              # a reply is asked again at once


def test_the_correction_names_what_broke_not_only_that_something_did(client):
    made = client('Hier: {"statements": []} und noch was', GOOD)
    ask()
    sent = made.requests[1]["messages"][0]["content"]
    assert "'Hier:  und noch was'" in sent          # the extra text itself
    made = client('{"statements": [1, 2,, 3]}', GOOD)
    ask()
    sent = made.requests[0]["messages"][0]["content"]
    assert sent == "FRAGE"
    sent = made.requests[1]["messages"][0]["content"]
    assert "breaks at character 21" in sent and ",, 3" in sent


def test_the_correction_rides_along_with_the_images_of_the_request(client):
    """A request with crops is a list of parts: the correction is one more
    text part, and the images stay."""
    made = client("keine Ahnung", GOOD)
    parts = [{"type": "text", "text": "FRAGE"},
             {"type": "image_url", "image_url": {"url": "data:x"}}]
    llm_client._ask(replies.answer(actions=False),
                    [{"role": "user", "content": parts}], temperature=0.1)
    second = made.requests[1]["messages"][0]["content"]
    assert second[:2] == parts and second[2]["type"] == "text"
    assert "no JSON object" in second[2]["text"]
    assert made.requests[0]["messages"][0]["content"] == parts   # untouched


def test_the_sentences_are_the_profiles_where_one_is_named_and_the_built_ins_where_not(
        client, monkeypatch):
    """The chat answers with no profile named, on the built-in one. The
    reader's words come from the same profile as the chat's prompts."""
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    monkeypatch.setattr(llm_client.wording, "_said_fallback", [])
    made = client("keine Ahnung", GOOD)
    ask()
    assert "no JSON object" in made.requests[1]["messages"][0]["content"]
    # outside the chat the reader still stops without a profile
    with pytest.raises(LookupError, match="needs a profile"):
        reading.read(types.SimpleNamespace(
            message=types.SimpleNamespace(content="x", reasoning_content=None),
            finish_reason="stop"))


# ---------------------------------------------------------------------------
# Nothing is repaired
# ---------------------------------------------------------------------------

STILL_JSON = {"statements": [], "complete": False}
WRAPPED = {
    "fenced": ("```json\n" + json.dumps(STILL_JSON) + "\n```", "outside_text"),
    "think": ("<think>Ich überlege.</think>" + json.dumps(STILL_JSON),
              "outside_text"),
    "prose first": ("Hier ist die Antwort: " + json.dumps(STILL_JSON),
                    "outside_text"),
    "prose after": (json.dumps(STILL_JSON) + " Das war es.", "outside_text"),
    "a bracket missing": ('{"statements": [{"statement": "x", "basis": '
                          '"text", "index": 0, "quote": "yyyyyyyyyyyyyy"}',
                          "syntax"),
    "two objects": (json.dumps(STILL_JSON) + json.dumps(STILL_JSON),
                    "outside_text"),
}


@pytest.mark.parametrize("name", sorted(WRAPPED))
def test_nothing_is_repaired(client, name):
    """Each of these was taken apart, closed or cut out of its surroundings by
    the code that was removed, and read as an answer. None is accepted now:
    asked again as often as the setting allows, then the request ends with
    the cause."""
    text, cause = WRAPPED[name]
    made = client(text)
    with pytest.raises(llm_client.ReplyError) as ended:
        ask()
    assert ended.value.cause == cause
    assert len(made.requests) == llm_client.LLM_MAX_RETRIES


def test_what_was_removed_is_gone():
    for name in ("_clean_raw", "_loads_json_object", "_is_off_envelope",
                 "revise_with_readings", "_ENVELOPE_CORRECTION",
                 "_READOFF_CORRECTION", "REVISE_PROMPT", "_ANSWER_SPEC_TEXT",
                 "_ANSWER_SPEC_JSON"):
        assert not hasattr(llm_client, name), name
    assert not hasattr(replies, "REVISE")
    for name in ("kwp", "scenarios", "default"):
        phrases = load_profile(name)._own("inference", "PHRASES")
        assert "empty_reply" not in phrases and "parse_error" not in phrases
    for gone in ("answer_spec_text", "answer_spec_json",
                 "envelope_correction", "readoff_correction", "revise"):
        for name in ("kwp", "scenarios", "default"):
            assert not prompts.path_for(f"inference/{gone}",
                                        load_profile(name)).is_file()


def test_an_action_stands_in_for_the_statements_only_where_one_may_come(
        client):
    action = '{"action": "python", "code": "print(1)"}'
    made = client(action)
    assert ask(replies.answer())["action"] == "python"      # offered
    assert len(made.requests) == 1
    made = client(action)
    with pytest.raises(llm_client.ReplyError) as ended:     # the last call
        ask(replies.answer(actions=False))
    assert ended.value.cause == "missing_key"
    assert 'lacked "statements"' in made.requests[1]["messages"][0]["content"]
    # an object with neither is no reply to a call that may ask for either
    made = client('{"complete": true}')
    with pytest.raises(llm_client.ReplyError) as ended:
        ask(replies.answer())
    assert ended.value.cause == "missing_key"


def test_a_closed_question_answered_with_no_answer_is_asked_again_not_read_as_none(
        client):
    """`choose` reads None as "no constraint": a reply that carries no
    "answer" key is a hole and not that None. The key of this request has no
    single kind (text or a number), which is where a missing key used to be
    taken for a value."""
    prompt = types.SimpleNamespace(text="Wähle.", meta={})
    made = client('{"Antwort": "x"}', '{"answer": "x"}')
    assert llm_client.choose(prompt, "Frage?", "Welche?", {"x": "X"}) == "x"
    assert len(made.requests) == 2
    assert 'lacked "answer"' in made.requests[1]["messages"][-1]["content"]
    # and a reply that never carries it ends with its cause
    made = client("{}")
    with pytest.raises(llm_client.ReplyError) as ended:
        llm_client.choose(prompt, "Frage?", "Welche?", {"x": "X"})
    assert ended.value.cause == "missing_key"
    assert len(made.requests) == llm_client.LLM_MAX_RETRIES


# ---------------------------------------------------------------------------
# The causes are the harvest's
# ---------------------------------------------------------------------------

def _choice(content, finish="stop", reasoning=None):
    return types.SimpleNamespace(finish_reason=finish, message=types.SimpleNamespace(
        content=content, reasoning_content=reasoning))


PARITY = {
    "cut_off": _choice('{"statements": [', "length"),
    "cut_off, no text": _choice("", "length"),
    "reasoning_only": _choice("", "stop", "ich denke"),
    "empty": _choice(""),
    "blank": _choice("  \n"),
    "no_object": _choice("keine Ahnung"),
    "syntax": _choice('{"statements": [1, 2,, 3]}'),
    "outside_text": _choice('Hier: {"statements": []} fertig'),
    "fenced": _choice('```json\n{"statements": []}\n```'),
    "two objects": _choice('{"statements": []}{"statements": []}'),
    "not_an_object": _choice("[1, 2]"),
    "missing_key": _choice('{"other": 1}'),
    "not a list": _choice('{"statements": 3}'),
    "a cut that parses keeps its shape fault": _choice('{"other": 1}',
                                                       "length"),
}


def test_the_chat_and_the_harvest_agree_on_the_cause():
    shape = replies.answer(actions=False)
    for name, given in PARITY.items():
        _got, cause, _said = llm_client._read(given, shape)
        harvest, _correction = runner._reply_fault(given, 512,
                                                   key="statements")
        assert cause == harvest, (name, cause, harvest)
    assert {llm_client._read(given, shape)[1] for given in PARITY.values()} \
        == set(reading.CAUSES) - {"wrong_shape"}


def test_the_guard_sees_a_cause_that_changed(monkeypatch):
    """The instrument: a harvest that named one cause differently is found."""
    real = runner._reply_fault

    def drifted(reply, limit, **options):
        cause, correction = real(reply, limit, **options)
        return ("syntax" if cause == "outside_text" else cause), correction

    monkeypatch.setattr(runner, "_reply_fault", drifted)
    shape = replies.answer(actions=False)
    differ = [name for name, given in PARITY.items()
              if llm_client._read(given, shape)[1]
              != runner._reply_fault(given, 512, key="statements")[0]]
    assert differ == ["outside_text", "fenced", "two objects"]


# ---------------------------------------------------------------------------
# A request that stays unreadable
# ---------------------------------------------------------------------------

def test_a_request_that_stays_unreadable_raises_with_its_cause_and_counts_attempts(
        client):
    made = client("kein JSON", "auch kein JSON", '{"statements": [,]}')
    with llm_client.collecting() as faults:
        with pytest.raises(llm_client.ReplyError) as ended:
            ask()
    # the last thing that went wrong, after every attempt the setting allows
    assert ended.value.cause == "syntax"
    assert ended.value.request == "answer_reply"
    assert ended.value.attempts == llm_client.LLM_MAX_RETRIES
    assert len(made.requests) == llm_client.LLM_MAX_RETRIES
    assert "answer_reply" in str(ended.value) and "syntax" in str(ended.value)
    assert isinstance(ended.value, RuntimeError)     # what always caught it
    assert faults == [{"request": "answer_reply", "cause": "syntax"}]
    assert client.slept == []                        # no pause between replies


def test_a_server_that_does_not_answer_is_retried_after_a_pause(client):
    made = client(RuntimeError("connection reset"))
    with llm_client.collecting() as faults:
        with pytest.raises(llm_client.ReplyError) as ended:
            ask()
    assert ended.value.cause == "not_served"
    assert len(made.requests) == llm_client.LLM_MAX_RETRIES
    assert len(client.slept) == llm_client.LLM_MAX_RETRIES - 1
    # every attempt starts from the original turn: no correction is carried
    assert all(r["messages"] == [{"role": "user", "content": "FRAGE"}]
               for r in made.requests)
    assert faults == [{"request": "answer_reply", "cause": "not_served"}]
    # and a server that comes back is the second attempt's
    made = client(RuntimeError("down"), GOOD)
    assert ask()["statements"]


def test_faults_are_described_by_kind_with_the_count_where_there_are_several():
    def fault(request, cause):
        return {"request": request, "cause": cause}

    assert llm_client.describe_faults([]) == ""
    assert llm_client.describe_faults([fault("a_reply", "syntax")])         == "a_reply: syntax"
    assert llm_client.describe_faults([
        fault("a_reply", "syntax"), fault("b_reply", "empty"),
        fault("a_reply", "syntax"), fault("a_reply", "cut_off")])         == "a_reply: syntax x2, b_reply: empty, a_reply: cut_off"


def test_a_cause_is_one_of_the_closed_set():
    for cause in reading.HOLE_CAUSES:
        assert llm_client.ReplyError(cause, "x").cause == cause
    with pytest.raises(ValueError, match="no cause"):
        llm_client.ReplyError("cutoff", "x")
    assert set(llm_client.FAULT_CAUSES) == set(reading.HOLE_CAUSES) | {
        "not_asked"}


def test_the_request_goes_out_with_its_grammar_and_the_extras_of_every_stage(
        client, monkeypatch):
    monkeypatch.setenv("LLM_SCHEMA", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    made = client(GOOD)
    ask()
    (sent,) = made.requests
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["name"] == "answer_reply"
    assert sent["response_format"]["json_schema"]["schema"] \
        == replies.answer(actions=False)[1]
    assert sent["extra_body"] == request_extras()
    assert sent["max_tokens"] == llm_client.LLM_MAX_TOKENS
    # the one reply with no shape is a JSON object, and still a single one
    made = client('{"Firma": "X"}')
    assert llm_client._ask(None, [{"role": "user", "content": "x"}],
                           temperature=0.1) == {"Firma": "X"}
    assert made.requests[0]["response_format"] == {"type": "json_object"}


def test_extras_follow_the_settings_the_other_stages_use(client, monkeypatch):
    monkeypatch.setenv("LLM_ENABLE_THINKING", "1")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    made = client(GOOD)
    ask()
    assert made.requests[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": True},
        "reasoning_effort": "high"}


# ---------------------------------------------------------------------------
# A reply cut off at its token limit
# ---------------------------------------------------------------------------

CUT = base.reply('{"statements": [{"statement": "x", "basis": "te', "length")


def test_a_cut_off_reply_is_not_asked_again_as_it_stands(client):
    made = client(CUT)
    with pytest.raises(llm_client.ReplyError) as ended:
        llm_client._ask(replies.answer(actions=False),
                        [{"role": "user", "content": "FRAGE"}],
                        temperature=0.1, splittable=True)
    assert ended.value.cause == "cut_off"
    assert len(made.requests) == 1          # the caller halves; nobody retries


def test_a_unit_that_cannot_be_split_gets_twice_the_room_once(client):
    made = client(CUT, GOOD)
    assert ask()["statements"]
    rooms = [r["max_tokens"] for r in made.requests]
    assert rooms == [llm_client.LLM_MAX_TOKENS, 2 * llm_client.LLM_MAX_TOKENS]
    # the correction is not used for a cut: the same turn is asked
    assert made.requests[1]["messages"] == made.requests[0]["messages"]
    made = client(CUT)
    with pytest.raises(llm_client.ReplyError) as ended:
        ask()
    assert ended.value.cause == "cut_off" and len(made.requests) == 2


def test_a_cut_that_is_answered_leaves_no_fault_and_one_that_is_not_leaves_one(
        client):
    """The record holds a request only where it was left without a reply:
    the room given once answers the cut, and the halves the caller asks for
    answer it too. Where nothing answers it, it is one fault and not two."""
    client(CUT, GOOD)
    with llm_client.collecting() as faults:
        assert ask()["statements"]
    assert faults == []
    client(CUT)
    with llm_client.collecting() as faults:
        with pytest.raises(llm_client.ReplyError):
            llm_client._ask(replies.answer(actions=False),
                            [{"role": "user", "content": "FRAGE"}],
                            temperature=0.1, splittable=True)
    assert faults == []                      # the caller's halves answer it
    client(CUT)
    with llm_client.collecting() as faults:
        with pytest.raises(llm_client.ReplyError):
            ask()
    assert faults == [{"request": "answer_reply", "cause": "cut_off"}]


TWO = [{"index": 0, "source": "a", "text": "Der Auszug null steht hier."},
       {"index": 1, "source": "b", "text": "Der Auszug eins steht hier."}]
NOTHING = json.dumps({"statements": [], "complete": False})


def test_a_halved_batch_whose_halves_were_read_leaves_no_fault(client):
    made = client(CUT, NOTHING)
    with llm_client.collecting() as faults:
        out = llm_client.answer_from_sources("Frage?", TWO)
    assert len(made.requests) == 3           # the batch, then its two halves
    assert out["statements"] == [] and out["fault"] is None
    assert faults == []


def test_a_half_that_stays_cut_is_one_fault_of_its_own(client):
    """The violating case: the first half is read, the second one stays cut
    even with more room. That one request is a hole and the record has it
    once; the first reply of the whole batch, which the halves answered, is
    not a second one."""
    client(CUT, NOTHING, CUT)
    with llm_client.collecting() as faults:
        out = llm_client.answer_from_sources("Frage?", TWO)
    assert out["fault"] == "cut_off"
    assert faults == [{"request": "answer_reply", "cause": "cut_off"}]


# ---------------------------------------------------------------------------
# Unread is not "nothing found"
# ---------------------------------------------------------------------------

def _hit(text="Der Wärmebedarf betrug 100 GWh."):
    return {"owner_kind": "section", "owner_id": 1, "content": text,
            "text": text, "title": "T", "document_id": 1, "page_number": 1,
            "image_path": None}


@pytest.fixture
def chat_turn(client, monkeypatch, tmp_path):
    """A turn with the real answer call and the real reader; only the server
    is stood in for. Returns (run, log connection)."""
    log = request_log.connect(tmp_path / "log.db")
    corpus = answer.Corpus(conn=None, index=None, id_to_pos={},
                           embed=lambda item: ([0.0] * 4, False),
                           resolve_image=lambda path: None, log_conn=log)
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                        lambda *a, **k: [_hit()])
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)
    monkeypatch.setattr(answer.code_exec, "is_enabled", lambda: False)
    monkeypatch.setattr(answer.config, "REQUEST_IMAGE_MAX", 0)
    monkeypatch.setattr(answer.config, "CODE_EXEC_MAX_ROUNDS", 0)

    def run(*served, **more):
        # the search phrase is asked first, then the answer
        made = client(*served)
        return answer.answer_question("Wie hoch?", corpus, 1,
                                      [config.SCOPE_TEXT], **more), made

    return run, log


PHRASE = json.dumps({"phrase": "Der Wärmebedarf betrug 100 GWh."})


def test_unreadable_answer_is_not_nothing_found(chat_turn):
    """Every reply to the answer request is unreadable, for every attempt.
    The turn has no answer, its faults say why, and its log row says that the
    replies could not be read, not that the sources hold nothing."""
    run, log = chat_turn
    out, made = run(PHRASE, "kein JSON", "kein JSON", "kein JSON", "kein JSON")
    assert out["answer"] is None
    assert out["statements_made"] == 0
    assert out["faults"] == [{"request": "answer_reply",
                              "cause": "no_object"}]
    (message,) = [row[0] for row in log.execute(
        "SELECT error_message FROM requests")]
    assert message.startswith("Reply unreadable: 1 request(s): "
                              "answer_reply: no_object")
    assert "nothing" not in message.lower()
    assert len(made.requests) == 1 + llm_client.LLM_MAX_RETRIES


def test_an_honest_miss_is_not_a_fault(chat_turn):
    """The case that must stay apart from the one above: the model read the
    excerpts and said they hold nothing."""
    run, log = chat_turn
    out, _made = run(PHRASE, json.dumps({"statements": [],
                                         "complete": False}))
    assert out["answer"] is None and out["faults"] == []
    assert out["statements_made"] == 0
    (message,) = [row[0] for row in log.execute(
        "SELECT error_message FROM requests")]
    assert message == "No statement made"


def test_a_turn_whose_statements_were_all_dropped_says_so_and_has_no_fault(
        chat_turn):
    run, log = chat_turn
    wrote = json.dumps({"statements": [
        {"statement": "Erfunden.", "basis": "text", "index": 0,
         "quote": "Das steht in keinem Auszug dieses Plans."}],
        "complete": True})
    out, _made = run(PHRASE, wrote)
    assert out["answer"] is None and out["faults"] == []
    assert (out["statements_made"], out["statements_dropped"]) == (1, 1)
    row = log.execute("SELECT error_message, n_statements, n_dropped "
                      "FROM requests").fetchone()
    assert row == ("No statement backed (1 of 1 statements dropped)", 1, 1)


def _two_sources(monkeypatch):
    other = {**_hit("Der Wärmebedarf sank um zehn Prozent."), "owner_id": 2}
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                        lambda *a, **k: [_hit(), other])


def test_a_turn_whose_cut_batch_was_halved_and_read_found_nothing_and_is_not_unread(
        chat_turn, monkeypatch):
    """The model's reply to the whole batch was cut off; the two halves were
    read and hold nothing. That is "no statement made", never "could not be
    read", which the first reply alone would have said."""
    run, log = chat_turn
    _two_sources(monkeypatch)
    out, _made = run(PHRASE, base.reply('{"statements": [{"sta', "length"),
                     NOTHING)
    assert out["answer"] is None and out["faults"] == []
    assert out["statements_made"] == 0
    (message,) = [row[0] for row in log.execute(
        "SELECT error_message FROM requests")]
    assert message == "No statement made"


def test_an_unread_batch_beside_dropped_statements_stays_in_the_log(
        chat_turn, monkeypatch):
    """Batch one made a statement that did not stand, batch two could not be
    read: the log says both."""
    run, log = chat_turn
    _two_sources(monkeypatch)
    monkeypatch.setattr(answer.config, "ANSWER_CONTEXT_TOKENS", 1)
    wrong = json.dumps({"statements": [
        {"statement": "Erfunden.", "basis": "text", "index": 0,
         "quote": "Das steht in keinem Auszug dieses Plans."}],
        "complete": False})
    out, _made = run(PHRASE, wrong, "kein JSON")
    assert out["n_batches"] == 2 and out["answer"] is None
    assert (out["statements_made"], out["statements_dropped"]) == (1, 1)
    assert out["faults"] == [{"request": "answer_reply",
                              "cause": "no_object"}]
    (message,) = [row[0] for row in log.execute(
        "SELECT error_message FROM requests")]
    assert message == ("No statement backed (1 of 1 statements dropped); "
                       "1 request(s) unreadable: answer_reply: no_object")


def test_a_turn_that_answered_but_lost_a_small_request_says_so(chat_turn):
    """The search phrase could not be read: the turn falls back to the
    question as its anchor, answers, and the record has the fault."""
    run, log = chat_turn
    out, _made = run("kein JSON", "kein JSON", "kein JSON", "kein JSON", GOOD)
    assert out["answer"] == "Der Bedarf war 100 GWh. [1]"
    assert out["faults"] == [{"request": "search_phrase_reply",
                              "cause": "no_object"}]
    assert out["phrase"] == "Wie hoch?"
    row = log.execute("SELECT error_message, n_statements, n_dropped, "
                      "n_citations FROM requests").fetchone()
    assert row == ("1 request(s) unreadable: search_phrase_reply: no_object",
                   1, 0, 1)


def test_a_swallowed_failure_leaves_a_record(client, monkeypatch):
    """Search phrase, read-off, comparison and the JSON step each end in a
    fallback of their own; each leaves a fault in the turn's list."""
    monkeypatch.setattr(llm_client, "_image_part",
                        lambda path, max_side=None, png=False: {
                            "type": "image_url", "image_url": {"url": "d"}})
    client("kein JSON")
    with llm_client.collecting() as faults:
        assert llm_client.make_search_phrase("Frage?") == ("Frage?", False)
        assert llm_client.read_off_image("Frage?", "b.png", "Balken") is None
        assert llm_client.compare_answers(
            "Frage?", [{"label": "a", "answer": "x"}]) is None
        with pytest.raises(llm_client.ReplyError):
            llm_client.format_as_json("Frage?", "x")
    assert [(f["request"], f["cause"]) for f in faults] == [
        ("search_phrase_reply", "no_object"), ("readoff_reply", "no_object"),
        ("comparison_reply", "no_object"), ("json_reply", "no_object")]
    # a blank phrase is a reply that was read and says nothing
    client(json.dumps({"phrase": " "}))
    with llm_client.collecting() as faults:
        assert llm_client.make_search_phrase("Frage?") == ("Frage?", False)
    assert faults == [{"request": "search_phrase_reply",
                       "cause": "wrong_shape"}]
    # outside a collecting turn nothing is recorded and nothing fails
    llm_client.note_fault("search_phrase_reply", "empty")


def test_a_read_off_in_the_tasks_own_format_is_asked_again_and_not_taken_as_a_reading(
        client, monkeypatch):
    """The task carries a format of its own and the model answered in it: the
    reply is one object, and it has no reading. The reader says so and the
    same single turn goes out again with the cause; the wrong value is never
    the reading (the old loop of its own for this is gone)."""
    monkeypatch.setattr(llm_client, "_image_part",
                        lambda path, max_side=None, png=False: {
                            "type": "image_url", "image_url": {"url": "d"}})
    hijacked = json.dumps({"amount": 1000.0, "unit": "GWh/a"})
    right = json.dumps({"reading": "Erdgas 2035: ca. 600 GWh/a",
                        "value": 600.0, "unit": "GWh/a"})
    made = client(hijacked, right)
    got = llm_client.read_off_image('Gas 2035? Als JSON {"amount": float}',
                                    "c.png", "Erdgas-Balken")
    assert got["value"] == 600.0 and "600" in got["reading"]
    assert len(made.requests) == 2
    first, again = (r["messages"][0]["content"] for r in made.requests)
    assert again[:-1] == first                       # the same text and image
    assert again[-1]["type"] == "text" and 'lacked "reading"' in again[-1]["text"]
    # and where it stays in the task's format it is no reading at all
    made = client(hijacked)
    with llm_client.collecting() as faults:
        assert llm_client.read_off_image("Gas 2035?", "c.png", "x") is None
    assert faults == [{"request": "readoff_reply", "cause": "missing_key"}]
    assert len(made.requests) == llm_client.LLM_MAX_RETRIES


def test_the_faults_of_one_turn_are_not_the_next_ones(chat_turn):
    run, _log = chat_turn
    first, _ = run(PHRASE, "kein JSON")
    second, _ = run(PHRASE, GOOD)
    assert first["faults"] and second["faults"] == []
    assert second["answer"] == "Der Bedarf war 100 GWh. [1]"


def test_a_turn_with_a_server_that_never_answers_ends_with_its_cause(chat_turn):
    run, log = chat_turn
    out, _made = run(RuntimeError("connection refused"))
    assert out["answer"] is None
    assert {f["cause"] for f in out["faults"]} == {"not_served"}
    assert [f["request"] for f in out["faults"]] == [
        "search_phrase_reply", "answer_reply"]
