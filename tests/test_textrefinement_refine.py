"""Tests for Stage 4 refinement: JSON parsing, action application, vLLM call."""
import json

import pytest

from docpipe.refinement import refine as s4


def test_loads_json_object_direct_and_fallback():
    assert s4._loads_json_object('{"a": 1}') == {"a": 1}
    assert s4._loads_json_object('noise {"a": 2} tail') == {"a": 2}
    with pytest.raises(json.JSONDecodeError):
        s4._loads_json_object("no json here")


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


def test_call_llm_request_uses_json_object_format(make_client, seq_responder):
    rec = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=rec)
    s4._call_llm([{"t": 1}], client)
    assert rec[0]["response_format"] == {"type": "json_object"}
    assert "max_tokens" in rec[0] and "temperature" in rec[0]


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


def test_call_llm_exhausts_to_none(make_client, seq_responder):
    client = make_client(seq_responder([RuntimeError("down")]))
    assert s4._call_llm([{"t": 1}], client) is None


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

    assert result is None
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

    assert s4._call_llm([{"t": 1}], client) is None
    assert len(rec) == 1 and slept == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_busy_or_broken_server_is_still_retried(
        make_client, seq_responder, status):
    """429 and 5xx are the server asking for time, not refusing the request."""
    client = make_client(seq_responder([_Refused("later", status),
                                        '{"sections": []}']))

    assert s4._call_llm([{"t": 1}], client) == []
