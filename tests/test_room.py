"""The room a cut-off unit is given once more, and the budget that stays one reply.

The owner serves every model of this pipeline with a window of 32768 tokens on
purpose (the key-value cache of a larger window is taken from the requests
that run side by side), and no request of the pipeline may need more. A unit
whose reply was cut off at its token limit and that cannot be split (a lone
section, an outline of one segment, an image, a page) is asked once more with
more room. The first build paid for that room by counting a second reply in
the budget of each stage, which took the budget of stage 4 past the window.

Promised, in one sentence: a unit whose reply was cut off and that cannot be
split is asked once more with more room, AND that room is twice what the
request asked for or as much of it as the served window leaves, whichever is
smaller, AND the context budget each of the three stages prints and checks its
server against is the prompt, the largest input and ONE largest reply, AND
when the served window leaves no more room than the request already had, the
unit is a hole with the cause cut_off at once and no second request is sent,
AND where the served window is not known (a hosted model whose window is its
own, a caller that asked no server) the room is twice.

Each AND has its tests below, over the four units (a lone window and an outline
of one segment in stage 4, an image in stage 5, a page of the transcription),
and each has a case built to violate it. What a window leaves is counted from
the window the server reported at the preflight, minus the stage's own budget;
the numbers of stage 4 are made small here (a reply ceiling of 1000 tokens) so
that every boundary is a few tokens away.
"""
import logging
import sys
from types import SimpleNamespace as NS

import pytest

from docpipe import llm_preflight
from docpipe.llm_preflight import PreflightError, further_room, served_window
from docpipe.profile import load_profile
from docpipe.providers import base
from docpipe.reading import Hole
from docpipe.refinement import config as RC
from docpipe.refinement import pipeline as RP
from docpipe.refinement import refine as s4
from docpipe.refinement import split
from docpipe.visuals import config as VC
from docpipe.visuals import pipeline as IP
from docpipe.visuals import process as P
from docpipe.visuals.models import ProcessingStats
from tests.test_entry_points import _budget, _run

# What the owner serves every model with, and so what no request may exceed.
SERVED_WINDOW = 32768


# ---------------------------------------------------------------------------
# A server that is asked, and one that cuts every reply off
# ---------------------------------------------------------------------------

def _answer(content, finish="stop"):
    return NS(choices=[NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=None))], usage=None)


def _replies(*answers):
    """(client, requests): the answers in turn, the last one again after that."""
    sent: list = []
    queue = list(answers)

    def create(**kwargs):
        sent.append(kwargs)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return NS(chat=NS(completions=NS(create=create))), sent


def _cut_server(content):
    """Every reply stops at its token limit, in the middle of *content*."""
    return _replies(_answer(content, "length"))


def _preflight(monkeypatch, role, window, required, *, hosted=False):
    """The real `assert_serving`, against a server that reports *window* (None:
    it reports none) and is asked for a request of *required* tokens. A hosted
    API is told apart from a server of one's own by the role's provider."""
    card = NS(id="m", max_model_len=window)
    client = base.facade(lambda **kw: base.reply('{"ok": true}', "stop"),
                         models=lambda: NS(data=[card]))
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)
    variable = f"{role.upper()}_PROVIDER"
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VLM_PROVIDER", raising=False)
    if hosted:
        monkeypatch.setenv(variable, "gemini")
    try:
        return llm_preflight.assert_serving(
            "http://x/v1", "EMPTY", "m", required, what="a stage", role=role)
    finally:
        monkeypatch.delenv(variable, raising=False)


# ---------------------------------------------------------------------------
# The four units, each one cut off at its limit however often it is asked
#
# A scene is the role whose server is asked, the budget its stage checks that
# server against, and `run()`: the requests' token limits in the order they
# were sent, and the cause of the hole the unit ended as (None: it was read).
# ---------------------------------------------------------------------------

