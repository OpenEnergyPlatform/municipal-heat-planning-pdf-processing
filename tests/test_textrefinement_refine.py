"""Tests for Stage 4 refinement: action application and the window request.

Promised for the request: the reply schema is the grammar of every window
request on a server of one's own as on a hosted one AND exactly one JSON
object is read from each reply, nothing stripped, cut out or closed AND a
reply that is not that object is asked again with its cause named AND a reply
that was cut off is never asked again as it stands but in halves, or with more
room for a lone section, and what is left is a Hole with its cause. Each AND
has its own tests below, each with a case built to break it.
"""
import json
from types import SimpleNamespace as NS

import pytest

from docpipe import reading
from docpipe.reading import Hole
from docpipe.refinement import refine as s4
from docpipe.refinement import replies


def _reply(content, finish="stop", reasoning=None):
    """A chat response with the fields the reader looks at."""
    return NS(choices=[NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=reasoning))], usage=None)


def _sections(*titles):
    return json.dumps({"sections": [{"_action": "keep", "title": t}
                                    for t in titles]})


def _server(*answers):
    """(client, requests): a client that answers its requests with *answers*
    in turn, an Exception being raised, and the requests it was asked."""
    asked: list = []
    queue = list(answers)

    def create(**kwargs):
        asked.append(kwargs)
        item = queue.pop(0) if queue else answers[-1]
        if isinstance(item, BaseException):
            raise item
        return item

    return NS(chat=NS(completions=NS(create=create))), asked


def test_the_name_of_the_old_reader_is_gone():
    """Removed means removed: nothing here cuts an object out of text."""
    assert not hasattr(s4, "_loads_json_object")


def test_tail_text():
    assert s4._tail_text("abcdef", 3) == "def"
    assert s4._tail_text("ab", 5) == "ab"
    assert s4._tail_text(["@book{a}", "@book{b}"], 100).startswith("@book{a}")


def test_coerce_section_normalises_types():
    s = s4._coerce_section({"title": 123, "content": {"x": 1}, "tables": "nope",
                            "_action": "remove"})
    assert s == {"title": "123", "content": "", "tables": [], "figures": [],
                 "_action": "remove"}
    assert s4._coerce_section("not a dict")["_action"] == "keep"
    assert s4._coerce_section({"content": ["@book{x}"]})["content"] == ["@book{x}"]


def test_is_empty_section():
    assert s4._is_empty_section({"content": "  ", "tables": [], "figures": []})
    assert not s4._is_empty_section({"content": "x"})
    assert not s4._is_empty_section({"content": "", "tables": [{"id": "t"}]})
    assert not s4._is_empty_section({"content": ["@book{x}"]})


def test_apply_actions_keep_remove_merge():
    sections = [
        {"title": "A", "content": "a", "_action": "keep"},
        {"title": "B", "content": "b", "_action": "merge_into_previous"},
        {"title": "C", "content": "c", "_action": "remove"},
        {"title": "D", "content": "d", "_action": "keep"},
    ]
    result, last = s4._apply_actions(sections, None)
    assert [s["title"] for s in result] == ["A", "D"]
    assert result[0]["content"] == "a b"      # B merged into A
    assert last["title"] == "D"


def test_apply_actions_merges_across_window_boundary():
    prev = {"title": "Prev", "content": "p", "tables": [], "figures": []}
    sections = [{"title": "frag", "content": "x", "_action": "merge_into_previous"}]
    result, _ = s4._apply_actions(sections, prev)
    assert result == []                # nothing new emitted
    assert prev["content"] == "p x"    # merged into the carried-over previous section


def test_apply_actions_tolerates_non_dict_section():
    result, _ = s4._apply_actions([{"title": "K", "_action": "keep"}, "junk"], None)
    assert [s["title"] for s in result] == ["K", ""]


def test_block_ids_of_output_tolerates_non_dict():
    # The LLM occasionally emits a bare string where a section object belongs;
    # provenance threading (_redistribute_segments) must not crash on it.
    assert s4._block_ids_of_output("a bogus string section") == set()
    assert s4._block_ids_of_output({"content": "[p1_tbl0] text",
                                    "tables": [{"id": "p1_tbl0"}]}) == {"p1_tbl0"}


def test_call_llm_happy_path(make_client, seq_responder):
    client = make_client(seq_responder(['{"sections": [{"_action": "keep", "title": "A"}]}']))
    assert s4._call_llm([{"title": "A", "content": "x"}], client) == [
        {"_action": "keep", "title": "A"}
    ]


