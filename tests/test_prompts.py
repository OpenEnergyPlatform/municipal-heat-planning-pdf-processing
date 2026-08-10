"""Prompt loading and versioning. A prompt belongs to a profile."""
import json

import pytest

from docpipe import prompts
from docpipe.profile import Profile, load_profile


@pytest.fixture
def kwp():
    return load_profile("kwp")


def test_a_profile_ships_the_prompts_its_stages_load(kwp):
    for pid in ("refinement/refine", "visuals/table_system", "inference/answer_head"):
        assert len(prompts.load(pid, kwp).text) > 50


def test_front_matter_becomes_meta_and_leaves_the_body_alone(kwp):
    p = prompts.load("refinement/refine", kwp)
    assert p.meta["temperature"] == 0.1 and p.meta["max_tokens"] == 8192
    assert not p.text.startswith("---")


def test_body_is_passed_through_byte_for_byte(tmp_path):
    profile = _profile_with(tmp_path, "refinement/refine", "  vorne und hinten  \n\n")
    assert prompts.load("refinement/refine", profile).text == "  vorne und hinten  \n\n"


def test_a_prompt_the_profile_does_not_have_is_an_error(tmp_path):
    """There is nothing sensible to fall back to: a prompt names the corpus it
    was written for. Another project's prompt would run, and quietly tell the
    model it is looking at a document that is not in front of it."""
    profile = _profile_with(tmp_path, "refinement/refine", "eigener Prompt")

    assert prompts.load("refinement/refine", profile).text == "eigener Prompt"
    with pytest.raises(FileNotFoundError) as exc:
        prompts.load("visuals/table_user", profile)
    assert "probe" in str(exc.value) and "visuals/table_user" in str(exc.value)


def test_without_a_profile_there_is_no_prompt(monkeypatch):
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    with pytest.raises(LookupError):
        prompts.load("refinement/refine")


def test_render_substitutes_and_catches_typos():
    p = prompts.Prompt(id="t/x", text="Hallo {{name}}!", meta={}, sha256="", path=None)
    assert p.render(name="Welt") == "Hallo Welt!"
    with pytest.raises(KeyError):
        p.render()
    with pytest.raises(KeyError):
        p.render(name="Welt", nmae="Tippfehler")


def test_hash_changes_with_the_file(tmp_path, kwp):
    before = prompts.load("refinement/refine", kwp).sha256
    profile = _profile_with(tmp_path, "refinement/refine", "anders")
    assert prompts.load("refinement/refine", profile).sha256 != before


def test_stale_reports_changed_and_unversioned_results():
    current = {"a": "1", "b": "2"}
    assert prompts.stale(current, current) == []
    assert prompts.stale({"a": "1", "b": "x"}, current) == ["b"]
    assert prompts.stale(None, current) == ["a", "b"]      # produced before versioning
    assert prompts.stale({"a": "1"}, current) == ["b"]      # prompt added later


def test_record_then_check_is_clean(tmp_path, kwp):
    ids = ["refinement/refine"]
    prompts.record(tmp_path, ids, kwp)
    assert json.loads((tmp_path / prompts.VERSION_FILE).read_text(encoding="utf-8"))
    assert prompts.check(tmp_path, ids, kwp) == []


def test_check_flags_a_changed_prompt(tmp_path, kwp):
    ids = ["refinement/refine"]
    prompts.record(tmp_path, ids, kwp)
    profile = _profile_with(tmp_path / "p", "refinement/refine", "anders")
    assert prompts.check(tmp_path, ids, profile) == ids


def test_check_flags_results_without_a_version_file(tmp_path, kwp):
    assert prompts.check(tmp_path, ["refinement/refine"], kwp) == ["refinement/refine"]


def test_unusable_prompt_id(kwp):
    with pytest.raises(ValueError):
        prompts.path_for("ohne_stufe", kwp)


def _profile_with(root, prompt_id, text):
    """A profile whose prompts/ dir carries exactly one override."""
    path = root / "prompts" / f"{prompt_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return Profile(name="probe", data_root=root, home=root)
