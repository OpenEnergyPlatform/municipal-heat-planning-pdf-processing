"""The sentences a stage says outside its prompts are files beside the
prompts (`prompts/<module>/phrases.json`, owner decision 2026-11-10), read
strictly and laid over those of the profile a profile extends; and what the
editor does with them.

Each test states one promise and holds a case that breaks it by
construction.

Measured once, on 2026-11-10, when the sentences left the profiles' Python
modules: every stage got the same sentences from the files as from the
tables (9 tables, 291 sentences, in order, a tuple still a tuple), and the
smoke probe of both profiles sent the same requests before and after, text
for text (338 requests of kwp, 108 of scenarios)."""
import dataclasses
import json
from pathlib import Path

import pytest

from docpipe import phrases, reading
from docpipe.editor import phrases as edited
from docpipe.extraction import wording
from docpipe.profile import load_profile

DEFAULT = load_profile("default")
KWP = load_profile("kwp")
SCENARIOS = load_profile("scenarios")


def read(path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def file_of(profile, module: str) -> dict:
    return json.loads(phrases.path_of(profile, module).read_text("utf-8"))


def lone(tmp_path: Path, name: str, table) -> object:
    """A profile that extends none, with *table* as its reading
    sentences (None: no file)."""
    profile = dataclasses.replace(DEFAULT, name=name, home=tmp_path)
    if table is not None:
        path = phrases.path_of(profile, "reading")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(table), encoding="utf-8")
    return profile


# -- the files are the sentences of a run -----------------------------------------

def test_a_profile_takes_the_sentences_it_does_not_word_from_the_one_it_extends():
    own, base = file_of(SCENARIOS, "extraction"), file_of(DEFAULT,
                                                           "extraction")
    got = wording.phrases(SCENARIOS)
    inherited = sorted(set(base) - set(own))
    assert inherited and all(got[key] == base[key] for key in inherited)
    differing = [key for key in own if own[key] != base.get(key)]
    assert differing and all(got[key] == own[key] for key in differing)
    assert list(got)[:len(base)] == list(base)      # in the order of the file
    # a list of words reaches the stage as the tuple it always was
    from docpipe.inference import wording as said
    assert said.phrases(KWP)["citation_quotes"] == tuple(
        file_of(KWP, "inference")["citation_quotes"])


