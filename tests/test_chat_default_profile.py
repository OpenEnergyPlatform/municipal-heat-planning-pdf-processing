"""The chat with no profile named.

What is promised, sentence by sentence:

  * the answer loop reads its phrases AND its prompts AND its read-off
    pieces from the built-in profile when no profile is named, and from the
    profile in force when there is one;
  * one log line names the profile it fell back to, once, and a named
    profile says nothing;
  * the app's one-line notice says the chat runs on the built-in profile and
    how to name another, in each profile's own language;
  * the fallback is the chat's alone: `prompts.load` and the stages that write
    a corpus still stop without a profile.
"""
import logging
import sys

import pytest

from docpipe import prompts
from docpipe.inference import chunker, llm_client, wording
from docpipe.profile import ENV_VAR, load_profile

BUILT_IN = load_profile("default")


@pytest.fixture
def nothing_named(monkeypatch):
    """No profile in force, and no memory of one from an earlier test."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(wording, "_checked", {})
    monkeypatch.setattr(wording, "_said_fallback", [])
    monkeypatch.setattr(llm_client, "_texts", prompts.per_profile(lambda: {}))
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)


@pytest.fixture
def kwp_named(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "kwp")
    monkeypatch.setattr(wording, "_checked", {})
    monkeypatch.setattr(wording, "_said_fallback", [])
    monkeypatch.setattr(llm_client, "_texts", prompts.per_profile(lambda: {}))
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)


def _built_in_phrases() -> dict:
    return wording.phrases(BUILT_IN)


def test_the_two_profiles_differ_where_these_tests_look():
    """Or the tests below could not tell the fallback from the profile in
    force: each of them compares a piece the two words differently."""
    kwp = load_profile("kwp")
    assert wording.phrases(kwp)["task_heading"] \
        != _built_in_phrases()["task_heading"]
    assert prompts.load("inference/phrase", kwp).text \
        != prompts.load("inference/phrase", BUILT_IN).text
    assert wording.readoff(kwp) != wording.readoff(BUILT_IN)


# The phrases, the prompts and the read-off pieces
def test_without_a_profile_the_phrases_are_the_built_in_profiles(
        nothing_named):
    assert wording.phrases() == _built_in_phrases()
    assert wording.REQUIRED <= set(wording.phrases())


def test_without_a_profile_the_read_off_pieces_are_the_built_in_profiles(
        nothing_named):
    assert wording.readoff() == wording.readoff(BUILT_IN)


def test_without_a_profile_the_prompts_are_the_built_in_profiles(
        nothing_named):
    for name, prompt_id in llm_client._PROMPTS.items():
        assert getattr(llm_client, name) \
            == prompts.load(prompt_id, BUILT_IN).text, name


def test_a_hit_is_labelled_without_a_profile(nothing_named):
    label = chunker.citation_label(
        {"owner_kind": "section", "owner_id": 1, "page_number": 7,
         "section_title": "Heat demand"})
    assert wording._component("PHRASES")["citation_page"].format(page=7) \
        in label


def test_the_first_question_reaches_the_model_in_the_built_in_words(
        nothing_named, monkeypatch):
    """The failure this was written for: the first question stopped on a
    LookupError before any request left."""
    sent = []

    def ask(kind, messages, **options):
        sent.append(messages[0]["content"])
        return {"phrase": "a sentence"}

    monkeypatch.setattr(llm_client, "_ask", ask)
    assert llm_client.make_search_phrase("How much heat?") \
        == ("a sentence", False)
    (message,) = sent
    assert message.startswith(
        prompts.load("inference/phrase", BUILT_IN).text)
    assert f"{_built_in_phrases()['task_heading']}:\nHow much heat?" \
        in message


def test_a_named_profile_is_not_replaced_by_the_built_in_one(
        kwp_named, monkeypatch):
    """The violating case: the fallback must not take a profile that is
    named, or every kwp deployment would answer in English."""
    kwp = load_profile("kwp")
    assert wording.phrases() == wording.phrases(kwp)
    assert wording.readoff() == wording.readoff(kwp)
    assert llm_client.PHRASE_SYSTEM_PROMPT \
        == prompts.load("inference/phrase", kwp).text
    assert llm_client.PHRASE_SYSTEM_PROMPT \
        != prompts.load("inference/phrase", BUILT_IN).text
    sent = []
    monkeypatch.setattr(llm_client, "_ask", lambda kind, messages, **o: (
        sent.append(messages[0]["content"]) or {"phrase": "x"}))
    llm_client.make_search_phrase("Wie viel Wärme?")
    assert f"{wording.phrases(kwp)['task_heading']}:\nWie viel Wärme?" \
        in sent[0]


def test_a_profile_given_is_the_one_read_even_where_another_is_in_force(
        kwp_named):
    assert wording.chat_profile(BUILT_IN) is BUILT_IN
    assert wording.phrases(BUILT_IN) == _built_in_phrases()


# One line in the log
def test_the_fallback_is_said_once_and_names_the_profile(
        nothing_named, caplog):
    with caplog.at_level(logging.INFO, logger=wording.log.name):
        wording.phrases()
        wording.readoff()
        chunker.citation_label({"owner_kind": "section", "owner_id": 1})
        llm_client.PHRASE_SYSTEM_PROMPT
    said = [r for r in caplog.records if r.name == wording.log.name]
    assert len(said) == 1, [r.getMessage() for r in said]
    line = said[0].getMessage()
    assert "'default'" in line
    assert "--profile" in line and ENV_VAR in line and "docpipe.toml" in line
    assert "\n" not in line


def test_a_named_profile_is_not_announced(kwp_named, caplog):
    with caplog.at_level(logging.INFO, logger=wording.log.name):
        wording.phrases()
        llm_client.PHRASE_SYSTEM_PROMPT
    assert [r for r in caplog.records if r.name == wording.log.name] == []


def test_the_pages_words_without_a_profile_do_not_say_it(nothing_named,
                                                         caplog):
    """The picker's words were the built-in profile's before this and need
    no line of their own: the page's notice says it."""
    with caplog.at_level(logging.INFO, logger=wording.log.name):
        assert wording.ui() == BUILT_IN._own("inference", "UI")
    assert [r for r in caplog.records if r.name == wording.log.name] == []


