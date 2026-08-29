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
    assert wording.non_anchor(profile).search("") is None       # a usable pattern
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


# ---------------------------------------------------------------------------
# The pattern that has to fire in its own language
# ---------------------------------------------------------------------------

REFUSALS = {
    "kwp": ["Diese Angabe ist im bereitgestellten Kontext nicht enthalten.",
            "Dazu liegen keine Daten vor.",
            "Das lässt sich aus den Auszügen nicht ermitteln.",
            "Es ist keine Abbildung mit ähnlichen Angaben vorhanden."],
    "scenarios": ["This is not reported in the provided context.",
            "No data available for this scenario.",
            "The value cannot be determined from the excerpts.",
            "There is no figure showing that."],
}

ANCHORS = {
    "kwp": ["Die Gemeinde hat 19.499 Einwohner und eine Fläche von 24 km².",
            "Abbildung 3: Wärmebedarf nach Sektoren im Jahr 2035."],
    "scenarios": ["The scenario reaches net-zero CO2 emissions in 2050.",
            "Figure 3: Final energy demand by sector under SSP2-1.9."],
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_refusal_in_the_profiles_language_is_recognised(name):
    """A refusal that slips through is used as the retrieval probe, and the
    correction turn that would have caught it never runs."""
    pattern = wording.non_anchor(load_profile(name))

    for text in REFUSALS[name]:
        assert pattern.search(text), text


@pytest.mark.parametrize("name", sorted(ANCHORS))
def test_a_real_anchor_is_left_alone(name):
    pattern = wording.non_anchor(load_profile(name))

    for text in ANCHORS[name]:
        assert not pattern.search(text), text