def _window_scene(monkeypatch, tmp_path, words=400):
    """A window of one section. 400 words ask for the ceiling (1000 tokens); a
    window of a single word asks for the floor (300), which is less than the
    reply the budget counts."""
    monkeypatch.setattr(RC, "REPLY_TOKENS_CEILING", 1000)
    monkeypatch.setenv("LLM_MAX_TOKENS", "300")
    section = {"title": "A", "content": " ".join(["w"] * words),
               "segments": [], "pages": [1]}

    def run():
        client, sent = _cut_server('{"sections": [{"title": "Cu')
        got = s4._ask_window([section], client, None)
        return ([r["max_tokens"] for r in sent],
                got.cause if isinstance(got, Hole) else None)
    return NS(role="llm", budget=RC.max_request_tokens(), run=run)


def _outline_scene(monkeypatch, tmp_path, asked=1000):
    """The outline of one segment, which asks for *asked* tokens: as many as
    the reply the budget counts, or fewer."""
    monkeypatch.setattr(RC, "REPLY_TOKENS_CEILING", 1000)
    monkeypatch.setattr(s4, "split_max_tokens", lambda: asked)
    section = {"title": "T", "content": "x", "segments": [
        {"kind": "text", "text": "x", "page": 1}]}

    def run():
        client, sent = _cut_server('{"cuts": [{"at": ')
        got = split._ask_cuts(section, s4._make_splitter(client))
        return ([r["max_tokens"] for r in sent],
                got.cause if isinstance(got, Hole) else None)
    return NS(role="llm", budget=RC.max_request_tokens(), run=run)


def _image(tmp_path):
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "i.png").write_bytes(b"\x89PNG\r\n")
    return {"id": "i", "path": "images/i.png"}


def _figure_scene(monkeypatch, tmp_path):
    def run():
        client, sent = _cut_server('{"description": "Ein Anfang')
        got = P.process_figure(_image(tmp_path), {"title": "S"}, tmp_path,
                               client, ProcessingStats())
        return [r["max_tokens"] for r in sent], got.get("vlm_why")
    return NS(role="vlm", budget=VC.max_request_tokens(), run=run)


def _table_scene(monkeypatch, tmp_path):
    def run():
        client, sent = _cut_server('{"markdown": "| Jahr | MWh')
        got = P.process_table(_image(tmp_path), {"title": "S"}, tmp_path,
                              client, ProcessingStats())
        return [r["max_tokens"] for r in sent], got.get("vlm_why")
    return NS(role="vlm", budget=VC.max_request_tokens(), run=run)


def _page_scene(monkeypatch, tmp_path):
    from docpipe.preprocessing.page_text_fallback import (make_transcriber,
                                                          page_request_tokens)

    def run():
        client, sent = _cut_server('{"markdown": "Ein Anfang der')
        page = tmp_path / "page.png"
        page.write_bytes(b"\x89PNG\r\n")
        got = make_transcriber(None, client=client, model="m")(page, 1)
        return ([r["max_tokens"] for r in sent],
                got.cause if isinstance(got, Hole) else None)
    return NS(role="vlm", budget=page_request_tokens(None), run=run)


# The units whose first request asks for as many tokens as the reply their
# budget counts: what is left to the window decides how much more they get.
FULL = {"window": _window_scene, "outline": _outline_scene,
        "figure": _figure_scene, "table": _table_scene, "page": _page_scene}
# The units that asked for less than that reply.
SMALL = {"small window": lambda m, t: _window_scene(m, t, words=1),
         "small outline": lambda m, t: _outline_scene(m, t, asked=300)}
EVERY = {**FULL, **SMALL}


def _ask(scene_of, monkeypatch, tmp_path, slack):
    """(scene, requests, cause) of a unit whose server reported a window that
    leaves *slack* tokens beyond the stage's budget; None: it reported none,
    and no preflight is run at all."""
    scene = scene_of(monkeypatch, tmp_path)
    if slack is not None:
        _preflight(monkeypatch, scene.role, scene.budget + slack, scene.budget)
    sent, cause = scene.run()
    return scene, sent, cause


# ---------------------------------------------------------------------------
# AND 1: asked once more with more room, once
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", sorted(FULL))
def test_a_cut_off_unit_is_asked_once_more_with_more_room_and_then_no_more(
        unit, monkeypatch, tmp_path):
    _, sent, cause = _ask(FULL[unit], monkeypatch, tmp_path, slack=10 ** 6)
    assert len(sent) == 2, "once as asked, once with more room, never a third"
    assert sent[1] > sent[0]
    assert cause == "cut_off", "cut off again: a hole, with the cause of the cut"


