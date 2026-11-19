"""The decisions of stage 5 (tables and figures) are rules, with today's value as
their default (owner request 2026-11-19, point A1 of the review of that day:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard").

The promises, each with a case that breaks it by construction:

1. Every rule of stage 5 has a default in the default profile's rules.json that
   the rules take, a title and a help; a value out of its bounds is refused.
2. A vision request is asked as often, at the temperature, with the reply room
   and with the penalty for repetition of the rules, where the caller names none
   AND a caller that names one keeps it.
3. A table is asked at the temperature of the rule; where it fails the check it
   is asked again as often as the rule says, at the temperature and penalty of
   the rule, with the prompt file of the retry hint after the request, AND
   with 0 rereads it is asked once.
4. The check judges by the rules: the coverage, the repeated rows, the least
   text to measure, the shortest words, and the overlap and known words that
   make a PDF text unreadable.
5. A failed table has its stuttered rows collapsed while the rule is on AND
   keeps them while it is off; a table cut off with the most room is read in
   strips while the rule is on AND has no content, with the cause, while it
   is off.
6. The strips are cut by the rules: the contrast of writing, the specks of a
   blank row, the tilt of a rule.
7. A request shows the words of the rule where the section title, a caption,
   the head before or the text between is missing; a piece between two tables
   is written with the words of the rule.
8. A table may continue a table that began as many pages before as the rule
   says, and no more.
9. The two sentences that stood in the code are prompt files, byte for byte
   what the code sent, and the stage records the retry hint among its prompts.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from docpipe import prompts, providers, rules
from docpipe.reading import Hole
from docpipe.ruleset.stage_visuals import RULES
from docpipe.visuals import config, continuation, process, qa, replies, strips, vision
from docpipe.visuals.models import ProcessingStats

HINT = ("\n\nIMPORTANT: A previous attempt was incomplete or repeated rows. Read "
        "the table again carefully, row by row, and reproduce EVERY row exactly "
        "once — do not omit any row and do not repeat any row.")


def png_bytes(image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


# -- 1. the rules ---------------------------------------------------------------

def test_every_rule_has_a_default_a_title_and_a_help():
    defaults = rules.default()
    assert len(RULES) == 24
    for one in RULES:
        assert one.tab == "stages" and one.group == "Stage 5: tables and figures"
        assert one.title and one.help and one.where
        assert rules.problem(one.name, defaults[one.name]) is None, one.name


def test_a_value_out_of_its_bounds_is_refused():
    assert rules.problem("table_min_coverage", 1.5)
    assert rules.problem("vision_max_attempts", 0)
    assert rules.problem("strip_ink_contrast", 300)
    assert rules.problem("table_continuation_page_gap", 6)
    assert rules.problem("read_cut_tables_in_strips", "yes")
    assert rules.problem("request_blank_words", {"caption": 3})
    assert rules.problem("vision_retry_penalties", {"second_attempt": "1.1"})


def test_the_defaults_are_the_values_the_code_held():
    defaults = rules.default()
    assert [defaults[n] for n in (
        "vision_max_attempts", "figure_temperature", "table_temperature",
        "vision_max_tokens", "vision_tokens_per_word", "strip_ink_contrast",
        "strip_blank_pixels", "strip_rule_drift", "table_min_coverage",
        "table_max_duplication", "table_min_source_tokens",
        "table_unreadable_shared_below", "table_unreadable_known_below",
        "table_retry_temperature", "table_retry_penalty", "table_qa_retries",
        "qa_token_min_letters", "qa_word_min_letters",
        "table_continuation_page_gap")] == [
        4, 0.6, 0.1, 8192, 3.0, 64, 2, 2, 0.5, 0.4, 8, 0.25, 0.5, 0.4, 1.3, 1,
        2, 3, 1]
    assert defaults["vision_retry_penalties"] == {
        "second_attempt": 1.1, "third_attempt": 1.3, "later_attempts": 1.3}
    assert defaults["request_blank_words"] == {
        "section_title": "Unknown", "caption": "(none)", "head": "(no head)",
        "between": "(nothing)"}
    assert defaults["between_tables_words"] == {
        "figure_with_caption": "[Figure: {caption}]", "figure": "[Figure]",
        "heading": "# {title}"}
    assert defaults["read_cut_tables_in_strips"] is True
    assert defaults["collapse_stutter_rows"] is True


# -- 2. a vision request -----------------------------------------------------------

class Failing:
    """A client whose every request fails the way *error* says; it records
    what each request was sent with."""

    def __init__(self, error):
        self.sent = []
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.sent.append(kwargs)
        raise self.error


@pytest.fixture
def picture(tmp_path, monkeypatch):
    monkeypatch.setattr(vision.time, "sleep", lambda seconds: None)
    path = tmp_path / "t.png"
    path.write_bytes(png_bytes(Image.new("L", (20, 20), 255)))
    return path


def ask(client, picture, **more):
    return vision.call_vision(client, "system", "user", picture,
                              reply=replies.TABLE, **more)


def test_a_request_is_asked_as_often_as_the_rule_says(picture):
    client = Failing(RuntimeError("boom"))
    assert isinstance(ask(client, picture), Hole)
    assert len(client.sent) == 4
    with rules.overlaid(vision_max_attempts=2):
        client = Failing(RuntimeError("boom"))
        ask(client, picture)
        assert len(client.sent) == 2
        # a caller that names the attempts keeps its own
        client = Failing(RuntimeError("boom"))
        ask(client, picture, max_retries=3)
        assert len(client.sent) == 3


def test_a_request_is_sent_with_the_temperature_and_room_of_the_rules(picture):
    client = Failing(RuntimeError("boom"))
    ask(client, picture, max_retries=1)
    assert (client.sent[0]["temperature"], client.sent[0]["max_tokens"]) == (0.6, 8192)
    with rules.overlaid(figure_temperature=0.9, vision_max_tokens=1024):
        client = Failing(RuntimeError("boom"))
        ask(client, picture, max_retries=1)
        assert (client.sent[0]["temperature"],
                client.sent[0]["max_tokens"]) == (0.9, 1024)
        client = Failing(RuntimeError("boom"))
        ask(client, picture, max_retries=1, temperature=0.2, max_tokens=512)
        assert (client.sent[0]["temperature"],
                client.sent[0]["max_tokens"]) == (0.2, 512)


def penalties(client):
    return [sent["extra_body"].get("repetition_penalty")
            for sent in client.sent]


def test_the_penalty_for_repetition_climbs_as_the_rule_says(picture):
    client = Failing(providers.ProviderTimeout("slow"))
    ask(client, picture)
    assert penalties(client) == [None, 1.1, 1.3, 1.3]
    ladder = {"second_attempt": 1.2, "third_attempt": 1.4, "later_attempts": 1.5}
    with rules.overlaid(vision_retry_penalties=ladder):
        client = Failing(providers.ProviderTimeout("slow"))
        ask(client, picture)
        assert penalties(client) == [None, 1.2, 1.4, 1.5]


def test_the_request_budget_counts_the_words_and_the_room_of_the_rules(monkeypatch):
    for name in ("table_system_prompt", "table_user_prompt",
                 "table_continued_prompt", "figure_system_prompt",
                 "figure_user_prompt"):
        monkeypatch.setattr(config, name, lambda: "one two three four")
    # the table request counts 12 words, the figure request 8
    assert config.max_request_tokens(0) == 12 * 3 + config.IMAGE_TOKENS + 8192
    with rules.overlaid(vision_max_tokens=1000, vision_tokens_per_word=1.0):
        assert config.max_request_tokens(0) == 12 + config.IMAGE_TOKENS + 1000
    # the page request of stage 1 counts its words by the same rule
    from docpipe.preprocessing import page_text_without_layer as pages
    from docpipe.profile import load_profile
    kwp = load_profile("kwp")
    with rules.overlaid(vision_tokens_per_word=1.0):
        one = pages.page_request_tokens(kwp)
    with rules.overlaid(vision_tokens_per_word=2.0):
        two = pages.page_request_tokens(kwp)
    words = len(pages.prompts.load(pages.PAGE_TRANSCRIBE_PROMPT_ID,
                                   kwp).text.split())
    assert two - one == words


# -- 3. a table and its rereads ----------------------------------------------------

TEXTS = {"visuals/table_system": "table system",
         "visuals/table_user": "{section_title}|{page_number}|"
                               "{existing_caption}|{section_content}|"
                               "{caption_instruction}",
         "visuals/table_continued": " BEFORE {previous_caption}|"
                                    "{previous_head}|{between}",
         "visuals/table_retry_hint": HINT,
         "visuals/caption_keep": "keep",
         "visuals/caption_generate_table": "make table",
         "visuals/figure_user": "{section_title}|{page_number}|"
                                "{existing_caption}|{section_content}|"
                                "{caption_instruction}",
         "visuals/caption_generate_figure": "make figure",
         "visuals/figure_system": "figure system"}
GOOD = ["| a | b |", "| --- | --- |", "| x | 1 |"]
STUTTER = ["| a | b |", "| --- | --- |", "| x | 1 |", "| x | 1 |", "| x | 1 |"]
SOURCE = ("Liegenschaft Verbrauch Kita Nord Schule Sued Rathaus Hof Ost Bad "
          "West Heizung Gebaeude Strom Gas")


@pytest.fixture
def stub(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "_text", TEXTS.__getitem__)
    monkeypatch.setattr(process, "table_system_prompt", lambda: "table system")
    monkeypatch.setattr(process, "figure_system_prompt", lambda: "figure system")
    (tmp_path / "t.png").write_bytes(png_bytes(Image.new("L", (20, 20), 255)))
    calls = []

    def run(answer, *, section=None, before=None, source=SOURCE, table=None):
        def call_vision(client, system, user, path, *, reply, **kwargs):
            calls.append({"user": user, "reply": reply[0], **kwargs})
            return answer(len(calls)) if callable(answer) else (
                answer if isinstance(answer, Hole) else {"rows": list(answer)})

        monkeypatch.setattr(process, "call_vision", call_vision)
        calls.clear()
        got = process.process_table(
            table or {"id": "t1", "path": "t.png"},
            section if section is not None else {"title": "S", "content": "c"},
            tmp_path, None, ProcessingStats(), source_text=source,
            before=before)
        return got, list(calls)
    return run


def test_a_table_is_asked_at_the_temperature_of_the_rule(stub):
    _got, calls = stub(GOOD, source="")
    assert [c["temperature"] for c in calls] == [0.1]
    with rules.overlaid(table_temperature=0.3):
        _got, calls = stub(GOOD, source="")
        assert [c["temperature"] for c in calls] == [0.3]


def test_a_table_that_fails_is_asked_again_as_the_rules_say(stub):
    got, calls = stub(GOOD)                 # coverage 0: fails the check
    assert [c["temperature"] for c in calls] == [0.1, 0.4]
    assert [c.get("repetition_penalty") for c in calls] == [None, 1.3]
    assert calls[1]["user"].endswith(HINT) and not calls[0]["user"].endswith(HINT)
    # the request log names the hint as the prompt file the editor makes it from
    assert calls[1]["traced"]["made"]["user"][-1] == {
        "prompt": "visuals/table_retry_hint"}
    assert got["qa_warning"]
    with rules.overlaid(table_qa_retries=3, table_retry_temperature=0.7,
                        table_retry_penalty=1.5):
        _got, calls = stub(GOOD)
        assert len(calls) == 4
        assert [c["temperature"] for c in calls] == [0.1, 0.7, 0.7, 0.7]
        assert [c.get("repetition_penalty") for c in calls] == [None, 1.5, 1.5, 1.5]
    with rules.overlaid(table_qa_retries=0):
        got, calls = stub(GOOD)
        assert len(calls) == 1 and got["qa_warning"]


def test_a_table_that_passes_is_not_asked_again(stub):
    with rules.overlaid(table_qa_retries=3):
        _got, calls = stub(GOOD, source="")
        assert len(calls) == 1


# -- 4. the check -----------------------------------------------------------------

def test_the_check_follows_the_coverage_the_rule_names():
    markdown = "| Kita | Nord | Schule | Sued |\n| --- | --- | --- | --- |\n| Rathaus | Hof | 1 | 2 |"
    source = "Kita Nord Schule Sued Rathaus Hof Ost Bad"
    assert qa.assess(markdown, source)[1]["coverage"] == 0.75
    assert qa.assess(markdown, source)[0] is True
    with rules.overlaid(table_min_coverage=0.9):
        assert qa.assess(markdown, source)[0] is False


def test_the_check_follows_the_repeated_rows_the_rule_allows():
    markdown = "\n".join(["| a |", "| --- |", "| x |", "| x |", "| y |"])
    assert qa.duplication(markdown) == pytest.approx(0.25)
    assert qa.assess(markdown)[0] is True
    with rules.overlaid(table_max_duplication=0.1):
        assert qa.assess(markdown)[0] is False


def test_a_source_with_few_tokens_is_not_measured_unless_the_rule_is_lower():
    assert qa.coverage("Kita Nord", "| Kita |") is None
    with rules.overlaid(table_min_source_tokens=2):
        assert qa.coverage("Kita Nord", "| Kita |") == 0.5


def test_the_shortest_word_of_the_check_is_the_rule():
    assert qa.salient_tokens("Wärme im Ort 45,2 und a") == {
        "wärme", "im", "ort", "45,2", "und"}
    with rules.overlaid(qa_token_min_letters=4):
        assert qa.salient_tokens("Wärme im Ort 45,2 und a") == {"wärme", "45,2"}


def test_the_shortest_word_of_the_readability_test_is_the_rule():
    assert qa.words("Wärme im Ort und Gas") == {"wärme", "ort", "und", "gas"}
    with rules.overlaid(qa_word_min_letters=5):
        assert qa.words("Wärme im Ort und Gas") == {"wärme"}


def test_a_text_that_shares_little_and_knows_little_is_unreadable_by_the_rules():
    markdown = "| flexibility | demand |\n| --- | --- |\n| heat | 12 |"
    source = " ".join(["Ayjiqixayy", "Ayjiqixayy2", "Zzzzzz", "Qqqqqq",
                       "Wwwwww", "Eeeeee", "Rrrrrr", "Tttttt", "Yyyyyy"])
    known = {"flexibility", "demand", "heat"}
    assert qa.assess(markdown, source, known_words=known)[1][
        "source_unreadable"] is True
    with rules.overlaid(table_unreadable_shared_below=0.0):
        assert qa.assess(markdown, source, known_words=known)[1][
            "source_unreadable"] is False
    with rules.overlaid(table_unreadable_known_below=0.0):
        assert qa.assess(markdown, source, known_words=known)[1][
            "source_unreadable"] is False


# -- 5. stutter rows and strips -----------------------------------------------------

def test_a_failed_table_has_its_stuttered_rows_collapsed_only_while_the_rule_is_on(stub):
    got, _calls = stub(STUTTER)
    assert got["markdown"].count("| x | 1 |") == 1
    with rules.overlaid(collapse_stutter_rows=False):
        got, _calls = stub(STUTTER)
        assert got["markdown"].count("| x | 1 |") == 3


def test_a_table_that_passes_keeps_its_rows_whatever_the_rule(stub):
    rows = ["| a | b |", "| --- | --- |", "| x | 1 |", "| x | 1 |", "| y | 2 |",
            "| z | 3 |", "| w | 4 |", "| v | 5 |", "| u | 6 |"]
    got, _calls = stub(rows, source="")
    assert got["markdown"].count("| x | 1 |") == 2


def lined_png(rows=6) -> bytes:
    from PIL import ImageDraw
    image = Image.new("L", (200, 20 * rows + 10), 255)
    draw = ImageDraw.Draw(image)
    for at in range(rows):
        draw.text((8, 10 + 20 * at), f"Zeile {at} 1234", fill=0)
    return png_bytes(image)


def test_a_table_cut_off_with_the_most_room_is_read_in_strips_only_while_the_rule_is_on(stub, tmp_path):
    (tmp_path / "t.png").write_bytes(lined_png())
    got, calls = stub(Hole("cut_off"))
    assert len(calls) > 1 and any(c.get("picture") for c in calls[1:])
    assert got["vlm_why"] == "cut_off"
    with rules.overlaid(read_cut_tables_in_strips=False):
        got, calls = stub(Hole("cut_off"))
        assert len(calls) == 1 and not calls[0].get("picture")
        assert got["vlm_why"] == "cut_off" and "markdown" not in got


# -- 6. the strips ----------------------------------------------------------------

def test_the_contrast_of_writing_is_the_rule():
    image = Image.new("L", (40, 40), 255)
    image.paste(200, (5, 10, 10, 14))          # a faint mark, 55 levels darker
    assert sum(strips.ink_rows(image)) == 0
    with rules.overlaid(strip_ink_contrast=30):
        assert sum(strips.ink_rows(image)) == 5 * 4


def test_the_specks_a_blank_row_may_have_are_the_rule():
    ink = [5, 1, 1, 0, 5, 5]
    assert strips.cut_at(ink) == 2             # rows 1 to 3 are blank
    with rules.overlaid(strip_blank_pixels=0):
        assert strips.cut_at(ink) == 3         # only row 3 is


def test_the_tilt_of_a_rule_is_the_rule():
    image = Image.new("L", (30, 60), 255)
    image.paste(0, (10, 0, 11, 40))            # the rule, 40 rows
    image.paste(0, (12, 40, 13, 60))           # its tilted rest
    assert sum(strips.ink_rows(image)) == 0
    with rules.overlaid(strip_rule_drift=0):
        assert sum(strips.ink_rows(image)) == 20


# -- 7. the words of a request ------------------------------------------------------

def test_a_request_shows_the_words_of_the_rule_where_something_is_missing(stub):
    before = {"after": "t0", "caption": "", "head": "", "between": ""}
    _got, calls = stub(GOOD, section={"content": "c"}, source="", before=before)
    assert calls[0]["user"] == (
        "Unknown|?|(none)|c|make table BEFORE (none)|(no head)|(nothing)")
    words = {"section_title": "Unbekannt", "caption": "-", "head": "ohne",
             "between": "leer"}
    with rules.overlaid(request_blank_words=words):
        _got, calls = stub(GOOD, section={"content": "c"}, source="",
                           before=before)
        assert calls[0]["user"] == (
            "Unbekannt|?|-|c|make table BEFORE -|ohne|leer")


def test_a_figure_request_shows_the_words_of_the_rule(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "_text", TEXTS.__getitem__)
    monkeypatch.setattr(process, "figure_system_prompt", lambda: "figure system")
    (tmp_path / "f.png").write_bytes(png_bytes(Image.new("L", (20, 20), 255)))
    seen = []

    def call_vision(client, system, user, path, **kwargs):
        seen.append(user)
        return {"description": "d"}

    monkeypatch.setattr(process, "call_vision", call_vision)
    figure = {"id": "f1", "path": "f.png"}
    process.process_figure(figure, {"content": "c"}, tmp_path, None,
                           ProcessingStats())
    assert seen[-1] == "Unknown|?|(none)|c|make figure"
    words = {"section_title": "?!", "caption": "none", "head": "h",
             "between": "b"}
    with rules.overlaid(request_blank_words=words):
        process.process_figure(figure, {"content": "c"}, tmp_path, None,
                               ProcessingStats())
    assert seen[-1] == "?!|?|none|c|make figure"


def two_tables(page_of_second, between=None):
    segments = [{"kind": "table", "page": 3, "ref": "t1"}]
    figures = []
    if between == "figure":
        segments.append({"kind": "figure", "page": 3, "ref": "f1"})
        figures = [{"id": "f1", "caption": "Karte"}]
    elif between == "bare":
        segments.append({"kind": "figure", "page": 3, "ref": "f2"})
    elif between == "heading":
        pass
    segments.append({"kind": "table", "page": page_of_second, "ref": "t2"})
    return [{"title": "Anhang", "page_number": 3, "segments": segments,
             "tables": [{"id": "t1", "page_number": 3},
                        {"id": "t2", "page_number": page_of_second}],
             "figures": figures}]


def test_a_piece_between_two_tables_is_written_with_the_words_of_the_rule():
    assert continuation.links(two_tables(3, "figure"))["t2"]["between"] == "[Figure: Karte]"
    assert continuation.links(two_tables(3, "bare"))["t2"]["between"] == "[Figure]"
    heading = [{"title": "Anhang", "page_number": 3, "segments": [],
                "tables": [], "figures": []}]
    assert continuation._said("section", heading[0]) == "# Anhang"
    words = {"figure_with_caption": "Abb. {caption}", "figure": "Abb.",
             "heading": "== {title} =="}
    with rules.overlaid(between_tables_words=words):
        assert continuation.links(two_tables(3, "figure"))["t2"]["between"] == "Abb. Karte"
        assert continuation.links(two_tables(3, "bare"))["t2"]["between"] == "Abb."
        assert continuation._said("section", heading[0]) == "== Anhang =="


# -- 8. the page gap -----------------------------------------------------------------

def test_a_table_may_continue_one_that_began_as_many_pages_before_as_the_rule_says():
    assert "t2" in continuation.links(two_tables(3))        # the same page
    assert "t2" in continuation.links(two_tables(4))        # the next
    assert "t2" not in continuation.links(two_tables(5))    # two pages on
    with rules.overlaid(table_continuation_page_gap=2):
        assert "t2" in continuation.links(two_tables(5))
        assert "t2" not in continuation.links(two_tables(6))
    with rules.overlaid(table_continuation_page_gap=0):
        assert "t2" in continuation.links(two_tables(3))
        assert "t2" not in continuation.links(two_tables(4))


# -- 9. the sentences that stood in the code --------------------------------------------

def test_the_retry_hint_is_a_prompt_file_with_the_words_the_code_sent():
    assert prompts.text("visuals/table_retry_hint") == HINT
    assert "visuals/table_retry_hint" in config.PROMPT_IDS
    assert "visuals/table_retry_hint" in replies.REQUESTS["table"]
    assert "visuals/table_retry_hint" not in replies.REQUESTS["figure"]
    assert process.RETRY_HINT_PROMPT == "visuals/table_retry_hint"