def test_a_follow_up_says_the_sentence_as_the_file_words_it(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    template = file_of(KWP, "extraction")["not_an_option"]
    assert "{given!r}" in template
    assert wording.say("not_an_option", given="7") == template.format(
        given="7")


@pytest.mark.parametrize("text, said", [
    ('{"a": "x", "a": "y"}', "'a' stands twice"),
    ('["a"]', "one JSON object"),
    ('{"a": 1}', "neither a string nor a list"),
    ('{"a": ["x", 2]}', "neither a string nor a list"),
    ('{"a": []}', "neither a string nor a list"),
    ('{"": "x"}', "without a name"),
    ('{"a": "x"', "phrases.json"),
])
def test_a_sentence_file_is_read_strictly(text, said):
    with pytest.raises(phrases.PhrasesError, match=said) as caught:
        phrases.parse(text, "prompts/x/phrases.json")
    assert "prompts/x/phrases.json" in str(caught.value)
    assert phrases.parse('{"a": "x", "b": ["“", "”"]}', "f") == {
        "a": "x", "b": ("“", "”")}


def test_a_stage_names_the_sentence_it_cannot_run_without(tmp_path):
    whole = file_of(DEFAULT, "reading")
    assert reading.phrases(lone(tmp_path / "a", "lone_whole", whole)) == whole
    less = {key: value for key, value in whole.items() if key != "syntax"}
    with pytest.raises(LookupError, match="syntax") as caught:
        reading.phrases(lone(tmp_path / "b", "lone_less", less))
    assert "phrases.json" in str(caught.value)
    with pytest.raises(LookupError, match="writes no sentences"):
        reading.phrases(lone(tmp_path / "c", "lone_none", None))


# -- the editor ------------------------------------------------------------------

def own_table(profile, module: str) -> dict:
    return dict(edited.detail(profile, module, read)["table"])


def test_the_page_gets_the_file_back_when_nothing_is_changed():
    for profile in (DEFAULT, KWP, SCENARIOS):
        for module in phrases.MODULES:
            report = edited.judge(profile, module,
                                  own_table(profile, module), read)
            assert report["ok"] and report["changed"] is False
            assert report["text"].encode("utf-8") == read(
                phrases.path_of(profile, module))


@pytest.mark.parametrize("key, change, said", [
    ("not_an_option", lambda text: text + " {foo}", "uses {foo}"),
    ("not_an_option", lambda text: text + " {", "no template"),
    ("not_an_option", lambda text: text + " {0}", "no template"),
    ("empty", lambda text: text + " {given}", "has a brace"),
    ("empty", lambda text: [text], "is one text"),
    ("no_such_sentence", lambda text: "x", "no stage reads"),
])
def test_a_sentence_the_code_cannot_fill_is_not_written(key, change, said):
    table = own_table(SCENARIOS, "extraction")
    table[key] = change(table.get(key))
    report, data, _ = edited.save(SCENARIOS, "extraction", table, read)
    assert report["ok"] is False and report["where"] == key
    assert said in report["error"] and data is None
    assert report["reason"] == "check"


def test_a_reworded_sentence_with_the_same_names_is_written():
    table = own_table(SCENARIOS, "extraction")
    table["not_an_option"] = "{given!r} is no entry. Pick one of the list."
    report, data, target = edited.save(SCENARIOS, "extraction", table, read)
    assert report["ok"] and report["saved"]
    assert [change["key"] for change in report["changes"]] == [
        "not_an_option"]
    assert json.loads(data.decode("utf-8")) == table
    assert list(json.loads(data.decode("utf-8"))) == list(table)
    assert target == phrases.path_of(SCENARIOS, "extraction")
    assert report["lines"] == {"added": 1, "removed": 1}
    # a list of words stays a list of as many
    quotes = own_table(KWP, "inference")
    quotes["citation_quotes"] = ["«"]
    assert "list of 2" in edited.judge(KWP, "inference", quotes,
                                       read)["error"]


def test_an_own_sentence_is_taken_away_only_after_it_is_confirmed():
    table = own_table(SCENARIOS, "extraction")
    del table["not_an_option"]
    report, data, _ = edited.save(SCENARIOS, "extraction", table, read)
    assert data is None and report["reason"] == "confirm"
    (gone,) = report["removed"]
    assert gone["key"] == "not_an_option"
    assert gone["after"] == file_of(DEFAULT, "extraction")["not_an_option"]
    report, data, _ = edited.save(SCENARIOS, "extraction", table, read,
                                  confirm=True)
    assert report["saved"] and "not_an_option" not in json.loads(data)
    # the failure by construction: a sentence no extended profile words
    # cannot go, confirmed or not
    whole = own_table(DEFAULT, "extraction")
    del whole["not_an_option"]
    report, data, _ = edited.save(DEFAULT, "extraction", whole, read,
                                  confirm=True)
    assert data is None and "not_an_option" in report["error"]


def test_a_sentence_is_found_where_a_recorded_request_shows_it():
    old = file_of(SCENARIOS, "extraction")["not_an_option"]
    shown = old.format(given="31,35")
    requests = [
        {"kind": "follow", "asked": "list", "messages": [["user", json.dumps(
            {"answer": {"entry": "31,35"}, "what": [shown]}, indent=1)
            + "\n\nAnswer once more."]]},
        {"kind": "coord", "messages": [["user", json.dumps(
            {"question": "Which year?"})]]},
    ]
    got = edited.shown_in(requests, old, old)
    assert (got["searched"], got["found"]) == (2, 1)
    (row,) = got["shown"]
    assert row["index"] == 0 and row["before"] == row["after"] == shown
    new = "No entry: {given!r}."
    assert edited.shown_in(requests, old, new)["shown"][0]["after"] == (
        "No entry: '31,35'.")
    # shown as the model wrote it where the new wording drops the quotes
    assert edited.shown_in(requests, old, "No entry: {given}.")[
        "shown"][0]["after"] == "No entry: 31,35."
    # the failure by construction: a name the record does not show
    lacking = edited.shown_in(requests, old, "{given!r} is not {wrong}.")
    assert lacking["shown"][0]["after"] is None
    assert "wrong" in lacking["shown"][0]["why"]