# The notice on the page
@pytest.mark.parametrize("name,language", [
    ("default", "English"), ("scenarios", "English"), ("kwp", "German")])
def test_the_notice_says_the_chat_runs_on_the_built_in_profile(name, language):
    line = wording.ui(load_profile(name))["no_profile"]
    assert "\n" not in line
    assert "`default`" in line
    # how to name another one
    assert "--profile" in line and "docpipe.toml" in line \
        and "DOCPIPE_PROFILE" in line
    if language == "German":
        assert "läuft" in line and "eingebauten Profil" in line
        assert "cannot" not in line
    else:
        assert "runs on the built-in profile" in line
    # it no longer says that a question cannot be answered
    assert "cannot be answered" not in line
    assert "keine Frage" not in line


# What stays as it was
def test_the_prompt_loader_still_needs_a_profile(nothing_named):
    """The fallback is in the chat, not in `prompts`: a stage that asks
    for a prompt without a profile has forgotten it, and must hear so."""
    with pytest.raises(LookupError, match="needs a profile"):
        prompts.load("inference/phrase")
    with pytest.raises(LookupError, match="needs a profile"):
        prompts.text("refinement/refine")


def test_refine_without_a_profile_stops_before_anything_runs(
        nothing_named, monkeypatch, capsys):
    from docpipe.refinement import pipeline
    started = []
    monkeypatch.setattr(pipeline.usage, "begin", lambda *a: started.append(a))
    monkeypatch.setattr(sys, "argv", ["refine", "--batch"])
    with pytest.raises(SystemExit) as stopped:
        pipeline.main()
    assert "no profile" in str(stopped.value) and "--profile" \
        in str(stopped.value)
    assert started == [], "nothing was begun"
