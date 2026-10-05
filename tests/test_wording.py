"""What the answer loop says around the prompts, and in whose language.

The prompts were the visible half. The other half is everything the loop wraps
around them — the heading over the task, the labels in the history block, the
sentence that tells the model to answer now, the words that give away a refusal
dressed up as a search anchor. All of it used to be German literals in the
core, which is invisible until a corpus arrives that is not German.
"""
import pathlib

import pytest

from docpipe.inference import wording
from docpipe.profile import Profile, load_profile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
BUILTIN = ROOT / "docpipe" / "builtin"


def _profiles_that_answer():
    """Profiles whose stages talk to a model, so they need the wording."""
    return sorted(p.name for root in (PROFILES, BUILTIN)
                  for p in root.iterdir()
                  if (p / "prompts" / "inference").is_dir())


@pytest.mark.parametrize("name", _profiles_that_answer())
def test_a_profile_that_answers_provides_all_of_it(name):
    profile = load_profile(name)

    assert wording.REQUIRED <= set(wording.phrases(profile))
    assert not hasattr(wording, "non_anchor")
    marker, note = wording.readoff(profile)
    assert marker and note


@pytest.mark.parametrize("name", _profiles_that_answer())
def test_the_readoff_note_contains_its_own_marker(name):
    """The note is appended unless the answer already says the values were read
    off. If the marker were not in the note, a second pass over the same answer
    would append it again."""
    marker, note = wording.readoff(load_profile(name))

    assert marker.casefold() in note.casefold()


def test_a_profile_without_the_module_is_named_in_the_error():
    with pytest.raises(LookupError) as exc:
        wording.phrases(Profile(name="doesnotexist"))

    assert "doesnotexist" in str(exc.value) and "inference.py" in str(exc.value)


def test_an_incomplete_set_says_which_pieces_are_missing(monkeypatch):
    """Half a set is worse than none: the loop runs and the model reads a
    KeyError-shaped hole only where that one label was used."""
    monkeypatch.setattr(wording, "_checked", {})
    monkeypatch.setattr(wording, "_component",
                        lambda attr, profile=None: {"task_heading": "Task"})

    # A profile that stands alone: one that extends another has asked for
    # that profile's pieces where it has none.
    with pytest.raises(LookupError) as exc:
        wording.phrases(Profile(name="kwp"))

    assert "history_heading" in str(exc.value)
    assert "task_heading" not in str(exc.value)


# -- the words of the app's pages ---------------------------------------------

APP = ROOT / "docpipe" / "app" / "app.py"


def _fields(text):
    import string
    return sorted(name for _lit, name, _spec, _conv
                  in string.Formatter().parse(text) if name)


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_a_profile_words_every_piece_of_the_pages_and_no_other(name):
    profile = load_profile(name)
    own = profile._own("inference", "UI")
    assert set(own) == set(wording.UI_REQUIRED), name
    assert wording.ui(profile) == own
    assert all(isinstance(text, str) and text.strip()
               for text in own.values())


def test_the_three_tables_take_the_same_values():
    """A page fills a sentence by name. A table that names another value,
    or none, fails on that page only, in that language only."""
    tables = {name: load_profile(name)._own("inference", "UI")
              for name in ("kwp", "scenarios", "default")}
    for key in sorted(wording.UI_REQUIRED):
        taken = {name: _fields(table[key]) for name, table in tables.items()}
        assert len({tuple(fields) for fields in taken.values()}) == 1, (
            key, taken)


def test_the_pages_use_every_word_and_only_words_there_are():
    import ast
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript)                 and isinstance(node.value, ast.Name) and node.value.id == "T":
            key = node.slice
            key = getattr(key, "value", key)        # Python 3.8: ast.Index
            key = getattr(key, "value", key)
            assert isinstance(key, str), "a page word is named literally"
            used.add(key)
    assert used == set(wording.UI_REQUIRED), (
        sorted(used - wording.UI_REQUIRED),
        sorted(wording.UI_REQUIRED - used))


def test_the_pages_say_nothing_that_is_not_in_a_table():
    """Every sentence a person reads is the profile's. A literal with a
    space and a letter in a call that puts text on the page would be one
    the profile cannot word."""
    import ast
    shows = {"markdown", "caption", "header", "subheader", "warning",
             "error", "info", "checkbox", "multiselect", "radio",
             "selectbox", "text_input", "text_area", "button",
             "link_button", "expander", "toast", "chat_input",
             "file_uploader", "title"}
    found = []
    for node in ast.walk(ast.parse(APP.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("st", "save", "skip")
                and node.func.attr in shows and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str)                 and " " in first.value.strip()                 and not first.value.lstrip().startswith("<"):
            found.append((node.lineno, first.value))
    assert not found, found


def test_without_a_profile_the_pages_speak_the_built_in_profile_s_words(
        monkeypatch):
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    monkeypatch.setattr(wording, "_ui_checked", {})
    assert wording.ui() == load_profile("default")._own("inference", "UI")


def test_a_table_with_a_piece_too_few_or_too_many_is_named(monkeypatch):
    monkeypatch.setattr(wording, "_ui_checked", {})
    profile = load_profile("default")
    short = dict(profile._own("inference", "UI"))
    del short["open_pdf"]
    short["greeting"] = "Hello"
    monkeypatch.setattr(type(profile), "layers",
                        lambda self, module, attr: [short])
    with pytest.raises(LookupError) as caught:
        wording.ui(profile)
    assert "open_pdf" in str(caught.value) and "greeting" in str(caught.value)
