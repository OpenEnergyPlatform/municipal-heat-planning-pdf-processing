"""The decisions of stage 4 (refinement) are rules the owner can set, with the
value the code used to hold as the default (docpipe/ruleset/stage_refine.py).

Promises, each with a case that breaks it by construction:

1. Every rule of the module has a default in the default profile's rules that
   `rules.problem` takes, a title and a help; and a value outside its bounds
   is refused.
2. With the default values the stage does what it did: the same attempts,
   window size, cuts, heading cleaning, removal guards and reply room.
3. With another value the stage decides otherwise, where it decides: fewer
   attempts, a smaller longest section, no cut at all, no removal guard, no
   heading number cut, a bigger share the corrections may remove.
4. The setting that wins over a file (REFINE_WINDOW_SIZE, REFINE_REPLY_CEILING,
   REFINE_RETURN_CORRECTIONS) still wins.
5. The two sentences a model reads that stood in code are prompt files, and
   what the model is sent is the same words as before, byte for byte; the log
   names the user message as made from them.
"""
import json
import re
from types import SimpleNamespace

import pytest

from docpipe import prompts, rules
from docpipe.extraction import trace
from docpipe.refinement import config as rconfig
from docpipe.refinement import corrections, refine, replies, split
from docpipe.ruleset import stage_refine


def names():
    return [one.name for one in stage_refine.RULES]


# -- 1. the rules --------------------------------------------------------------

def test_every_rule_has_a_default_a_title_and_a_help():
    default = rules.default()
    for one in stage_refine.RULES:
        assert one.tab == "stages" and one.group == stage_refine.GROUP
        assert one.name in default.values, one.name
        assert rules.problem(one.name, default[one.name]) is None, one.name
        assert one.title and one.help, one.name
        # a help says what the value decides, not how it came about
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b|owner request|used to",
                             one.help), one.name


def test_a_value_outside_its_bounds_is_no_value():
    assert rules.problem("refine_max_attempts", 0)
    assert rules.problem("refine_window_sections", 21)
    assert rules.problem("corrections_max_shrink", 1.5)
    assert rules.problem("split_long_sections", "yes")
    assert rules.problem("title_number_patterns", [""])
    assert rules.problem("refine_max_attempts", 3) is None


def test_the_defaults_are_the_values_the_code_held():
    got = {name: rules.default()[name] for name in names()}
    assert got["refine_max_attempts"] == 4
    assert got["refine_window_sections"] == 3
    assert got["refine_return_corrections"] is False
    assert got["corrections_max_shrink"] == 0.3
    assert got["tokens_per_word"] == 3.0 and got["reply_headroom"] == 1.35
    assert got["reply_tokens_ceiling"] == 16384
    assert got["refine_default_max_tokens"] == 8192
    assert got["refine_default_temperature"] == 0.1
    assert got["split_default_max_tokens"] == 1024
    assert got["split_default_temperature"] == 0.1
    assert got["section_max_words"] == 1000
    assert got["section_target_words"] == 600
    assert got["split_min_part_words"] == 100
    assert got["title_shout_min_letters"] == 6
    assert got["title_acronym_max_letters"] == 4
    for switch in ("split_long_sections", "clean_titles",
                   "keep_sections_with_media", "keep_opening_section",
                   "keep_front_matter", "drop_cover_pages",
                   "fold_bare_headings"):
        assert got[switch] is True, switch
    assert len(got["title_number_patterns"]) == 4


# -- 4. the settings that win over a file ---------------------------------------

def test_a_setting_still_wins_over_the_file():
    made = rules.load(environ={"REFINE_WINDOW_SIZE": "5",
                               "REFINE_REPLY_CEILING": "4096",
                               "REFINE_RETURN_CORRECTIONS": "1"})
    assert made["refine_window_sections"] == 5
    assert made["reply_tokens_ceiling"] == 4096
    assert made["refine_return_corrections"] is True
    # and where none is set, the file says it
    plain = rules.load(environ={})
    assert plain["refine_window_sections"] == 3
    assert plain["refine_return_corrections"] is False