def test_a_window_whose_second_reply_is_whole_is_read_and_no_hole(
        monkeypatch, tmp_path):
    """The case that keeps the more room honest: it is spent on a request that
    then fits, which is the reason for it."""
    scene = _window_scene(monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget + 10 ** 6, scene.budget)
    section = {"title": "A", "content": " ".join(["w"] * 400),
               "segments": [], "pages": [1]}
    client, sent = _replies(
        _answer('{"sections": [{"title": "Cu', "length"),
        _answer('{"sections": [{"_action": "keep", "title": "A*"}]}'))
    got = s4._ask_window([section], client, None)
    assert [s["title"] for s in got] == ["A*"]
    assert [r["max_tokens"] for r in sent] == [1000, 2000]


def test_an_outline_whose_second_reply_is_whole_is_read_and_no_hole(
        monkeypatch, tmp_path):
    scene = _outline_scene(monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget + 10 ** 6, scene.budget)
    section = {"title": "T", "content": "x", "segments": [
        {"kind": "text", "text": "x", "page": 1}]}
    client, sent = _replies(_answer('{"cuts": [{"at": ', "length"),
                            _answer('{"cuts": []}'))
    assert split._ask_cuts(section, s4._make_splitter(client)) == {"cuts": []}
    assert [r["max_tokens"] for r in sent] == [1000, 2000]


# ---------------------------------------------------------------------------
# AND 2: twice what it asked, or as much as the served window leaves, whichever
# is smaller
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", sorted(FULL))
def test_the_room_is_twice_what_was_asked_where_the_window_leaves_that_much(
        unit, monkeypatch, tmp_path):
    scene = FULL[unit](monkeypatch, tmp_path)
    first = scene.run()[0][0]
    _preflight(monkeypatch, scene.role, scene.budget + first, scene.budget)
    sent, _ = scene.run()
    assert sent == [first, 2 * first]


@pytest.mark.parametrize("unit", sorted(FULL))
def test_the_room_is_what_the_window_leaves_where_that_is_less_than_twice(
        unit, monkeypatch, tmp_path):
    """Built to violate "twice": a window that leaves a quarter of the request.
    Twice the room would be a request of budget + asked, over the window."""
    scene = FULL[unit](monkeypatch, tmp_path)
    first = scene.run()[0][0]
    slack = first // 4
    window = scene.budget + slack
    _preflight(monkeypatch, scene.role, window, scene.budget)
    sent, cause = scene.run()
    assert sent == [first, first + slack]
    assert sent[1] < 2 * first
    # and the request the unit was given fits the window it was given it for
    assert scene.budget - first + sent[1] <= window
    assert cause == "cut_off"


@pytest.mark.parametrize("unit", sorted(SMALL))
def test_a_request_that_asked_for_less_than_the_reply_is_doubled_out_of_the_reply_alone(
        unit, monkeypatch, tmp_path):
    """The window leaves nothing beyond the budget, and the request asked for
    300 of the 1000 tokens the budget counts: it is given 600. Built to violate
    a sizing that adds only the slack to what was asked."""
    _, sent, cause = _ask(SMALL[unit], monkeypatch, tmp_path, slack=0)
    assert sent == [300, 600]
    assert cause == "cut_off"


# the rule itself: what it is for every number, not for a unit's
@pytest.mark.parametrize("asked, reply, slack, room", [
    (1000, 1000, 5000, 2000),      # the window leaves more than twice: twice
    (1000, 1000, 1000, 2000),      # exactly twice
    (1000, 1000, 999, 1999),       # a token short of twice: what is left
    (1000, 1000, 250, 1250),
    (1000, 1000, 1, 1001),         # one token of room is room
    (1000, 1000, 0, None),         # none: nothing more to ask for
    (300, 1000, 0, 600),           # asked less than the reply: out of the reply
    (700, 1000, 0, 1000),          # twice would pass the reply: as much as it is
    (1000, 1000, -5, None),        # a window under the budget leaves none
])
def test_the_room_is_the_smaller_of_twice_and_the_reply_plus_what_is_left(
        asked, reply, slack, room, monkeypatch):
    budget = 20000
    llm_preflight._WINDOWS["llm"] = budget + slack
    assert further_room(asked, reply=reply, budget=budget) == room


