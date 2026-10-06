"""A reply cut off at its token limit, and the retry ladder.

Sparse Gantt grids make the model lose count and emit empty cells until the
reply runs into its limit. The reply says so itself (`finish_reason` "length"),
so it is not told apart by a pattern in its text any more.

Promised: a cut reply is never asked again as it stands and never used (an image
has no halves) AND it is asked once more from the original prompt, with the next
repetition penalty and more room, without a word about the cut AND if that
one is cut off too the item is a hole with the cause cut_off AND a reply that is
long but whole is read, not retried. How much room, and when there is none, is
held in tests/test_room.py; the requests here ask no preflight, so the served
window is not known and the room is twice.
"""
from types import SimpleNamespace as NS

import pytest

from docpipe.reading import Hole
from docpipe.visuals import replies
from docpipe.visuals import vision as V

ASKED = dict(reply=replies.TABLE)
OK = '{"markdown": "| a |"}'
# a grid that lost count: cut in the middle of its row
RUNAWAY = '{"markdown": "| Rahmen ' + "| " * 40


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"\x89PNG\r\n")
    return p


def _answer(content, finish="stop"):
    return NS(choices=[NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=None))], usage=None)


def _server(*answers):
    """(client, requests): answers in turn, the last one again after that."""
    asked: list = []
    queue = list(answers)

    def create(**kwargs):
        asked.append(kwargs)
        item = queue.pop(0) if queue else answers[-1]
        if isinstance(item, BaseException):
            raise item
        return item

    return NS(chat=NS(completions=NS(create=create))), asked


def _penalties(asked):
    return [r.get("extra_body", {}).get("repetition_penalty") for r in asked]


def test_a_cut_reply_restarts_from_the_original_prompt_with_the_next_penalty(
        png):
    client, asked = _server(_answer(RUNAWAY, "length"), _answer(OK))
    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "| a |"}
    first, second = asked
    assert len(second["messages"]) == 2, "the cut answer is not echoed back"
    assert second["messages"] == first["messages"], (
        "the original prompt again, nothing said about the cut")
    assert _penalties(asked) == [None, 1.1]


def test_the_retry_after_a_cut_gets_twice_the_room_where_the_window_is_not_known(
        png):
    client, asked = _server(_answer(RUNAWAY, "length"), _answer(OK))
    V.call_vision(client, "sys", "user", png, max_tokens=1000, **ASKED)
    assert [r["max_tokens"] for r in asked] == [1000, 2000]


def test_a_reply_cut_off_twice_is_a_hole_and_the_room_is_given_once(png):
    client, asked = _server(_answer(RUNAWAY, "length"))
    got = V.call_vision(client, "sys", "user", png, max_tokens=1000, **ASKED)
    assert isinstance(got, Hole) and got.cause == "cut_off"
    assert [r["max_tokens"] for r in asked] == [1000, 2000], (
        "once as asked, once with more room: never a third request")


def test_a_cut_reply_is_never_content_whatever_it_holds(png):
    """Half a table, closed or not: a hole, not the first half of a table."""
    half = '{"markdown": "| Jahr | MWh |\\n| --- | --- |\\n| 2024 | 12 |"}'
    client, _ = _server(_answer(half, "length"), _answer(half, "length"))
    # a reply that parses and is whole is read even when it says "length":
    # the harvest reads such a reply too
    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "| Jahr | MWh |\n| --- | --- |\n| 2024 | 12 |"}
    cut = '{"markdown": "| Jahr | MWh |\\n| --- | --- |\\n| 2024 | 12 |'
    client, _ = _server(_answer(cut, "length"))
    got = V.call_vision(client, "sys", "user", png, **ASKED)
    assert isinstance(got, Hole) and got.cause == "cut_off"


def test_a_closed_object_with_empty_cells_that_ended_normally_is_read_not_retried(
        png):
    """The case built to break the old detector's replacement: thirty empty
    cells are a table as far as a reader of the reply can tell. The regex used
    to retry this; finish_reason says it ended on its own."""
    grid = '{"markdown": "| Rahmen ' + "| " * 30 + '|"}'
    client, asked = _server(_answer(grid, "stop"))
    got = V.call_vision(client, "sys", "user", png, **ASKED)
    assert got["markdown"].startswith("| Rahmen")
    assert len(asked) == 1


def test_a_cut_is_not_mistaken_for_a_formatting_slip(png):
    """A formatting slip is fed back with its cause; a cut is not."""
    client, asked = _server(_answer("not json at all"), _answer(OK))
    V.call_vision(client, "sys", "user", png, **ASKED)
    assert len(asked[1]["messages"]) == 4, "the model sees its own answer"
    assert "repetition_penalty" not in asked[1].get("extra_body", {})
    assert asked[1]["max_tokens"] == asked[0]["max_tokens"], "no more room"


def test_a_cut_on_the_last_attempt_is_a_hole(png):
    client, asked = _server(_answer(RUNAWAY, "length"))
    got = V.call_vision(client, "sys", "user", png, max_retries=1, **ASKED)
    assert got.cause == "cut_off"
    assert len(asked) == 1


# ---------------------------------------------------------------------------
# The penalty ladder after a timeout is what it was
# ---------------------------------------------------------------------------

def test_the_penalty_escalates_across_timeouts(openai_error, png):
    client, asked = _server(openai_error("t", timeout=True),
                            openai_error("t", timeout=True),
                            openai_error("t", timeout=True), _answer(OK))
    assert V.call_vision(client, "sys", "user", png, **ASKED) == {
        "markdown": "| a |"}
    assert _penalties(asked) == [None, 1.1, 1.3, 1.3]


def test_the_first_attempt_carries_no_penalty(png):
    """A table legitimately repeats pipes, dashes and units."""
    client, asked = _server(_answer(OK))
    V.call_vision(client, "sys", "user", png, **ASKED)
    assert "repetition_penalty" not in asked[0].get("extra_body", {})


def test_no_stop_sequence_is_sent(png):
    """A stop on the empty-cell run cut the answer mid-JSON and cost more in
    repair than it saved in tokens."""
    client, asked = _server(_answer(OK))
    V.call_vision(client, "sys", "user", png, **ASKED)
    assert not asked[0].get("stop")


def test_the_context_budget_counts_one_reply():
    """The room given after a cut comes out of what the served window leaves
    beyond the budget, so the budget holds ONE reply."""
    from docpipe.visuals import config as C
    prompts = max(len(C.table_system_prompt().split()),
                  len(C.figure_system_prompt().split()))
    assert C.max_request_tokens() == int(
        prompts * C.TOKENS_PER_WORD + C.IMAGE_TOKENS + C.VLM_MAX_TOKENS)
    assert C.max_request_tokens() != int(
        prompts * C.TOKENS_PER_WORD + C.IMAGE_TOKENS + 2 * C.VLM_MAX_TOKENS)