def test_the_settings_name_their_rule():
    from docpipe import settings
    by_env = {s.env: s for s in settings.SETTINGS}
    for env, name in (("REFINE_WINDOW_SIZE", "refine_window_sections"),
                      ("REFINE_REPLY_CEILING", "reply_tokens_ceiling"),
                      ("REFINE_RETURN_CORRECTIONS",
                       "refine_return_corrections")):
        assert by_env[env].rule == name and by_env[env].default is None


# -- 2. and 3. the attempts ------------------------------------------------------

class Failing:
    """A client whose server always fails with a 500, and counts."""

    def __init__(self):
        self.calls = 0
        outer = self

        def create(**sent):
            outer.calls += 1
            raise RuntimeError("server down")
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


WINDOW = [{"title": "Einleitung", "content": "Text der Einleitung."}]


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(refine.time, "sleep", lambda seconds: None)


def test_a_window_is_asked_as_often_as_the_rule_says(quick):
    client = Failing()
    refine._call_llm(WINDOW, client)
    assert client.calls == 4
    for more in (1, 2, 7):
        client = Failing()
        with rules.overlaid(refine_max_attempts=more):
            refine._call_llm(WINDOW, client)
        assert client.calls == more


def test_the_cut_request_is_asked_as_often_as_the_rule_says(quick):
    for more in (4, 2):
        client = Failing()
        with rules.overlaid(refine_max_attempts=more):
            with pytest.raises(split.NotServed):
                refine._make_splitter(client)("system", "user")
        assert client.calls == more


def test_the_context_step_of_stage_6_shares_the_number(monkeypatch):
    from docpipe.chunking import context
    seen = {}

    def ask_model(client, request, **kept):
        seen.update(kept)
    monkeypatch.setattr(context, "ask_model", ask_model)
    monkeypatch.setattr(context.providers, "client", lambda *a, **k: None)
    monkeypatch.setattr(context, "window_fits", lambda *a, **k: None)
    with rules.overlaid(refine_max_attempts=6):
        ask, _ = context.make_ask()
        ask({})
    assert seen["max_retries"] == 6
    with rules.overlaid(refine_max_attempts=2):
        ask, _ = context.make_ask()
        ask({})
    assert seen["max_retries"] == 2


# -- the room of a request ---------------------------------------------------------