# ---------------------------------------------------------------------------
# AND 3: the budget is the prompt, the largest input and ONE largest reply
# ---------------------------------------------------------------------------

def test_the_budget_of_stage_four_is_the_prompt_the_largest_input_and_one_reply():
    system = len(RC.system_prompt().split()) * RC.TOKENS_PER_WORD
    largest_input = RC.WINDOW_SIZE * RC.SECTION_MAX_WORDS * RC.TOKENS_PER_WORD
    assert RC.max_request_tokens() == int(
        system + largest_input + RC.largest_reply_tokens())
    assert RC.largest_reply_tokens() == RC.REPLY_TOKENS_CEILING


def test_a_longer_reply_moves_the_budget_of_stage_four_by_that_reply_once(
        monkeypatch):
    before = RC.max_request_tokens()
    monkeypatch.setattr(RC, "REPLY_TOKENS_CEILING", RC.REPLY_TOKENS_CEILING + 700)
    assert RC.max_request_tokens() == before + 700, (
        "a budget with a second reply in it moves by 1400")


def test_the_budget_of_stage_five_is_the_prompt_the_image_and_one_reply():
    prompt = max(len(VC.table_system_prompt().split()),
                 len(VC.figure_system_prompt().split()))
    assert VC.max_request_tokens() == int(
        prompt * VC.TOKENS_PER_WORD + VC.IMAGE_TOKENS + VC.VLM_MAX_TOKENS)


def test_a_longer_reply_moves_the_budget_of_stage_five_by_that_reply_once(
        monkeypatch):
    before = VC.max_request_tokens()
    monkeypatch.setattr(VC, "VLM_MAX_TOKENS", VC.VLM_MAX_TOKENS + 700)
    assert VC.max_request_tokens() == before + 700


def test_the_budget_of_a_page_request_is_the_prompt_the_image_and_one_reply(
        monkeypatch):
    from docpipe import prompts
    from docpipe.preprocessing import page_text_fallback as fb

    real = prompts.load(fb.PAGE_TRANSCRIBE_PROMPT_ID, None)
    words = len(real.text.split())

    def with_room(room):
        monkeypatch.setattr(prompts, "load", lambda *a, **k: NS(
            text=real.text, meta={**real.meta, "max_tokens": room}))
        return fb.page_request_tokens(None)

    assert with_room(4096) == int(words * VC.TOKENS_PER_WORD
                                  + VC.IMAGE_TOKENS + 4096)
    assert with_room(4796) - with_room(4096) == 700, "one reply, not two"


def test_the_page_budget_is_not_the_budget_of_the_visuals_stage():
    """The test below that sizes a page from its own budget could not fail if
    the two were one number."""
    from docpipe.preprocessing.page_text_fallback import page_request_tokens
    assert page_request_tokens(None) != VC.max_request_tokens()


def test_the_command_prints_the_budget_it_checks_its_server_against(
        monkeypatch, capsys, tmp_path):
    for module, command, budget in ((RP, "refinement", RC.max_request_tokens),
                                    (IP, "visuals", VC.max_request_tokens)):
        monkeypatch.setattr(sys, "argv", [command, "--print-context-budget"])
        with pytest.raises(SystemExit) as stopped:
            module.main()
        assert stopped.value.code == 0
        assert int(capsys.readouterr().out.split()[-1]) == budget()


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_no_request_of_any_stage_needs_more_than_the_window_the_owner_serves(
        tmp_path, name):
    """What the commands print is what the server has to be started for, and
    what its preflight checks. The first build printed 44927 tokens for stage 4
    of the profile kwp, over a window of 32768 that stage had always run on."""
    from docpipe.preprocessing.page_text_fallback import page_request_tokens
    printed = {
        "refinement": _budget(_run(tmp_path, "docpipe.refinement",
                                   "--print-context-budget", "--profile", name)),
        "visuals": _budget(_run(tmp_path, "docpipe.visuals",
                                "--print-context-budget", "--profile", name)),
        "page transcription": page_request_tokens(load_profile(name)),
    }
    assert {stage: tokens for stage, tokens in printed.items()
            if tokens > SERVED_WINDOW} == {}, (
        f"tokens per request that do not fit {SERVED_WINDOW} tokens: {printed}")


