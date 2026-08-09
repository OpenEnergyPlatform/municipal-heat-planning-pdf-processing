"""Prompt loading, overriding and versioning."""
import json

import pytest

from docpipe import prompts
from docpipe.profile import Profile


def test_core_prompts_exist_and_carry_text():
    for pid in ("refinement/refine", "visuals/table_system", "inference/answer_head"):
        assert len(prompts.load(pid, use_ambient=False).text) > 50


def test_front_matter_becomes_meta_and_leaves_the_body_alone():
    p = prompts.load("refinement/refine", use_ambient=False)
    assert p.meta["temperature"] == 0.1 and p.meta["max_tokens"] == 8192
    assert not p.text.startswith("---")


def test_body_is_passed_through_byte_for_byte(tmp_path):
    profile = _profile_with(tmp_path, "refinement/refine", "  vorne und hinten  \n\n")
    assert prompts.load("refinement/refine", profile).text == "  vorne und hinten  \n\n"


def test_profile_overrides_core(tmp_path):
    profile = _profile_with(tmp_path, "refinement/refine", "eigener Prompt")
    assert prompts.load("refinement/refine", profile).text == "eigener Prompt"
    # a prompt the profile does not override still comes from the core
    assert len(prompts.load("visuals/table_user", profile).text) > 50


def test_render_substitutes_and_catches_typos():
    p = prompts.Prompt(id="t/x", text="Hallo {{name}}!", meta={}, sha256="", path=None)
    assert p.render(name="Welt") == "Hallo Welt!"
    with pytest.raises(KeyError):
        p.render()
    with pytest.raises(KeyError):
        p.render(name="Welt", nmae="Tippfehler")


def test_hash_changes_with_the_file(tmp_path):
    before = prompts.load("refinement/refine", use_ambient=False).sha256
    profile = _profile_with(tmp_path, "refinement/refine", "anders")
    assert prompts.load("refinement/refine", profile).sha256 != before


def test_stale_reports_changed_and_unversioned_results():
    current = {"a": "1", "b": "2"}
    assert prompts.stale(current, current) == []
    assert prompts.stale({"a": "1", "b": "x"}, current) == ["b"]
    assert prompts.stale(None, current) == ["a", "b"]      # produced before versioning
    assert prompts.stale({"a": "1"}, current) == ["b"]      # prompt added later


def test_record_then_check_is_clean(tmp_path):
    ids = ["refinement/refine"]
    prompts.record(tmp_path, ids)
    assert json.loads((tmp_path / prompts.VERSION_FILE).read_text(encoding="utf-8"))
    assert prompts.check(tmp_path, ids) == []


def test_check_flags_a_changed_prompt(tmp_path):
    ids = ["refinement/refine"]
    prompts.record(tmp_path, ids)
    profile = _profile_with(tmp_path / "p", "refinement/refine", "anders")
    assert prompts.check(tmp_path, ids, profile) == ids


def test_check_flags_results_without_a_version_file(tmp_path):
    assert prompts.check(tmp_path, ["refinement/refine"]) == ["refinement/refine"]


def test_unusable_prompt_id():
    with pytest.raises(ValueError):
        prompts.core_path("ohne_stufe")


def _profile_with(root, prompt_id, text):
    """A profile whose prompts/ dir carries exactly one override."""
    path = root / "prompts" / f"{prompt_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return Profile(name="probe", data_root=root, home=root)