def test_call_llm_asks_inside_the_schema_on_its_own_server(
        make_client, seq_responder, monkeypatch):
    """The grammar goes out on a server of one's own with LLM_SCHEMA unset,
    which used to be a json_object that let fences, think blocks and prose
    through."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_SCHEMA", raising=False)
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    s4._call_llm([{"t": 1, "segments": [], "pages": [1]}], client)
    shape = rec[0]["response_format"]
    assert shape != {"type": "json_object"}, "the old default"
    assert shape == {"type": "json_schema", "json_schema": {
        "name": "refined_sections", "schema": replies.window([{"t": 1}])}}
    assert "max_tokens" in rec[0] and "temperature" in rec[0]


def test_the_corrections_mode_asks_inside_its_own_schema(
        make_client, seq_responder, monkeypatch):
    monkeypatch.setattr(s4, "REFINE_RETURN_CORRECTIONS", True)
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    s4._call_llm([{"title": "A", "content": "x"}], client)
    assert rec[0]["response_format"]["json_schema"] == {
        "name": "refined_sections", "schema": replies.CORRECTIONS}


def test_the_cut_request_asks_inside_the_schema_too(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(['{"cuts": []}']), recorder=rec)
    assert s4._make_splitter(client)("system", "user") == {"cuts": []}
    assert rec[0]["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "section_cuts", "schema": replies.SPLIT}}


def test_a_cut_request_for_one_segment_is_asked_again_with_twice_the_room_where_the_window_is_not_known():
    """Through the real request, not a stand-in for it: the room that
    `split._ask_range` asks for is the room the request is sent with. A
    request that ignored it asked the same thing twice and called it more
    room. No preflight ran, so the served window is not known and the room is
    twice; what a known window leaves is held in tests/test_room.py."""
    from docpipe.refinement import split

    section = {"title": "T", "content": "x", "segments": [
        {"kind": "text", "text": "x", "page": 1}]}
    client, rec = _server(_reply('{"cuts": [{"at": ', "length"),
                          _reply('{"cuts": []}'))
    got = split._ask_cuts(section, s4._make_splitter(client))
    assert got == {"cuts": []}
    assert len(rec) == 2, "once as asked, once with more room"
    assert rec[1]["max_tokens"] == 2 * rec[0]["max_tokens"]
    assert rec[1]["messages"] == rec[0]["messages"], (
        "nothing is told to the model about the cut")


def test_a_cut_request_for_one_segment_that_is_cut_off_twice_is_a_hole():
    from docpipe.refinement import split

    section = {"title": "T", "content": "x", "segments": [
        {"kind": "text", "text": "x", "page": 1}]}
    client, rec = _server(_reply('{"cuts": [{"at": ', "length"))
    assert split._ask_cuts(section, s4._make_splitter(client)) == Hole(
        "cut_off", f"{rec[1]['max_tokens']} tokens")
    assert len(rec) == 2, "never a third request"


def test_the_preflight_is_given_the_shapes_the_requests_send():
    shapes = s4.reply_shapes()
    assert set(shapes) == {"refined_sections", "section_cuts"}
    assert shapes["section_cuts"] == replies.SPLIT
    assert shapes["refined_sections"]["required"] == ["sections"]


def test_call_llm_injects_previous_context(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    prev = {"title": "Vorheriger", "content": "…ENDE-MARKER"}
    s4._call_llm([{"title": "X"}], client, prev)
    user_msg = rec[0]["messages"][1]["content"]
    assert "CONTEXT (read-only" in user_msg
    assert "ENDE-MARKER" in user_msg and "merge_into_previous" in user_msg


def test_call_llm_retries_after_bad_json(make_client, seq_responder):
    client = make_client(seq_responder(["garbage", '{"sections": []}']))
    assert s4._call_llm([{"t": 1}], client) == []


def test_call_llm_exhausts_to_a_hole_with_its_cause(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(["garbage"]), recorder=rec)
    assert s4._call_llm([{"t": 1}], client) == Hole("no_object")
    assert len(rec) == s4.MAX_RETRIES, "an unreadable reply is asked again"


# ---------------------------------------------------------------------------
# A reply that is not the object is asked again with its cause, never repaired
# ---------------------------------------------------------------------------

def test_a_reply_that_is_not_the_object_is_asked_again_with_its_cause():
    """The old code unwrapped the fenced object and used it. Its first
    section carries another title, which must be found nowhere."""
    fenced = "```json\n" + _sections("WRONG TITLE", "B") + "\n```"
    client, rec = _server(_reply(fenced), _reply(_sections("A")))
    got = s4._call_llm([{"title": "A", "content": "x"}], client)
    assert got == [{"_action": "keep", "title": "A"}]
    assert "WRONG TITLE" not in json.dumps(got)
    assert len(rec) == 2
    first, second = rec[0]["messages"], rec[1]["messages"]
    assert second[:2] == first[:2], "the request again, as it was"
    assert second[2] == {"role": "assistant", "content": s4._echo(fenced)}
    said = second[3]
    assert said["role"] == "user"
    assert "There was text beside the JSON object" in said["content"]
    assert said["content"].endswith(reading.say("shape_rule"))
    assert len(second) == 4, "base, the answer, what was wrong: nothing else"


@pytest.mark.parametrize("answer,phrase", [
    (_reply("<think>so</think>" + _sections("WRONG TITLE")),
     "text beside the JSON object"),
    (_reply(""), "Your answer was empty"),
    (_reply("{}"), 'lacked "sections"'),
    (_reply('{"sections": "x"}'), '"sections" was not a list'),
    (_reply("[1]"), "list structure"),
    (_reply("no json at all"), "no JSON object at all"),
    (_reply('{"sections": [{"title": '), "breaks at character"),
    (_reply("", reasoning="thinking out loud"), "You only thought"),
])
def test_each_cause_is_named_to_the_model_in_the_profiles_words(answer, phrase):
    client, rec = _server(answer, _reply(_sections("OK")))
    got = s4._call_llm([{"title": "A"}], client)
    assert got == [{"_action": "keep", "title": "OK"}]
    assert phrase in rec[1]["messages"][3]["content"]


def test_the_answer_that_is_echoed_back_is_bounded():
    long_text = "x " * 5000
    client, rec = _server(_reply(long_text), _reply(_sections("OK")))
    s4._call_llm([{"title": "A"}], client)
    assert rec[1]["messages"][2]["content"] == s4._echo(long_text)
    assert "characters omitted" in rec[1]["messages"][2]["content"]


def test_a_reply_that_breaks_in_our_own_code_is_a_hole_and_not_an_outage(
        monkeypatch, caplog):
    """The reading is outside the request's try: our own failure after the
    reply arrived is not 'LLM request failed', and is not retried as one."""
    monkeypatch.setattr(s4, "REFINE_RETURN_CORRECTIONS", True)

    def broken(reply, window):
        raise ValueError("our own bug")

    monkeypatch.setattr(s4, "_materialise_corrections", broken)
    client, rec = _server(_reply(_sections("A")))
    with caplog.at_level("ERROR"):
        got = s4._call_llm([{"title": "A"}], client)
    assert got == Hole("error", "ValueError: our own bug")
    assert len(rec) == 1
    assert "our own bug" in caplog.text and "Traceback" in caplog.text
    assert "LLM request failed" not in caplog.text


# ---------------------------------------------------------------------------
# A reply that was cut off is never asked again as it stands
# ---------------------------------------------------------------------------

# One complete section inside the cut: what the old code could have salvaged.
CUT = ('{"sections": [{"title": "SALVAGEABLE", "content": "one complete one"},'
       ' {"title": "Cu')


def _window(*titles):
    return [{"title": t, "content": f"text of {t}", "segments": [], "pages": [1]}
            for t in titles]


def _titles(rec):
    """The section titles each request carried."""
    out = []
    for kwargs in rec:
        body = kwargs["messages"][1]["content"].split("SECTIONS TO PROCESS:\n")[-1]
        out.append([s["title"] for s in json.loads(body)["sections"]])
    return out


def test_a_cut_reply_is_a_hole_and_is_not_used_or_asked_again():
    client, rec = _server(_reply(CUT, finish="length"))
    got = s4._call_llm(_window("A"), client)
    assert got.cause == "cut_off" and "tokens" in got.detail
    assert len(rec) == 1, "not MAX_RETRIES identical requests"


def test_a_cut_window_is_asked_in_halves():
    """Three sections: the whole, then [0] and [1, 2]. The complete section
    inside the cut reply is not used, and the second half sees the last
    section of the first as its context, as the next window would."""
    client, rec = _server(_reply(CUT, finish="length"),
                          _reply(_sections("A*")),
                          _reply(_sections("B*", "C*")))
    got = s4._ask_window(_window("A", "B", "C"), client,
                         {"title": "Before", "content": "ENDE-DAVOR"})
    assert _titles(rec) == [["A", "B", "C"], ["A"], ["B", "C"]]
    assert [s["title"] for s in got] == ["A*", "B*", "C*"], "in input order"
    assert "SALVAGEABLE" not in json.dumps(got)
    first = rec[1]["messages"][1]["content"]
    second = rec[2]["messages"][1]["content"]
    assert "ENDE-DAVOR" in first, "the first half has the window's context"
    assert "text of A" in second.split("SECTIONS TO PROCESS")[0], (
        "the second half has the last section of the first half as context")
    assert "ENDE-DAVOR" not in second


def test_halves_are_asked_again_down_to_one_section():
    client, rec = _server(_reply(CUT, "length"), _reply(_sections("A*")),
                          _reply(CUT, "length"), _reply(_sections("B*")),
                          _reply(_sections("C*")))
    got = s4._ask_window(_window("A", "B", "C"), client, None)
    # the whole; [A]; [B, C], which is cut off again; then [B] and [C]
    assert _titles(rec) == [["A", "B", "C"], ["A"], ["B", "C"], ["B"], ["C"]]
    assert [s["title"] for s in got] == ["A*", "B*", "C*"]


def test_a_lone_section_that_is_cut_off_gets_twice_the_room_once_where_the_window_is_not_known_and_is_a_hole():
    client, rec = _server(_reply(CUT, finish="length"))
    got = s4._ask_window(_window("A"), client, None)
    assert isinstance(got, Hole) and got.cause == "cut_off"
    assert len(rec) == 2, "once as asked, once with more room, never a third"
    assert rec[1]["max_tokens"] == 2 * rec[0]["max_tokens"]
    # the same request otherwise: nothing is told to the model about the cut
    assert rec[1]["messages"] == rec[0]["messages"]


def test_the_extra_room_is_spent_once_on_a_section_that_then_fits():
    client, rec = _server(_reply(CUT, "length"), _reply(_sections("A*")))
    got = s4._ask_window(_window("A"), client, None)
    assert [s["title"] for s in got] == ["A*"]
    assert len(rec) == 2


def test_a_window_with_one_part_that_is_a_hole_is_assembled_by_parts():
    """First half read, second half (one section) cut off even with more
    room: only the second part is a hole."""
    client, rec = _server(_reply(CUT, "length"), _reply(_sections("A*")),
                          _reply(CUT, "length"))
    got = s4._ask_window(_window("A", "B"), client, None)
    assert isinstance(got, s4.Halved)
    assert [(offset, [s["title"] for s in part], type(reply).__name__)
            for offset, part, reply in got.parts] == [
        (0, ["A"], "list"), (1, ["B"], "Hole")]
    assert len(rec) == 4, "whole, A, B, B with more room"


def test_a_part_that_is_not_served_makes_the_whole_window_not_served():
    """A resume asks the whole window again: a half read beside a half nobody
    answered is no result."""
    client, _rec = _server(_reply(CUT, "length"), _reply(_sections("A*")),
                           RuntimeError("down"))
    assert s4._ask_window(_window("A", "B"), client, None) is s4.NOT_SERVED


def test_call_llm_on_a_server_that_is_down_is_not_a_none(make_client,
                                                         seq_responder):
    """None is a window the model could do nothing with, and it keeps its
    text. A window nobody answered is asked again another time."""
    client = make_client(seq_responder([RuntimeError("down")]))
    assert s4._call_llm([{"t": 1}], client) is s4.NOT_SERVED


def test_strip_table_source_text():
    secs = [
        {"tables": [{"id": "t", "source_text": "x"}, {"id": "u"}], "figures": []},
        "junk",   # non-dict tolerated
    ]
    s4._strip_table_source_text(secs)
    assert "source_text" not in secs[0]["tables"][0]
    assert secs[0]["tables"][1] == {"id": "u"}


def test_run_refine_uses_provided_data(tmp_path):
    out = s4.run_refine(tmp_path, data={"sections": []})
    assert out == {"sections": []}
    assert (tmp_path / "results" / "sections_refined.json").exists()


def test_run_refine_missing_input_returns_none(tmp_path):
    assert s4.run_refine(tmp_path, data=None) is None


# ---------------------------------------------------------------------------
# The repair turn must not resend the failed answer
# ---------------------------------------------------------------------------

def test_a_short_answer_is_echoed_whole():
    from docpipe.refinement.refine import _echo

    assert _echo("kurz und falsch") == "kurz und falsch"


def test_a_long_answer_is_bounded_before_it_goes_back():
    """A window is already ~18k tokens; echoing 8k more is what pushed a retry
    past the 32k context limit — the original request never came close."""
    from docpipe.refinement.refine import _ECHO_HEAD, _ECHO_TAIL, _echo

    raw = "A" * 20000 + "ENDE"
    out = _echo(raw)

    assert len(out) < _ECHO_HEAD + _ECHO_TAIL + 80
    assert out.startswith("A" * 100)
    assert out.endswith("ENDE")
    assert "characters omitted" in out


# ---------------------------------------------------------------------------
# Saying out loud what the stage threw away
# ---------------------------------------------------------------------------

def _prose(word: str, n: int = 40) -> str:
    return " ".join(f"{word}{i}" for i in range(n))


def test_the_stage_names_the_sections_it_dropped(caplog):
    """Two bugs shipped because nothing reported what came out of this stage,
    and a falling section count is normal here — a book's index is meant to be
    removed. So the titles are reported and the judgement is left to the
    reader: 'Index' and a chapter heading read very differently."""
    from docpipe.refinement.refine import _report_dropped_text

    before = [{"title": "Index", "content": _prose("entry")},
              {"title": "3.2 Heat demand", "content": _prose("demand")},
              {"title": "3.3 Supply", "content": _prose("supply")}]
    with caplog.at_level("INFO"):
        _report_dropped_text(before, before[1:])
    text = caplog.text
    assert "1 section(s) removed entirely" in text
    assert "'Index'" in text
    assert "3.2 Heat demand" not in text, "only what is gone is named"


def test_an_edited_section_does_not_count_as_dropped(caplog):
    """The check has to survive the corrections the stage exists to apply."""
    from docpipe.refinement.refine import _report_dropped_text

    before = [{"title": "A", "content": "Die Wärme- versorgung " + _prose("x")}]
    after = [{"title": "A", "content": "Die Wärmeversorgung " + _prose("x")}]
    with caplog.at_level("INFO"):
        _report_dropped_text(before, after)
    assert "removed entirely" not in caplog.text


def test_the_report_never_breaks_the_run(caplog):
    """It runs after an hour of GPU time; it may not be the thing that fails."""
    from docpipe.refinement.refine import _report_dropped_text

    _report_dropped_text([{"content": None}, {}, {"content": ["bibtex"]}],
                         [None])


# ---------------------------------------------------------------------------
# A refused request is a verdict, not a bad moment
# ---------------------------------------------------------------------------

class _Refused(Exception):
    """What the SDK raises on a 4xx: an error carrying the HTTP status."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