# ---------------------------------------------------------------------------
# The preflight of each stage takes a server that serves exactly its budget
# ---------------------------------------------------------------------------

def _server(monkeypatch, window):
    """A server that serves the model "m" with *window* and takes every
    request, of one's own."""
    client = base.facade(
        lambda **kw: base.reply("ok", "length"),
        models=lambda: NS(data=[NS(id="m", max_model_len=window)]))
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VLM_PROVIDER", raising=False)


def _command(monkeypatch, tmp_path, module, name, model_name):
    started: list = []
    monkeypatch.setattr(module, model_name, "m")
    monkeypatch.setattr(module, "run_batch",
                        lambda root, **kw: started.append(root) or {})
    monkeypatch.setattr(sys, "argv", [name, str(tmp_path), "--batch"])
    return started


def _exit(main):
    with pytest.raises(SystemExit) as stopped:
        main()
    return stopped.value.code


def test_stage_four_takes_a_server_that_serves_exactly_its_budget(
        monkeypatch, tmp_path):
    started = _command(monkeypatch, tmp_path, RP, "refinement", "LLM_MODEL")
    _server(monkeypatch, RC.max_request_tokens())
    assert _exit(RP.main) == 0 and len(started) == 1


def test_stage_four_refuses_a_server_one_token_under_its_budget(
        monkeypatch, tmp_path, caplog):
    started = _command(monkeypatch, tmp_path, RP, "refinement", "LLM_MODEL")
    _server(monkeypatch, RC.max_request_tokens() - 1)
    with caplog.at_level(logging.ERROR):
        assert _exit(RP.main) == 1
    assert started == [] and str(RC.max_request_tokens()) in caplog.text


def test_stage_five_takes_a_server_that_serves_exactly_its_budget(
        monkeypatch, tmp_path):
    started = _command(monkeypatch, tmp_path, IP, "visuals", "VLM_MODEL")
    _server(monkeypatch, VC.max_request_tokens())
    assert _exit(IP.main) == 0 and len(started) == 1


def test_stage_five_refuses_a_server_one_token_under_its_budget(
        monkeypatch, tmp_path):
    started = _command(monkeypatch, tmp_path, IP, "visuals", "VLM_MODEL")
    _server(monkeypatch, VC.max_request_tokens() - 1)
    assert _exit(IP.main) == 1 and started == []


def test_stage_four_takes_the_window_the_owner_serves(monkeypatch, tmp_path):
    """The case the doubled budget broke: the server the pipeline has always
    run on, 32768 tokens, refused by a budget of 44927."""
    started = _command(monkeypatch, tmp_path, RP, "refinement", "LLM_MODEL")
    _server(monkeypatch, SERVED_WINDOW)
    assert _exit(RP.main) == 0 and len(started) == 1


def test_stage_five_takes_the_window_the_owner_serves(monkeypatch, tmp_path):
    started = _command(monkeypatch, tmp_path, IP, "visuals", "VLM_MODEL")
    _server(monkeypatch, SERVED_WINDOW)
    assert _exit(IP.main) == 0 and len(started) == 1


def _page_server(monkeypatch, window):
    from docpipe.visuals import config as visuals_config

    monkeypatch.setattr(visuals_config, "VLM_MODEL", "m")
    _server(monkeypatch, window)


def test_the_page_transcription_takes_a_server_that_serves_exactly_its_budget(
        monkeypatch):
    from docpipe.preprocessing import pipeline as PL
    from docpipe.preprocessing.page_text_fallback import page_request_tokens

    _page_server(monkeypatch, page_request_tokens(None))
    PL._assert_page_server(None)            # does not raise


def test_the_page_transcription_takes_the_window_the_owner_serves(monkeypatch):
    from docpipe.preprocessing import pipeline as PL

    _page_server(monkeypatch, SERVED_WINDOW)
    PL._assert_page_server(None)            # does not raise


