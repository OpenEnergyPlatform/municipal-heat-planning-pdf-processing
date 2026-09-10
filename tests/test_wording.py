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

PROFILES = pathlib.Path(__file__).resolve().parent.parent / "profiles"


def _profiles_that_answer():
    """Profiles whose stages talk to a model, so they need the wording."""
    return sorted(p.name for p in PROFILES.iterdir()
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

    with pytest.raises(LookupError) as exc:
        wording.phrases(load_profile("kwp"))

    assert "history_heading" in str(exc.value)
    assert "task_heading" not in str(exc.value)
