"""Stages 4 and 5 cut nothing of what they show a model (owner decision
2026-11-17: "Nichts kürzen, einfach ggf. clever aufteilen").

Stage 5 (tables and figures):
- The request of a table or a figure shows the whole text of its section.
- The request of a table that may continue the table before it shows that
  table's whole head and the whole text between the two.
- The text between two tables is kept whole by `continuation.links`.
- The stage's budget counts the longest text a request of the run shows, not
  a fixed number of characters, and the estimate counts the whole section.

Stage 4 (refinement):
- The section before a window is shown to it whole.
- A window whose request with that context does not fit the served window
  takes fewer sections: it is asked as halves, each section once.
- A failed answer goes back whole in the re-ask; where that does not fit the
  served window the request starts anew with the cause named.
- The outline of a section shows each block whole; one that does not fit the
  served window is outlined in parts at block boundaries, each part with the
  title and the segment numbers it has in the section.

Each promise has a case that breaks it by construction: a text far longer
than any former limit, whose every word must come through."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import estimate, llm_preflight, rules
from docpipe import window as windows
from docpipe.reading import Hole
from docpipe.refinement import config as rconfig
from docpipe.refinement import refine, split
from docpipe.visuals import config as vconfig
from docpipe.visuals import continuation, process, vision
from docpipe.visuals.models import ProcessingStats

LONG = " ".join(f"w{i}" for i in range(6000))          # far past 800 characters


# -- stage 5 ------------------------------------------------------------------

TABLE_USER = ("{section_title}|{page_number}|{existing_caption}|"
              "{section_content}|{caption_instruction}")
FIGURE_USER = TABLE_USER


@pytest.fixture
def prompts_stub(monkeypatch):
    texts = {"table_system_prompt": "table system words",
             "table_user_prompt": TABLE_USER,
             "table_continued_prompt": "BEFORE {previous_caption}|"
                                       "{previous_head}|{between}",
             "figure_system_prompt": "figure system",
             "figure_user_prompt": FIGURE_USER,
             "caption_keep_instruction": "keep",
             "caption_generate_table_instruction": "make table",
             "caption_generate_figure_instruction": "make figure"}
    for name, text in texts.items():
        for module in (process, vconfig):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, lambda t=text: t)


@pytest.fixture
def asked(monkeypatch):
    """What call_vision was sent: user prompt and budget of each call; it
    answers with a hole, which ends the request after it was built."""
    calls = []

    def call_vision(client, system, user, path, **kwargs):
        calls.append({"user": user, "budget": kwargs.get("budget")})
        return Hole("refused")
    monkeypatch.setattr(process, "call_vision", call_vision)
    return calls


def image(tmp_path: Path) -> Path:
    (tmp_path / "t.png").write_bytes(b"x")
    return tmp_path


def test_a_table_request_shows_the_whole_section_text(
        tmp_path, prompts_stub, asked):
    process.process_table({"id": "t1", "path": "t.png"},
                          {"title": "S", "content": LONG}, image(tmp_path),
                          None, ProcessingStats())
    assert LONG in asked[0]["user"]          # every word, the last one too


def test_a_figure_request_shows_the_whole_section_text(
        tmp_path, prompts_stub, asked):
    process.process_figure({"id": "f1", "path": "t.png"},
                           {"title": "S", "content": LONG}, image(tmp_path),
                           None, ProcessingStats())
    assert LONG in asked[0]["user"]


def test_a_continuing_table_is_shown_its_whole_head_and_whole_between(
        tmp_path, prompts_stub, asked):
    head = "| " + " | ".join(f"col{i}" for i in range(900)) + " |"
    process.process_table(
        {"id": "t2", "path": "t.png"}, {"title": "S", "content": "short"},
        image(tmp_path), None, ProcessingStats(),
        before={"after": "t1", "caption": "c", "head": head, "between": LONG})
    assert head in asked[0]["user"] and LONG in asked[0]["user"]


def test_the_text_between_two_tables_is_kept_whole():
    sections = [{"page_number": 1, "tables": [{"id": "a", "page_number": 1},
                                              {"id": "b", "page_number": 1}],
                 "segments": [{"kind": "table", "page": 1, "ref": "a"},
                              {"kind": "text", "page": 1, "text": LONG},
                              {"kind": "table", "page": 1, "ref": "b"}]}]
    assert continuation.links(sections)["b"]["between"] == LONG


def test_the_budget_of_a_request_follows_the_text_it_shows(prompts_stub):
    base = vconfig.max_request_tokens(0)
    more = vconfig.max_request_tokens(vconfig.shown_bytes(LONG, "h", "b"))
    assert more - base >= len(LONG.encode("utf-8"))
    assert not hasattr(vconfig, "SHOWN_CHARS")
    assert not hasattr(vconfig, "CHARS_PER_TOKEN")


def test_a_request_is_budgeted_with_its_own_whole_section(
        tmp_path, prompts_stub, asked):
    process.process_table({"id": "t1", "path": "t.png"},
                          {"title": "S", "content": LONG}, image(tmp_path),
                          None, ProcessingStats())
    process.process_table({"id": "t1", "path": "t.png"},
                          {"title": "S", "content": "short"}, image(tmp_path),
                          None, ProcessingStats())
    assert asked[0]["budget"] - asked[1]["budget"] \
        >= len(LONG.encode("utf-8")) - 5


def test_the_budget_of_the_run_counts_the_longest_text_of_its_documents(
        tmp_path, prompts_stub):
    for name, text in (("d1", "short"), ("d2", LONG), ("d3", "middle " * 50)):
        folder = tmp_path / name
        (folder / vconfig.SECTIONS_JSON).parent.mkdir(parents=True)
        (folder / vconfig.SECTIONS_JSON).write_text(
            json.dumps({"sections": [{"title": "S", "content": text}]}),
            encoding="utf-8")
    assert vconfig.longest_in(tmp_path) == len(LONG)
    assert vconfig.longest_in(tmp_path / "nothing") == 0


def test_the_longest_text_counts_between_and_head_too():
    sections = [{"page_number": 1, "content": "abc",
                 "tables": [{"id": "a", "page_number": 1,
                             "source_text": "x" * 40},
                            {"id": "b", "page_number": 1}],
                 "segments": [{"kind": "table", "page": 1, "ref": "a"},
                              {"kind": "text", "page": 1, "text": "y" * 70},
                              {"kind": "table", "page": 1, "ref": "b"}]}]
    assert vconfig.longest_shown(sections) == 3 + 70 + 40


def test_the_estimate_counts_the_whole_section_text(tmp_path, monkeypatch,
                                                    prompts_stub):
    def estimated(text: str) -> int:
        folder = tmp_path / ("doc" + str(len(text)))
        (folder / vconfig.SECTIONS_JSON).parent.mkdir(parents=True)
        (folder / "t.png").write_bytes(b"x")
        (folder / vconfig.SECTIONS_JSON).write_text(json.dumps({"sections": [
            {"title": "S", "content": text,
             "tables": [{"id": "t", "path": "t.png"}]}]}), encoding="utf-8")
        where = estimate.Where(SimpleNamespace(name="p"), tmp_path, folder.parent,
                               tmp_path / "db", None, {}, {})
        return estimate.visuals(where).tokens_in
    only_short = estimated("word " * 10)
    with_long = estimated("word " * 5000)
    # One document of 10 words, then two (10 and 5000 words): beside the
    # fixed cost of each table, the 4,990 words more at 3 tokens a word.
    assert with_long - 2 * only_short == 4990 * 3


# -- stage 4 ------------------------------------------------------------------

def test_the_section_before_a_window_is_shown_to_it_whole():
    content = LONG + " END"
    text = refine._user_content([{"title": "A", "content": "x"}],
                                {"title": "Prev", "content": content})
    assert json.dumps(content) in text
    again = refine._user_content([{"title": "A", "content": "x"}],
                                 {"title": "Prev", "content": ["a", "b"]})
    assert "a b" in again                    # a list of entries, joined whole


class Server:
    """The servers of the stages, stubbed: the window they report, the
    tokenizer they count with and the frame their template makes."""

    def __init__(self, monkeypatch):
        self.limit = None
        self.count = lambda text: len(text.encode("utf-8"))
        self.per_message = 5
        self.counted = []
        self.frames = []
        self.counters_made = 0
        llm_preflight._STAGE_WINDOWS.clear()
        monkeypatch.setattr(llm_preflight, "served_window",
                            lambda role="llm": self.limit)
        monkeypatch.setattr(refine, "served_window",
                            lambda role="llm": self.limit)
        monkeypatch.setattr(windows, "server_counter", self._counter)
        monkeypatch.setattr(windows, "server_frame", self._frame)

    def _counter(self, base_url, model, api_key="", **_):
        self.counters_made += 1

        def count(text):
            self.counted.append(text)
            return self.count(text)
        return count

    def _frame(self, base_url, model, messages, api_key="", **_):
        self.frames.append(messages)
        return self.per_message * len(messages)


@pytest.fixture
def server(monkeypatch):
    stub = Server(monkeypatch)
    yield stub
    llm_preflight._STAGE_WINDOWS.clear()


@pytest.fixture
def window_of(monkeypatch, server):
    def set_window(tokens):
        server.limit = tokens
    monkeypatch.setattr(refine, "system_prompt", lambda: "sys")
    monkeypatch.setattr(refine, "reply_tokens", lambda words: 100)
    return set_window


def sections(n, words):
    return [{"title": f"S{i}", "content": f"s{i} " * words} for i in range(n)]


def test_a_window_that_does_not_fit_with_its_context_takes_fewer_sections(
        monkeypatch, window_of):
    calls = []

    def call(window, client, prev_context=None, again=False):
        calls.append(([s["title"] for s in window],
                      (prev_context or {}).get("title")))
        return [dict(s, _action="keep") for s in window]
    monkeypatch.setattr(refine, "_call_llm", call)
    window = sections(4, 400)
    previous = {"title": "PREV", "content": "p " * 400}

    window_of(100000)                                     # fits: one request
    got = refine._ask_window(window, None, previous)
    assert calls == [(["S0", "S1", "S2", "S3"], "PREV")] and len(got) == 4

    calls.clear()
    window_of(2500)             # 4 x 400 words of 3 bytes: too big
    got = refine._ask_window(window, None, previous)
    assert len(calls) > 1
    asked_titles = [t for names, _ctx in calls for t in names]
    assert asked_titles == ["S0", "S1", "S2", "S3"]       # each section once
    assert [s["title"] for s in got] == asked_titles
    assert calls[1][1] == calls[0][0][-1]      # the second part's context


def test_a_failed_answer_goes_back_whole(monkeypatch, window_of):
    window_of(None)
    answer = '{"sections": [' + LONG + " MIDDLE " + LONG
    base = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "ask"}]
    messages = refine._reask(base, answer, "It broke.", "syntax", 100)
    assert messages[:2] == base
    assert messages[2] == {"role": "assistant", "content": answer}
    assert messages[3]["content"] == "It broke."
    assert not hasattr(refine, "_echo")


def test_a_failed_answer_that_does_not_fit_starts_the_request_anew(
        monkeypatch, window_of):
    window_of(3000)
    answer = LONG                                    # 6000 words: no room
    base = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "ask"}]
    # The correction quotes the whole reply, as the sentence of a syntax
    # error does: the request anew shows neither, only the cause.
    said = f"Your JSON breaks at character 9. Your whole reply: {answer!r}."
    messages = refine._reask(base, answer, said, "syntax", 100)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"].startswith("ask")
    assert "(syntax)" in messages[1]["content"]
    assert LONG not in messages[1]["content"]
    assert said not in messages[1]["content"]


def test_the_budget_counts_the_section_before_the_window(monkeypatch):
    monkeypatch.setattr(rconfig, "system_prompt", lambda: "")
    monkeypatch.setattr(rconfig, "largest_reply_tokens", lambda: 0)
    assert rconfig.max_request_tokens() == int(
        (rules.get("refine_window_sections") + 1) * rules.get("section_max_words")
        * rules.get("tokens_per_word"))


def segments_of(n, words):
    return [{"kind": "text", "page": i + 1,
             "text": " ".join(f"b{i}w{k}" for k in range(words))}
            for i in range(n)]


def test_the_outline_shows_each_block_whole():
    section = {"segments": segments_of(3, 300)}
    lines = split.outline(section).splitlines()
    assert len(lines) == 3
    assert lines[1].split()[-1] == "b1w299"        # the last word of a block
    assert "[300 words]" in lines[1]
    assert not hasattr(rconfig, "SECTION_OUTLINE_WORDS")


@pytest.fixture
def splitting(monkeypatch, server):
    monkeypatch.setattr(split.prompts, "text", lambda *a, **k: "PROMPT")
    monkeypatch.setattr(split, "split_max_tokens", lambda: 10)

    def window(tokens):
        server.limit = tokens
    return window


def test_an_outline_that_does_not_fit_is_asked_in_parts_with_global_numbers(
        splitting):
    section = {"title": "TITLE", "segments": segments_of(8, 100)}
    requests = []

    def ask(system, user, again=False):
        requests.append(user)
        numbers = [int(line.split()[0]) for line in
                   user.split("OUTLINE:\n")[1].splitlines()]
        return {"first_title": "first", "cuts": [
            {"at": numbers[len(numbers) // 2], "title": f"at {numbers[0]}"}]
            if len(numbers) > 1 else []}

    splitting(100000)                                    # fits: one request
    whole = split._ask_range(section, ask, 0, 8)
    assert len(requests) == 1 and whole["cuts"][0]["at"] == 4

    requests.clear()
    splitting(1000)             # 800 words of 6 bytes: too big
    parts = split._ask_range(section, ask, 0, 8)
    assert len(requests) > 1
    seen = []
    for user in requests:
        assert user.startswith("TITLE: TITLE")
        seen += [int(line.split()[0]) for line in
                 user.split("OUTLINE:\n")[1].splitlines()]
        assert all(f"b{n}w99" in user for n in seen[-1:])   # blocks whole
    assert seen == list(range(8))                        # each block once
    assert all(0 < c["at"] < 8 for c in parts["cuts"])   # section numbers
    assert 4 in [c["at"] for c in parts["cuts"]]         # the cut between


# -- the window judged is the window sent --------------------------------------

# Digits cost a token each, so seven-digit numbers cost far more than the
# three tokens a word the stages used to count with.
DIGITS = "1234567 " * 200


def digit_tokens(text):
    return sum(1 for c in text if c.isdigit())


def message(text, role="user"):
    return {"role": role, "content": text}


def test_a_digit_heavy_window_that_words_would_pass_is_not_fitted(
        server, window_of):
    window_of(1000)
    server.count = digit_tokens            # 1,400 tokens; 200 words x 3 = 600
    assert not refine._fits_window(
        [message("sys", "system"), message(DIGITS)], 100)
    assert refine._fits_window(
        [message("sys", "system"), message("1234567 " * 20)], 100)


def test_a_digit_heavy_outline_that_words_would_pass_is_not_asked_whole(
        server, splitting):
    splitting(1000)
    server.count = digit_tokens
    section = {"title": "T", "segments": [
        {"kind": "text", "page": 1, "text": DIGITS}]}
    assert not split._outline_fits(section, 0, 1)
    short = {"title": "T", "segments": [
        {"kind": "text", "page": 1, "text": "1234567 " * 20}]}
    assert split._outline_fits(short, 0, 1)


def test_a_digit_heavy_vision_request_that_words_would_pass_is_not_fitted(
        server):
    server.limit = 6000
    server.count = digit_tokens
    picture = {"type": "image_url", "image_url": {"url": "data:image/png"}}

    def request(text):
        return [message("sys", "system"),
                {"role": "user", "content": [
                    {"type": "text", "text": text}, picture]}]
    # 300 words x 3 + one picture of 4,096 + a reply of 100 = 5,096 <= 6,000
    # at the old count; 2,100 digit tokens do not fit beside the picture.
    assert not vision._fits_served(100)(request("1234567 " * 300))
    assert vision._fits_served(100)(request("1234567 " * 20))


def test_each_picture_of_a_vision_request_costs_its_tokens(server):
    server.limit = 9000
    picture = {"type": "image_url", "image_url": {"url": "data:image/png"}}

    def request(pictures):
        return [{"role": "user", "content": [
            {"type": "text", "text": "x" * 1000}] + [picture] * pictures}]
    fits = vision._fits_served(100)
    assert fits(request(1)) and not fits(request(2))


def test_a_text_whose_bytes_fit_is_let_through_without_being_counted(
        server, window_of):
    window_of(1000)
    assert refine._fits_window(
        [message("sys", "system"), message("word " * 100)], 100)
    assert server.counted == []


def test_a_text_whose_bytes_do_not_fit_is_counted_by_the_server(
        server, window_of):
    window_of(1000)
    server.count = lambda text: len(text.split())     # a token a word
    text = "word " * 400                               # 2,000 bytes, 400 tokens
    assert refine._fits_window([message(text)], 100)
    assert server.counted == [text]
    server.count = len                                # a token a character
    assert not refine._fits_window([message(text + "x")], 100)


def test_the_frame_is_the_template_of_the_messages_sent(server, window_of):
    window_of(1000)
    server.per_message = 100
    two = [message("", "system"), message("x" * 700)]
    four = two + [message("", "assistant"), message("")]
    assert refine._fits_window(two, 0)             # 700 + 200 <= 1000
    assert not refine._fits_window(four, 0)        # 700 + 400 > 1000
    shape = server.frames[-1]
    assert [m["role"] for m in shape] == ["system", "user", "assistant",
                                         "user"]
    assert all(m["content"] == "" for m in shape)  # no text goes to the frame


def test_the_reply_asked_for_is_taken_off_the_window(server, window_of):
    window_of(1000)
    messages = [message("x" * 500)]
    assert refine._fits_window(messages, 100)
    assert not refine._fits_window(messages, 600)


def test_where_no_window_is_known_the_request_fits_and_nothing_is_asked(
        server, window_of):
    window_of(None)
    assert refine._fits_window([message(DIGITS * 100)], 10 ** 6)
    section = {"segments": [{"kind": "text", "page": 1, "text": DIGITS}]}
    assert split._outline_fits(section, 0, 1)
    assert vision._fits_served(10 ** 6)([message(DIGITS)])
    assert server.counters_made == 0 and server.frames == []


def test_where_the_server_counts_nothing_bytes_decide(monkeypatch, server,
                                                      window_of):
    window_of(1000)
    monkeypatch.setattr(windows, "server_counter", lambda *a, **k: None)
    monkeypatch.setattr(windows, "server_frame", lambda *a, **k: None)
    assert refine._fits_window([message("x" * 800)], 100)
    assert not refine._fits_window([message("x" * 1000)], 100)


def test_the_window_of_a_server_is_built_once_for_all_threads(server,
                                                              window_of):
    from concurrent.futures import ThreadPoolExecutor
    window_of(1000)
    # 2,000 bytes do not fit, the server counts 400 tokens: counted, fits
    server.count = lambda text: len(text.split())
    messages = [message("word " * 400)]
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda _i: refine._fits_window(messages, 10),
                            range(40)))
    assert all(got) and server.counters_made == 1


def test_the_budget_of_a_shown_text_counts_its_bytes(prompts_stub):
    german = "ä" * 1000                  # 1,000 characters, 2,000 bytes
    assert vconfig.shown_bytes(german, "ä", "") == 2002
    assert vconfig.longest_shown([{"content": german}]) == 2000
    assert (vconfig.max_request_tokens(2000)
            - vconfig.max_request_tokens(0)) == 2000
