"""
A rule that chooses how a request asks chooses its words too (owner
decision 2026-11-12: the prompts get a second wording of the sentence that
asks for a line's address, and the rule `answer_with` chooses which is
sent; in the standard every request stays the same).

The promise: a request is told the way of each group of ways that its rule
has in the request's step, and no marker; AND where the rule has the answer
name its line by its words, no request of the reading asks for "at", a
follow-up included; AND a group that lacks a way for a choice of its rule,
names one it does not have, or a rule it is not, fails when the prompt is
cut, before anything is sent. Broken by construction: a group without its
quote way, a way for a choice that does not exist, a rule that is none, a
group that is not closed.
"""
import pytest

from docpipe import prompts, rules
from docpipe.editor import prompts as editor_prompts
from docpipe.extraction import addressed, thread
from docpipe.profile import load_profile
from docpipe.prompts import Prompt

GROUP = ("Before.\n"
         "<!-- way: answer_with=address -->\n"
         "Name the address of its line.\n"
         "<!-- way: answer_with=quote -->\n"
         "Name its line, character for character, under quote.\n"
         "<!-- /way -->\n"
         "\n"
         "After.\n")


def prompt_of(text: str, name: str = "extraction/x") -> Prompt:
    return Prompt(id=name, text=text, meta={}, path=None, sha256="")


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def test_a_request_is_told_the_way_its_rule_has_in_its_step():
    standard = thread.cut(prompt_of(GROUP)).system().text
    assert standard == "Before.\nName the address of its line.\n\nAfter.\n"
    with rules.overlaid(answer_with="quote"):
        quoted = thread.cut(prompt_of(GROUP)).system().text
    assert quoted == ("Before.\nName its line, character for character, "
                      "under quote.\n\nAfter.\n")
    # a step's own value chooses for the requests of that step
    node = {"id": "x", "box": "find"}
    with rules.in_step(rules.stepped(node, {"answer_with": "quote"})):
        assert thread.cut(prompt_of(GROUP)).system().text == quoted
    # the longest way counts where the most a request is told is measured
    assert "character for character" in thread.widest(GROUP)


def test_a_text_without_ways_is_told_as_it_stands():
    plain = "Before.\nName the address of its line.\n\nAfter.\n"
    assert thread.chosen(plain) is plain


@pytest.mark.parametrize("broken, said", [
    (GROUP.replace("<!-- way: answer_with=quote -->\n"
                   "Name its line, character for character, under quote.\n",
                   ""), "choices"),
    (GROUP.replace("answer_with=quote", "answer_with=cell"), "choices"),
    (GROUP.replace("answer_with=", "answer_how="), "no rule"),
    (GROUP.replace("<!-- /way -->\n", ""), "not closed"),
    ("<!-- /way -->\n" + GROUP, "closes no way"),
    (GROUP.replace("way: answer_with=quote", "way: answer_with=address"),
     "two ways")])
def test_a_group_of_ways_that_does_not_fit_its_rule_fails_when_cut(broken,
                                                                   said):
    with pytest.raises(LookupError, match=said):
        thread.cut(prompt_of(broken))


# The prompts of the reading that ask for a line, in both profiles.
ASKING = ("find", "coord", "docfield", "search", "list", "work")


def systems(profile_name: str) -> dict:
    """{prompt id: the system text of a request that carries every field}
    of the reading's prompts of a profile, as the rule now has them."""
    profile = load_profile(profile_name)
    out = {}
    for kind in ASKING:
        try:
            prompt = prompts.load(f"extraction/{kind}", profile)
        except (FileNotFoundError, LookupError):
            continue
        parts = thread.cut(prompt)
        keys = {key for part in parts.of(thread.WITH) for key in part.keys}
        out[prompt.id] = parts.system(keys).text
    return out


@pytest.mark.parametrize("profile_name", ["kwp", "scenarios"])
def test_with_answers_by_quote_no_request_of_the_reading_asks_for_at(
        profile_name):
    standard = systems(profile_name)
    with rules.overlaid(answer_with="quote"):
        quoted = systems(profile_name)
    assert set(quoted) == set(standard) and len(standard) >= 5
    for prompt_id, text in quoted.items():
        assert '"at"' not in text, prompt_id
        assert "<!--" not in text and "<!--" not in standard[prompt_id]
    # the failure by construction: the standard asks for "at" and has no
    # word of the second way
    assert all('"at"' in text for prompt_id, text in standard.items()
               if not prompt_id.endswith(("/list", "/check")))
    assert not any('"quote"' in text for text in standard.values())


def test_a_follow_up_asks_for_what_the_request_asked():
    entry = {"quote": "| Rathaus | 1.200 | 27 |", "words": "999"}
    standard = addressed.told(addressed.WORDS_NOT_IN_LINE,
                              {"at": "3.2", "words": "999"})
    assert "'3.2'" in standard
    with rules.overlaid(answer_with="quote"):
        quoted = addressed.told(addressed.WORDS_NOT_IN_LINE, entry)
        no_line = addressed.told(addressed.NOT_AN_ADDRESS, entry)
    assert '"quote"' in quoted and "Rathaus" in quoted
    assert '"quote"' in no_line and "Adresse {" not in no_line
    assert "None" not in quoted + no_line


def test_the_page_reads_a_way_marker_only_on_a_line_of_its_own():
    assert editor_prompts._loose(GROUP) == []
    inline = "Name it. <!-- way: answer_with=quote --> Or its line.\n"
    assert editor_prompts._loose(inline) == [
        "<!-- way: answer_with=quote -->"]