_TOO_LONG = ("This model's maximum context length is 32768 tokens, however you "
             "requested 41210 tokens")


@pytest.fixture
def slept(monkeypatch):
    """Every sleep _backoff asks for, in seconds."""
    seconds = []
    monkeypatch.setattr(s4.time, "sleep", lambda s: seconds.append(s))
    return seconds


def test_an_oversized_window_is_abandoned_not_retried(
        make_client, seq_responder, slept, caplog):
    """The window that does not fit does not start fitting: the old loop sent
    it three more times, unchanged, with ~12 s of backoff in between."""
    rec = []
    client = make_client(seq_responder([_Refused(_TOO_LONG)]), recorder=rec)

    with caplog.at_level("ERROR"):
        result = s4._call_llm([{"title": "3.2 Wärmebedarf", "content": "x"}], client)

    assert result == Hole("refused", "HTTP 400")
    assert len(rec) == 1 and slept == []


def test_the_abandoned_window_is_named_out_loud(make_client, seq_responder, caplog):
    """The caller keeps such a window as raw text, which in the output is
    indistinguishable from a window that needed no change — so the hole exists
    only if this says so."""
    client = make_client(seq_responder([_Refused(_TOO_LONG)]))

    with caplog.at_level("ERROR"):
        s4._call_llm([{"title": "3.2 Wärmebedarf", "content": "x"},
                      {"title": "3.3 Versorgung", "content": "y"}], client)

    assert "ABANDONED" in caplog.text
    assert "3.2 Wärmebedarf" in caplog.text and "3.3 Versorgung" in caplog.text


def test_any_other_client_error_also_stops_at_once(
        make_client, seq_responder, slept):
    rec = []
    client = make_client(seq_responder([_Refused("unknown parameter", 400)]),
                         recorder=rec)

    assert s4._call_llm([{"t": 1}], client) == Hole("refused", "HTTP 400")
    assert len(rec) == 1 and slept == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_busy_or_broken_server_is_still_retried(
        make_client, seq_responder, status):
    """429 and 5xx are the server asking for time, not refusing the request."""
    client = make_client(seq_responder([_Refused("later", status),
                                        '{"sections": []}']))

    assert s4._call_llm([{"t": 1}], client) == []
