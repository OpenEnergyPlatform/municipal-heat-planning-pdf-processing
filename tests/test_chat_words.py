"""The words a person reads in the chat app have a place in the page (owner
request 2026-11-19, point A2 of the review of that day: "Die Texte und
Achsennamen der Chat-Oberfläche (`profiles/*/inference.py`)" had none).

They are the text block module "chat" (`prompts/chat/phrases.json`), which
the Prompts tab lists and edits as it does the sentences of the stages. Each
promise is held against a case that breaks it by construction:

1. The editor lists the module, shows each word with whether the chat
   cannot run without it, AND refuses a name no page shows.
2. Each profile's chat reads the words its file says, laid over those of the
   profiles it extends: the pages, the names of the axes, why the graph
   route did not answer, the marker of a value read off a figure.
3. A word the chat cannot run without may not be missing, AND a name of no
   family is refused when the words are read.
4. The picker of kwp names a plan's version in the chat words of its
   profile, AND the doctor checks those words under their file and fails
   where one is missing.
"""
from __future__ import annotations

import pytest

from docpipe import phrases as phrase_files
from docpipe.editor import phrases as editor_phrases
from docpipe.inference import kg_route, wording
from docpipe.profile import load_profile

KWP = load_profile("kwp")
SCENARIOS = load_profile("scenarios")


def read(path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


@pytest.fixture(autouse=True)
def fresh():
    wording._chat_checked.clear()
    yield
    wording._chat_checked.clear()


# -- 1. the place in the page -------------------------------------------------------------

def test_the_editor_lists_the_chat_words_as_a_text_block_module():
    assert "chat" in phrase_files.MODULES
    shown = editor_phrases.detail(KWP, "chat", read)
    by_key = {row["key"]: row for row in shown["sentences"]}
    assert by_key["page_chat"]["text"] == "Recherche"
    assert by_key["page_chat"]["required"] is True
    assert by_key["axis_year"]["required"] is False
    assert by_key["readoff_note"]["note"]
    # the scenarios profile words nothing differently and has no file
    assert editor_phrases.detail(SCENARIOS, "chat", read)["own_file"] is False


def test_a_changed_word_is_taken_and_a_name_no_page_shows_is_refused():
    own = editor_phrases.detail(KWP, "chat", read)["table"]
    changed = {**own, "page_chat": "Suche"}
    assert editor_phrases.judge(KWP, "chat", changed, read)["ok"] is True
    unknown = {**own, "page_nowhere": "Nirgends"}
    judged = editor_phrases.judge(KWP, "chat", unknown, read)
    assert judged["ok"] is False and judged["where"] == "page_nowhere"
    lacking = {key: value for key, value in own.items()
               if key != "readoff_marker"}
    # the built-in profile words it, so the kwp file may leave it out
    assert editor_phrases.judge(KWP, "chat", lacking, read)["ok"] is True


# -- 2. what each profile's chat reads ------------------------------------------------------

def test_each_profile_reads_the_words_of_its_file_over_those_it_extends():
    assert wording.ui(KWP)["page_chat"] == "Recherche"
    assert wording.ui(SCENARIOS)["page_chat"] == wording.ui(
        load_profile("default"))["page_chat"]
    assert set(wording.ui(KWP)) == set(wording.UI_REQUIRED)
    assert wording.axis_names(KWP)["year"] == "Jahr"
    assert wording.axis_names(SCENARIOS) == {}
    assert wording.readoff(KWP) == (
        "abgelesen", wording.chat_words(KWP)["readoff_note"])
    assert set(wording.graph_notes(KWP)) == set(kg_route.REASONS)
    assert wording.graph_notes(SCENARIOS) is None


# -- 3. what the chat cannot run without ------------------------------------------------------

def test_a_missing_word_and_a_name_of_no_family_are_refused(monkeypatch):
    whole = phrase_files.table(KWP, wording.CHAT)
    lacking = {key: value for key, value in whole.items()
               if key != "page_chat"}
    monkeypatch.setattr(phrase_files, "table", lambda profile, module: lacking)
    with pytest.raises(LookupError, match="page_chat"):
        wording.chat_words(KWP)
    wording._chat_checked.clear()
    stray = {**whole, "page_nowhere": "x"}
    monkeypatch.setattr(phrase_files, "table", lambda profile, module: stray)
    with pytest.raises(LookupError, match="page_nowhere"):
        wording.chat_words(KWP)
    wording._chat_checked.clear()
    named = {**whole, "axis_region": "Region", "graph_note_new": "x"}
    monkeypatch.setattr(phrase_files, "table", lambda profile, module: named)
    assert wording.axis_names(KWP)["region"] == "Region"
    # a reason the graph route does not know is refused where it is built
    with pytest.raises(LookupError, match="new"):
        kg_route.check_notes(wording.graph_notes(KWP), "test")


# -- 4. the readers outside the pages ---------------------------------------------------------

def test_the_kwp_picker_names_a_plans_version_in_the_profiles_words(
        monkeypatch):
    from docpipe.inference.catalog import load_catalog
    row = {"filename": "waermeplan_musterstadt.pdf", "published": "20240708",
           "is_current": 1, "municipality_name": "Musterstadt",
           "organisation_unit_name": None}
    words = wording.ui(KWP)
    catalog = load_catalog(KWP)
    assert catalog.label(row) \
        == f"Musterstadt · 2024-07-08 · {words['version_current']}"
    assert catalog.label({**row, "is_current": 0}).endswith(
        words["version_old"])
    # broken by construction: the label follows other words of the profile
    changed = {**wording.chat_words(KWP), "version_current": "(neu)"}
    monkeypatch.setitem(wording._chat_checked, KWP.name, changed)
    assert load_catalog(KWP).label(row).endswith("(neu)")


def test_the_doctor_checks_the_chat_words_under_their_file(monkeypatch):
    from docpipe import doctor

    def line():
        return {one.name: one for one in doctor.check_stages("chat", KWP)}[
            "prompts/chat/phrases.json"]
    assert line().status == doctor.OK
    # broken by construction: a word the file lacks fails the line

    def lacking(profile=None):
        raise LookupError("the chat words of profile 'kwp' are missing "
                          "['page_chat']")
    monkeypatch.setattr(wording, "chat_words", lacking)
    assert line().status == doctor.FAIL
    assert "page_chat" in line().detail