def test_the_reply_room_follows_the_rules(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setattr(rconfig, "refine_prompt",
                        lambda: SimpleNamespace(meta={}))
    # 5000 words of input: 5000 * 3.0 * 1.35 = 20250 tokens, over the ceiling
    assert rconfig.reply_tokens(5000) == 16384
    with rules.overlaid(reply_tokens_ceiling=10000):
        assert rconfig.reply_tokens(5000) == 10000
    with rules.overlaid(tokens_per_word=1.0, reply_headroom=1.0):
        assert rconfig.reply_tokens(5000) == 8192      # 5000 is under the floor
    with rules.overlaid(tokens_per_word=2.0, reply_headroom=2.0):
        assert rconfig.reply_tokens(2500) == 10000
    # the floor is a rule too
    with rules.overlaid(refine_default_max_tokens=12000):
        assert rconfig.reply_tokens(10) == 12000


def test_the_largest_reply_and_the_budget_follow_the_rules(monkeypatch):
    monkeypatch.setattr(rconfig, "system_prompt", lambda: "")
    assert rconfig.largest_reply_tokens() == 16384
    with rules.overlaid(reply_tokens_ceiling=2048, refine_window_sections=1,
                        section_max_words=100, tokens_per_word=2.0):
        assert rconfig.largest_reply_tokens() == 2048
        assert rconfig.max_request_tokens() == 2 * 100 * 2 + 2048
    with rules.overlaid(refine_return_corrections=True):
        assert rconfig.largest_reply_tokens() == rconfig.llm_max_tokens()
        assert rconfig.prompt_ids()[0] == "refinement/refine_corrections"
    assert rconfig.prompt_ids()[0] == "refinement/refine"


def test_the_default_sampling_is_the_rules_where_the_prompt_names_none(
        monkeypatch):
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setattr(rconfig, "refine_prompt",
                        lambda: SimpleNamespace(meta={}))
    monkeypatch.setattr(split, "split_prompt",
                        lambda: SimpleNamespace(meta={}))
    assert (rconfig.llm_temperature(), rconfig.llm_max_tokens()) == (0.1, 8192)
    assert (split.split_temperature(), split.split_max_tokens()) == (0.1, 1024)
    with rules.overlaid(refine_default_temperature=0.5,
                        refine_default_max_tokens=300,
                        split_default_temperature=0.7,
                        split_default_max_tokens=99):
        assert (rconfig.llm_temperature(), rconfig.llm_max_tokens()) \
            == (0.5, 300)
        assert (split.split_temperature(), split.split_max_tokens()) \
            == (0.7, 99)
    # what the prompt names wins over the rule
    monkeypatch.setattr(rconfig, "refine_prompt", lambda: SimpleNamespace(
        meta={"temperature": 0.2, "max_tokens": 111}))
    with rules.overlaid(refine_default_temperature=0.5):
        assert (rconfig.llm_temperature(), rconfig.llm_max_tokens()) \
            == (0.2, 111)


def test_a_corrections_window_asks_by_the_rule(monkeypatch):
    sections = [{"title": "A", "content": "b", "tables": [{"id": "t"}],
                 "segments": [], "pages": []}]
    assert "index" not in refine._stripped(sections)[0]
    with rules.overlaid(refine_return_corrections=True):
        assert refine._stripped(sections)[0]["index"] == 0
        assert refine.reply_shapes()["refined_sections"] == replies.CORRECTIONS
    assert refine.reply_shapes()["refined_sections"] != replies.CORRECTIONS


# -- long sections -----------------------------------------------------------------

def words(n, tag="w"):
    return " ".join(f"{tag}{i}." for i in range(n))


def long_section(n=2500):
    """A section of n words in segments of 50 words each."""
    segments = [{"kind": "text", "page": 1, "text": words(50, f"s{i}x")}
                for i in range(n // 50)]
    return {"title": "Long", "content": " ".join(s["text"] for s in segments),
            "segments": segments, "tables": [], "figures": [], "pages": [1]}


def count(parts):
    return sum(len(p["content"].split()) for p in parts)


def test_the_longest_section_and_the_target_are_the_rules():
    section = long_section(1500)
    assert split.needs_split(section) is True
    assert split.needs_split(long_section(1000)) is False
    with rules.overlaid(section_max_words=2000):
        assert split.needs_split(section) is False
    with rules.overlaid(section_max_words=500):
        assert split.needs_split(long_section(1000)) is True
    # cut after the refinement: parts of at most the longest allowed
    parts = refine._hold_to_limit([section])
    assert len(parts) >= 2 and max(len(p["content"].split())
                                   for p in parts) <= 1000
    assert count(parts) == 1500
    with rules.overlaid(section_max_words=300, section_target_words=200):
        small = refine._hold_to_limit([section])
        assert max(len(p["content"].split()) for p in small) <= 300
        assert len(small) > len(parts) and count(small) == 1500


def test_no_cut_where_the_rule_is_off():
    section = long_section(1500)
    with rules.overlaid(split_long_sections=False):
        assert refine._hold_to_limit([section]) == [section]
        assert split.split_oversized([section]) == [section]


def test_the_target_is_named_to_the_model():
    seen = []

    def ask(system, user, again=False):
        seen.append(system)
        return {"first_title": "A", "cuts": []}
    with rules.overlaid(section_target_words=321):
        split._ask_range(long_section(1500), ask, 0, 1)
    assert "about 321 words" in seen[0]
    seen.clear()
    split._ask_range(long_section(1500), ask, 0, 1)
    assert "about 600 words" in seen[0]


def test_a_cut_that_leaves_a_sliver_is_dropped_by_the_rule():
    section = long_section(300)          # six segments of 50 words
    cuts = [{"at": 1, "title": "a"}, {"at": 4, "title": "b"}]
    # the part before cut 1 has 50 words: under the default 100
    assert [c["at"] for c in split._sanitize(cuts, 6, section)] == [4]
    with rules.overlaid(split_min_part_words=40):
        assert [c["at"] for c in split._sanitize(cuts, 6, section)] == [1, 4]
    with rules.overlaid(split_min_part_words=120):
        # 150 words before cut 4 hold; the 100 words after it do not
        assert split._sanitize(cuts, 6, section) == []


def test_the_last_small_part_joins_by_the_rule():
    sizes = [60, 60, 60, 60, 30]
    assert split._group(sizes, 120, 1000) == [0, 2]
    with rules.overlaid(split_min_part_words=20):
        assert split._group(sizes, 120, 1000) == [0, 2, 4]


# -- headings ------------------------------------------------------------------------

def test_heading_numbers_are_cut_by_the_patterns():
    for title, cleaned in (("3.3.3 Wärmebedarf", "Wärmebedarf"),
                           ("4-1 Ziele", "Ziele"), ("6 Fazit", "Fazit"),
                           ("A. Anhang", "Anhang"), ("IV. Maßnahmen",
                                                      "Maßnahmen"),
                           ("6.1 7 Foo", "Foo"),
                           ("2030 Ziele", "2030 Ziele")):
        assert refine._normalize_title(title) == cleaned, title
    with rules.overlaid(title_number_patterns=[]):
        assert refine._normalize_title("3.3.3 Wärmebedarf") \
            == "3.3.3 Wärmebedarf"
    # a pattern of the rule is the only one: Roman numbers no longer count
    with rules.overlaid(title_number_patterns=["\\d+\\."]):
        assert refine._normalize_title("IV. Maßnahmen") == "IV. Maßnahmen"
        assert refine._normalize_title("12. Maßnahmen") == "Maßnahmen"


def test_a_heading_in_capitals_is_written_in_normal_case_by_the_rules():
    assert refine._normalize_title("ENERGIE UND KWP") == "Energie UND KWP"
    assert refine._normalize_title("ABCDE") == "ABCDE"      # five letters
    assert refine._normalize_title("ABCDEF") == "Abcdef"    # six
    with rules.overlaid(title_shout_min_letters=3):
        assert refine._normalize_title("ABCDE") == "Abcde"
    with rules.overlaid(title_shout_min_letters=20):
        assert refine._normalize_title("ENERGIE UND KWP") == "ENERGIE UND KWP"
    with rules.overlaid(title_acronym_max_letters=2):
        assert refine._normalize_title("ENERGIE UND KWP") == "Energie Und Kwp"
    with rules.overlaid(title_acronym_max_letters=7):
        assert refine._normalize_title("ENERGIE UND KWP") == "ENERGIE UND KWP"


def test_headings_are_cleaned_only_where_the_rule_is_on(monkeypatch):
    # refine_sections ends with the cleaning; stand in for everything before
    # it: one section, no model asked
    seen = []
    monkeypatch.setattr(refine, "_normalize_title",
                        lambda t: seen.append(t) or t)
    source = [{"title": "1 A", "content": "x", "tables": [], "figures": [],
               "segments": [], "pages": [1]}]
    monkeypatch.setattr(refine, "_call_llm", lambda *a, **k: [dict(source[0])])
    monkeypatch.setattr(refine.providers, "client", lambda *a, **k: None)
    refine.refine_sections([dict(source[0])])
    assert seen == ["1 A"]
    seen.clear()
    with rules.overlaid(clean_titles=False):
        refine.refine_sections([dict(source[0])])
    assert seen == []


# -- what the model may drop ---------------------------------------------------------

def section(title, content, page, **rest):
    return {"title": title, "content": content, "tables": [], "figures": [],
            "segments": [{"page": page}], "pages": [page], **rest}


def removed(sec):
    return {**sec, "_action": "remove"}


def kept_content(sections, front=frozenset()):
    done, _ = refine._apply_actions(sections, None, front)
    return [s["content"] for s in done]


def test_a_section_with_a_table_is_kept_by_the_rule():
    sec = removed(section("Tabelle", "[p5_tbl0]", 5,
                          tables=[{"id": "p5_tbl0"}]))
    assert kept_content([sec]) == ["[p5_tbl0]"]
    with rules.overlaid(keep_sections_with_media=False):
        assert kept_content([sec]) == [""]


def test_the_text_before_the_first_heading_is_kept_by_the_rule(monkeypatch):
    title = "Vorspann"
    sec = removed(section(title, "Kopfzeile des Journals", 4))
    with rules.overlaid(front_section_title=title):
        assert kept_content([sec]) == ["Kopfzeile des Journals"]
        with rules.overlaid(keep_opening_section=False):
            assert kept_content([sec]) == [""]
    # a section of another title is the rule's to remove
    assert kept_content([sec]) == [""]


def test_the_front_matter_is_kept_by_the_rule():
    sec = removed(section("Autoren", "A. Autor, Institut", 1))
    assert kept_content([sec], {1}) == ["A. Autor, Institut"]
    with rules.overlaid(keep_front_matter=False):
        assert kept_content([sec], {1}) == [""]
    # a section elsewhere goes either way
    assert kept_content([removed(section("X", "y", 9))], {1}) == [""]


def test_a_cover_page_is_dropped_by_the_rule():
    cover = {**section("Repository", "Open access archive", 1),
             "_action": "cover"}
    assert kept_content([cover], {1}) == []
    with rules.overlaid(drop_cover_pages=False):
        assert kept_content([cover], {1}) == ["Open access archive"]


def test_a_bare_heading_is_folded_by_the_rule():
    sections = [section("Titel der Studie", "", 1),
                section("Autoren", "A. Autor", 1)]
    folded = refine._fold_bare_headings([dict(s) for s in sections])
    assert folded[0]["content"].startswith("Titel der Studie\n")
    with rules.overlaid(fold_bare_headings=False):
        again = refine._fold_bare_headings([dict(s) for s in sections])
        assert [s["content"] for s in again] == ["A. Autor"]


# -- the corrections ------------------------------------------------------------------

def test_the_corrections_may_remove_the_share_the_rule_says():
    tail = "B" * 14 + "C" * 20 + "D" * 20
    original = "A" * 40 + " keep " + tail             # 100 characters
    edit = [{"find": tail, "replace": ""}]             # takes 54 of 100
    text, report = corrections.apply_corrections(original, edit)
    assert text == original and not report.ok
    assert "over the 30%" in report.rejected[0][1]
    with rules.overlaid(corrections_max_shrink=0.6):
        text, report = corrections.apply_corrections(original, edit)
        assert text == original[:-54] and report.ok
    small = [{"find": "C" * 20, "replace": ""}]
    text, report = corrections.apply_corrections(original, small)
    assert report.ok and len(text) == 80
    with rules.overlaid(corrections_max_shrink=0.1):
        text, report = corrections.apply_corrections(original, small)
        assert text == original and not report.ok


# -- 5. the sentences a model reads ---------------------------------------------------

OLD_CONTEXT = (
    "CONTEXT (read-only — do NOT include this in your output): the "
    "section immediately before the first section below, whole. "
    "Use it ONLY to decide whether the first section is a "
    "broken continuation of it (then set that first section's "
    '_action to "merge_into_previous").\n')


def test_a_window_with_context_is_sent_the_words_it_always_was():
    previous = {"title": "Vorher", "content": "Der {Satz} endet nicht"}
    sent = refine._user_content([{"title": "A", "content": "b"}], previous)
    context = json.dumps({"title": "Vorher", "content": "Der {Satz} endet nicht"},
                         ensure_ascii=False, indent=2)
    payload = json.dumps({"sections": [{"title": "A", "content": "b"}]},
                         ensure_ascii=False, indent=2)
    assert sent == (OLD_CONTEXT + context + "\n\nSECTIONS TO PROCESS:\n"
                    + payload)
    # without a section before it the message is its sections, nothing else
    assert refine._user_content([{"title": "A", "content": "b"}], None) \
        == payload


def test_the_split_request_is_sent_the_words_it_always_was():
    section = {"title": "Ein Titel", "segments": [
        {"kind": "text", "text": "Erster  Block"},
        {"kind": "table", "ref": "p1_tbl0"}]}
    assert split.split_user(section, 0, 2) == (
        "TITLE: Ein Titel\n\nOUTLINE:\n"
        "   0 [2 words] Erster Block\n   1 [TABLE] p1_tbl0")
    assert split.split_user({"title": None, "segments": []}, 0, 0) \
        == "TITLE: \n\nOUTLINE:\n"


def test_the_two_sentences_are_prompt_files_the_stage_records():
    for pid in ("refinement/window_context", "refinement/split_user"):
        prompt = prompts.load(pid)
        assert prompt.placeholders, pid
        assert not prompt.text.endswith("\n") and "\r" not in prompt.text
        assert pid in rconfig.prompt_ids()
    assert prompts.load("refinement/window_context").placeholders \
        == {"context", "sections"}
    assert prompts.load("refinement/split_user").placeholders \
        == {"title", "outline"}
    assert "refinement/window_context" in replies.REQUESTS["refine"]
    assert "refinement/split_user" in replies.REQUESTS["split"]


def test_a_kind_of_request_names_a_prompt_it_is_not_made_of_never():
    # failing by construction: a prompt id that no file holds
    with pytest.raises(FileNotFoundError):
        prompts.load("refinement/no_such_sentence")


class Said:
    """A client whose server answers one unusable sentence."""

    def __init__(self):
        message = SimpleNamespace(content="not json")
        self.reply = SimpleNamespace(
            choices=[SimpleNamespace(message=message,
                                     finish_reason="stop")], usage=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **sent: self.reply))


def test_the_log_names_the_user_message_as_made_from_the_prompt(monkeypatch,
                                                                quick):
    logged = []
    monkeypatch.setattr(trace, "stage_request",
                        lambda kind, sent, attempt, asked_at, **notes:
                        logged.append((kind, sent, notes)))
    previous = {"title": "Vorher", "content": "Text"}
    refine._call_llm(WINDOW, Said(), previous)
    refine._call_llm(WINDOW, Said(), None)
    with_context, without = logged[0], logged[-1]
    assert with_context[2]["made"]["user"] == [
        {"prompt": "refinement/window_context", "fill": "render"}]
    assert without[2]["made"]["user"] == [{"data": True}]
    # and the editor can make the message again from the file
    message = with_context[1]["messages"][1]["content"]
    parts = with_context[2]["made"]["user"]
    values = prompts.values_in(parts, lambda pid: prompts.load(pid).text,
                               message)
    assert values is not None
    assert prompts.composed(parts, lambda pid: prompts.load(pid).text,
                           values) == message


def test_the_log_names_the_split_message_as_made_from_the_prompt(monkeypatch,
                                                                  quick):
    logged = []
    monkeypatch.setattr(trace, "stage_request",
                        lambda kind, sent, attempt, asked_at, **notes:
                        logged.append((kind, sent, notes)))
    section = {"title": "T", "segments": [{"kind": "text", "text": "a b"}]}
    user = split.split_user(section, 0, 1)
    refine._make_splitter(Said())(prompts.text("refinement/split", target=600),
                                  user)
    kind, sent, notes = logged[0]
    assert kind == "split"
    assert notes["made"]["user"] == [{"prompt": "refinement/split_user",
                                      "fill": "render"}]
    parts = notes["made"]["user"]
    values = prompts.values_in(parts, lambda pid: prompts.load(pid).text,
                               sent["messages"][1]["content"])
    assert values == [{"title": "T", "outline": "   0 [2 words] a b"}]
