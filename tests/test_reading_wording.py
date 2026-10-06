"""What the refinement, visuals and page-transcription stages say to the model
when its reply was not the one JSON object that was asked for.

Promised: the sentences are the profile's (`reading.py: PHRASES`) AND every
profile has every one of them with the same names to fill in AND a profile
that lacks one is told which, before the first request of a stage.
"""
import string

import pytest

from docpipe import reading
from docpipe.profile import Profile, load_profile


def _names(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_every_profile_says_every_sentence_with_the_same_names(name):
    own = load_profile(name)._own("reading", "PHRASES")
    assert set(own) == reading.REQUIRED
    reference = load_profile("default")._own("reading", "PHRASES")
    for key, text in own.items():
        assert isinstance(text, str) and text, key
        assert _names(text) == _names(reference[key]), key


def test_the_names_the_core_fills_in_are_the_ones_the_sentences_take():
    """The core hands over these names; a sentence that asks for another one
    fails on the first reply it is used for, hours into a run."""
    table = load_profile("default")._own("reading", "PHRASES")
    assert {key: _names(text) for key, text in table.items() if _names(text)} \
        == {"syntax": {"position", "message", "around"},
            "outside_text": {"extra"}, "not_an_object": {"kind"},
            "key_missing": {"key"}, "key_not_a_list": {"key"},
            "key_not_text": {"key"}}


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_a_profile_says_them_in_the_language_of_its_stage_prompts(name):
    """The prompts of these three stages are English in every profile; the
    German of the harvest's table (extraction.PHRASES) is not this table."""
    own = load_profile(name)._own("reading", "PHRASES")
    umlauts = [key for key, text in own.items()
               if any(char in text for char in "äöüßÄÖÜ")]
    assert not umlauts, umlauts
    assert own["empty"] == "Your answer was empty."


def test_a_profile_that_lacks_a_sentence_is_told_which(monkeypatch):
    monkeypatch.setattr(reading, "_checked", {})
    own = dict(load_profile("default")._own("reading", "PHRASES"))
    del own["key_not_text"]
    half = Profile(name="kwp")          # stands alone: nothing to fall back on
    monkeypatch.setattr(
        Profile, "_own",
        lambda self, module, attr: own
        if (module, attr) == ("reading", "PHRASES") else None)
    with pytest.raises(LookupError) as refused:
        reading.phrases(half)
    assert "key_not_text" in str(refused.value)
    assert "'empty'" not in str(refused.value)


def _refinement(tmp_path):
    from docpipe.refinement import pipeline
    return pipeline, ["refinement", str(tmp_path)]


def _visuals(tmp_path):
    from docpipe.visuals import pipeline
    return pipeline, ["visuals", str(tmp_path)]


def _pages(tmp_path):
    from docpipe.preprocessing import pipeline
    return pipeline, ["preprocessing", str(tmp_path / "in.pdf"),
                      str(tmp_path / "out"), "--transcribe-missing-text"]


@pytest.mark.parametrize("stage", [_refinement, _visuals, _pages])
def test_each_stage_checks_the_sentences_before_its_first_request(
        stage, tmp_path, monkeypatch):
    """The case that violates it by construction: a profile that lacks a
    sentence. The stage has to stop on it before the server is asked anything,
    not on the first reply that needed the sentence."""
    import sys

    module, argv = stage(tmp_path)
    asked = []

    def lacks(*args, **kwargs):
        raise LookupError("reading.PHRASES lacks 'key_not_text'")

    monkeypatch.setattr(reading, "phrases", lacks)
    for name in ("assert_serving", "_assert_page_server"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name,
                                lambda *a, **k: asked.append(name))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(LookupError, match="key_not_text"):
        module.main()
    assert asked == [], "the server was asked before the profile was checked"


@pytest.mark.parametrize("stage, extra", [
    (_refinement, ["--print-context-budget"]),
    (_visuals, ["--print-context-budget"]),
    (_visuals, ["--dry-run"]),
])
def test_a_run_that_asks_nothing_of_the_model_needs_no_sentence(
        stage, extra, tmp_path, monkeypatch, capsys):
    """Printing the budget and a dry run end as they did for a profile that
    has no reading table: the command's exit code keeps its meaning. The
    profile that lacks a sentence is the case that violates it."""
    import sys

    module, argv = stage(tmp_path)

    def lacks(*args, **kwargs):
        raise LookupError("reading.PHRASES lacks 'key_not_text'")

    monkeypatch.setattr(reading, "phrases", lacks)
    monkeypatch.setattr(sys, "argv", [*argv, *extra])
    with pytest.raises(SystemExit) as stopped:
        module.main()
    if "--print-context-budget" in extra:
        assert stopped.value.code == 0
        assert capsys.readouterr().out.strip().isdigit()


def test_a_profile_without_the_table_is_told_it_provides_none(monkeypatch):
    monkeypatch.setattr(reading, "_checked", {})
    monkeypatch.setattr(Profile, "_own", lambda self, module, attr: None)
    with pytest.raises(LookupError, match="provides no reading.PHRASES"):
        reading.phrases(Profile(name="kwp"))


def test_one_sentence_is_laid_over_the_extended_profile_s(tmp_path,
                                                          monkeypatch):
    # Its own name: a profile package is cached by name for the whole run,
    # and another test's "worded" lives in another folder.
    home = tmp_path / "worded_reading"
    home.mkdir()
    (home / "__init__.py").write_text("", encoding="utf-8")
    (home / "profile.py").write_text(
        "from docpipe.profile import Profile\n"
        "PROFILE = Profile(name='worded_reading', extends='default')\n",
        encoding="utf-8")
    (home / "reading.py").write_text(
        "PHRASES = {'empty': 'Nothing came back.'}\n", encoding="utf-8")
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))
    monkeypatch.setattr(reading, "_checked", {})
    got = reading.phrases(load_profile("worded_reading"))
    base = load_profile("default")._own("reading", "PHRASES")
    assert got["empty"] == "Nothing came back."
    assert {k: v for k, v in got.items() if k != "empty"} == \
        {k: v for k, v in base.items() if k != "empty"}