def test_the_page_transcription_refuses_a_server_one_token_under_its_budget(
        monkeypatch):
    from docpipe.preprocessing import pipeline as PL
    from docpipe.preprocessing.page_text_fallback import page_request_tokens

    _page_server(monkeypatch, page_request_tokens(None) - 1)
    with pytest.raises(PreflightError) as refused:
        PL._assert_page_server(None)
    assert str(page_request_tokens(None)) in str(refused.value)


# ---------------------------------------------------------------------------
# AND 4: where the window leaves no more room than the request had, a hole
# at once and no second request
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", sorted(FULL))
def test_a_window_that_leaves_no_more_room_makes_the_unit_a_hole_at_once(
        unit, monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        scene, sent, cause = _ask(FULL[unit], monkeypatch, tmp_path, slack=0)
    assert len(sent) == 1, "no second request is sent"
    assert cause == "cut_off"
    window = scene.budget
    said = [r.getMessage() for r in caplog.records
            if "no more room" in r.getMessage()]
    assert any(f"served window of {window} tokens" in line for line in said), (
        "the line says the served window, in tokens", said)


@pytest.mark.parametrize("unit", sorted(FULL))
def test_one_token_of_room_is_room_and_the_second_request_is_sent(
        unit, monkeypatch, tmp_path):
    """The other side of the boundary above, built so that a unit that gives up
    one token early fails."""
    _, sent, cause = _ask(FULL[unit], monkeypatch, tmp_path, slack=1)
    assert len(sent) == 2 and sent[1] == sent[0] + 1


def test_the_hole_of_a_lone_window_keeps_the_size_of_the_request_that_was_cut(
        monkeypatch, tmp_path):
    scene = _window_scene(monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget, scene.budget)
    section = {"title": "A", "content": " ".join(["w"] * 400),
               "segments": [], "pages": [1]}
    client, sent = _cut_server('{"sections": [{"title": "Cu')
    got = s4._ask_window([section], client, None)
    assert got == Hole("cut_off", f"{sent[0]['max_tokens']} tokens")


def test_a_window_of_two_sections_is_asked_in_halves_whatever_the_window_leaves(
        monkeypatch, tmp_path):
    """The halves ask for less, so they do not need room: the halving of a
    window with more than one section stays as it was."""
    scene = _window_scene(monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget, scene.budget)    # none left
    window = [{"title": t, "content": f"text of {t}", "segments": [],
               "pages": [1]} for t in ("A", "B")]
    client, sent = _replies(
        _answer('{"sections": [{"title": "Cu', "length"),
        _answer('{"sections": [{"_action": "keep", "title": "A*"}]}'),
        _answer('{"sections": [{"_action": "keep", "title": "B*"}]}'))
    got = s4._ask_window(window, client, None)
    assert [s["title"] for s in got] == ["A*", "B*"] and len(sent) == 3


def test_an_outline_of_two_segments_is_asked_in_halves_whatever_the_window_leaves(
        monkeypatch, tmp_path):
    scene = _outline_scene(monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget, scene.budget)
    section = {"title": "T", "content": "x y", "segments": [
        {"kind": "text", "text": "x", "page": 1},
        {"kind": "text", "text": "y", "page": 1}]}
    client, sent = _replies(_answer('{"cuts": [{"at": ', "length"),
                            _answer('{"cuts": []}'))
    assert split._ask_cuts(section, s4._make_splitter(client)) == {
        "first_title": None, "cuts": [{"at": 1, "title": None}]}
    assert len(sent) == 3


# ---------------------------------------------------------------------------
# AND 5: where the served window is not known, the room is twice
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", sorted(EVERY))
def test_a_caller_that_asked_no_server_gives_twice_the_room(
        unit, monkeypatch, tmp_path):
    _, sent, cause = _ask(EVERY[unit], monkeypatch, tmp_path, slack=None)
    assert sent == [sent[0], 2 * sent[0]] and cause == "cut_off"


@pytest.mark.parametrize("unit", sorted(EVERY))
def test_a_server_that_reports_no_window_gives_twice_the_room(
        unit, monkeypatch, tmp_path):
    scene = EVERY[unit](monkeypatch, tmp_path)
    assert _preflight(monkeypatch, scene.role, None, scene.budget) is None
    sent, _ = scene.run()
    assert sent == [sent[0], 2 * sent[0]]


@pytest.mark.parametrize("unit", sorted(EVERY))
def test_a_hosted_model_whose_window_is_its_own_gives_twice_the_room(
        unit, monkeypatch, tmp_path):
    scene = EVERY[unit](monkeypatch, tmp_path)
    assert _preflight(monkeypatch, scene.role, None, scene.budget,
                      hosted=True) is None
    sent, _ = scene.run()
    assert sent == [sent[0], 2 * sent[0]]


@pytest.mark.parametrize("unit", sorted(FULL))
def test_a_hosted_model_that_reports_its_window_is_held_to_it(
        unit, monkeypatch, tmp_path):
    """The case that keeps the three above honest: a hosted API is no special
    case, it is a server whose window is known or not."""
    scene = FULL[unit](monkeypatch, tmp_path)
    _preflight(monkeypatch, scene.role, scene.budget, scene.budget, hosted=True)
    sent, cause = scene.run()
    assert len(sent) == 1 and cause == "cut_off"


def test_the_rule_gives_twice_where_the_stage_states_no_budget(monkeypatch):
    llm_preflight._WINDOWS["vlm"] = 20000
    assert further_room(500, reply=500, budget=None, role="vlm") == 1000
    assert further_room(500, reply=500, budget=20000, role="vlm") is None


# ---------------------------------------------------------------------------
# The window reaches the unit from the preflight: per role, from the real
# preflight of each stage, and without asking the server again
# ---------------------------------------------------------------------------

def test_the_window_a_server_reports_is_kept_for_the_role_that_asked(monkeypatch):
    assert served_window("llm") is None, "nothing was asked yet"
    assert _preflight(monkeypatch, "llm", 30000, 1000) == 30000
    assert served_window("llm") == 30000
    assert served_window("vlm") is None, "the other role's server is not it"


def test_each_role_keeps_the_window_of_its_own_server(monkeypatch):
    _preflight(monkeypatch, "llm", 30000, 1000)
    _preflight(monkeypatch, "vlm", 20000, 1000)
    assert (served_window("llm"), served_window("vlm")) == (30000, 20000)


def test_a_later_preflight_that_finds_no_window_replaces_the_one_found_before(
        monkeypatch):
    _preflight(monkeypatch, "llm", 30000, 1000)
    _preflight(monkeypatch, "llm", None, 1000)
    assert served_window("llm") is None


def test_a_server_that_was_refused_leaves_no_window(monkeypatch):
    with pytest.raises(PreflightError):
        _preflight(monkeypatch, "llm", 500, 1000)
    assert served_window("llm") is None


def test_a_hosted_api_that_reports_a_window_has_it_kept(monkeypatch):
    _preflight(monkeypatch, "llm", 30000, 1000, hosted=True)
    assert served_window("llm") == 30000


def test_a_replay_keeps_the_window_of_the_recorded_run(monkeypatch, tmp_path):
    import json

    from docpipe.providers import cassette
    path = tmp_path / "cassette.jsonl"
    path.write_text(json.dumps({"kind": cassette.HEADER, "model": "m",
                                "max_model_len": 20000}) + "\n",
                    encoding="utf-8")
    monkeypatch.setenv(cassette.REPLAY_ENV, str(path))
    assert llm_preflight.assert_serving(
        "http://x/v1", "EMPTY", "m", 1000, role="llm") == 20000
    assert served_window("llm") == 20000


def test_the_window_is_read_where_the_unit_is_sized_without_asking_the_server(
        monkeypatch):
    _preflight(monkeypatch, "llm", 30000, 20000)

    def down(role, **kw):
        raise AssertionError("the server was asked a second time")

    monkeypatch.setattr(llm_preflight.providers, "client", down)
    assert served_window("llm") == 30000
    assert further_room(1000, reply=1000, budget=20000) == 2000


def test_a_window_one_test_reported_is_not_there_in_the_next_one(monkeypatch):
    """The two tests are a pair, in this order: the first leaves a window in
    the module that holds it, the second finds none. Without the fixture that
    clears it after every test (tests/conftest.py) the second fails."""
    llm_preflight._WINDOWS["llm"] = 12345
    assert served_window("llm") == 12345


def test_the_window_of_the_test_before_is_gone():
    assert served_window("llm") is None and llm_preflight._WINDOWS == {}


@pytest.mark.parametrize("command", ["refinement", "visuals"])
def test_the_command_hands_the_window_it_found_to_the_units_it_asks(
        command, monkeypatch, tmp_path):
    """Through the command's own preflight and not a stand-in: the window the
    server reports is what leaves the unit its room."""
    if command == "refinement":
        scene = _window_scene(monkeypatch, tmp_path)
        _command(monkeypatch, tmp_path, RP, "refinement", "LLM_MODEL")
        main = RP.main
    else:
        scene = _figure_scene(monkeypatch, tmp_path)
        _command(monkeypatch, tmp_path, IP, "visuals", "VLM_MODEL")
        main = IP.main
    _server(monkeypatch, scene.budget + 40)
    assert _exit(main) == 0
    sent, _ = scene.run()
    assert sent[1] == sent[0] + 40, (
        "the window of the server minus the budget, on top of the reply")


def test_the_page_check_hands_the_window_it_found_to_the_pages(
        monkeypatch, tmp_path):
    from docpipe.preprocessing import pipeline as PL

    scene = _page_scene(monkeypatch, tmp_path)
    # the page is sized from its own budget: the visuals stage's is another
    # number (see the test of the two budgets above), which would leave
    # another room
    _page_server(monkeypatch, scene.budget + 40)
    PL._assert_page_server(None)
    sent, _ = scene.run()
    assert sent[1] == sent[0] + 40


# ---------------------------------------------------------------------------
# The line of the further attempt says what it was asked with and before
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", sorted(FULL))
def test_the_log_of_the_further_attempt_says_both_sizes_in_tokens(
        unit, monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _, sent, _ = _ask(FULL[unit], monkeypatch, tmp_path, slack=10 ** 6)
    said = [r.getMessage() for r in caplog.records
            if "again" in r.getMessage()]
    # the one it is asked with now, and the one it was asked with before: a
    # line that names both and swaps them says the opposite
    assert any(f"with {sent[1]} tokens ({sent[0]} tokens before)" in line
               for line in said), said


# ---------------------------------------------------------------------------
# What the output contract says of a cut-off item
# ---------------------------------------------------------------------------

def test_the_schema_does_not_say_a_cut_off_item_had_twice_the_room():
    """Twice is what an item gets where the window leaves that much. Where it
    leaves less, or none, the item is a hole after a smaller request or none,
    and the description of its cause has to allow for both."""
    import json

    from docpipe.artifacts import SCHEMA_DIR
    schema = json.loads((SCHEMA_DIR / "visuals.schema.json")
                        .read_text(encoding="utf-8"))
    said = schema["$defs"]["vlm_why"]["description"]
    assert "twice" not in said and "window" in said


# ---------------------------------------------------------------------------
# The three call sites of the visuals stage ask with its budget
# ---------------------------------------------------------------------------

def test_every_request_of_the_visuals_stage_carries_the_budget_of_that_stage(
        monkeypatch, tmp_path):
    seen: list = []

    def spy(*args, **kwargs):
        seen.append(kwargs.get("budget"))
        return ({"markdown": "| a |", "caption": ""} if len(seen) == 1
                else Hole("cut_off"))

    monkeypatch.setattr(P, "call_vision", spy)
    # a table whose first reading fails the quality gate is read once more
    P.process_table(_image(tmp_path), {"title": "S"}, tmp_path, None,
                    ProcessingStats(),
                    source_text="alpha beta gamma delta epsilon zeta eta theta "
                                "iota kappa")
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: (
        seen.append(k.get("budget")) or Hole("cut_off")))
    P.process_figure(_image(tmp_path), {"title": "S"}, tmp_path, None,
                     ProcessingStats())
    assert seen == [VC.max_request_tokens()] * 3
