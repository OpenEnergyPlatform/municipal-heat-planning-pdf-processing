"""Forcing a re-refine must never leave the document with nothing.

The old --force deleted sections_refined.json and only wrote it again at the
end. A run killed in between — a per-document timeout, a job hitting its wall
clock — left the document with no refined output at all, and merge.py skips
those without a word: the document would silently vanish from the database.
"""
import json

import pytest

from docpipe.refinement import pipeline as RP
from docpipe.refinement import refine as R


@pytest.fixture
def doc(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "sections.json").write_text(
        json.dumps({"sections": [{"title": "T", "content": "c"}]}), encoding="utf-8")
    (tmp_path / "results" / "sections_refined.json").write_text(
        json.dumps({"sections": [{"title": "old", "content": "old"}]}), encoding="utf-8")
    return tmp_path


def _final(doc):
    return doc / "results" / "sections_refined.json"


def test_a_forced_run_that_dies_leaves_the_previous_refinement(doc, monkeypatch):
    """The whole point: killed part-way, the old output is still there."""
    def die(sections):
        assert _final(doc).exists(), "the old output was deleted before the LLM ran"
        raise KeyboardInterrupt("timeout 30m")

    monkeypatch.setattr(R, "refine_sections", die)

    with pytest.raises(KeyboardInterrupt):
        R.run_refine(doc, force=True)

    assert json.loads(_final(doc).read_text(encoding="utf-8")) == {
        "sections": [{"title": "old", "content": "old"}]}


def test_a_forced_run_that_finishes_replaces_the_output(doc, monkeypatch):
    monkeypatch.setattr(R, "refine_sections",
                        lambda sections: [{"title": "new", "content": "new"}])

    out = R.run_refine(doc, force=True)

    assert out["sections"] == [{"title": "new", "content": "new"}]
    assert json.loads(_final(doc).read_text(encoding="utf-8"))["sections"] == [
        {"title": "new", "content": "new"}]


def test_without_force_the_cache_still_short_circuits(doc, monkeypatch):
    monkeypatch.setattr(R, "refine_sections",
                        lambda sections: pytest.fail("the LLM must not run"))

    out = R.run_refine(doc)

    assert out["sections"] == [{"title": "old", "content": "old"}]


def test_run_single_passes_force_through_instead_of_unlinking(doc, monkeypatch):
    seen = {}
    monkeypatch.setattr(RP, "run_refine",
                        lambda d, force=False: seen.setdefault("force", force) or {"sections": []})
    monkeypatch.setattr(RP.prompts, "check", lambda *a, **k: [])
    monkeypatch.setattr(RP.prompts, "record", lambda *a, **k: None)

    RP.run_single(doc, force=True)

    assert seen["force"] is True
    assert _final(doc).exists(), "run_single must not delete it either"
