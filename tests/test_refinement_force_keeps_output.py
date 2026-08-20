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
    def die(sections, report=None):
        assert _final(doc).exists(), "the old output was deleted before the LLM ran"
        raise KeyboardInterrupt("timeout 30m")

    monkeypatch.setattr(R, "refine_sections", die)

    with pytest.raises(KeyboardInterrupt):
        R.run_refine(doc, force=True)

    assert json.loads(_final(doc).read_text(encoding="utf-8")) == {
        "sections": [{"title": "old", "content": "old"}]}


def test_a_forced_run_that_finishes_replaces_the_output(doc, monkeypatch):
    monkeypatch.setattr(R, "refine_sections",
                        lambda sections, report=None: [{"title": "new", "content": "new"}])

    out = R.run_refine(doc, force=True)

    assert out["sections"] == [{"title": "new", "content": "new"}]
    assert json.loads(_final(doc).read_text(encoding="utf-8"))["sections"] == [
        {"title": "new", "content": "new"}]


def test_without_force_the_cache_still_short_circuits(doc, monkeypatch):
    monkeypatch.setattr(R, "refine_sections",
                        lambda sections, report=None: pytest.fail("the LLM must not run"))

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


def test_the_stage_records_which_windows_kept_their_originals(doc, monkeypatch):
    """A failed window keeps its original text, which in corrections mode looks
    exactly like a window that needed no change. Guessing from the output read
    a clean corpus as 31 broken documents; the stage records it instead."""
    monkeypatch.setattr(R, "WINDOW_SIZE", 1)
    (doc / "results" / "sections.json").write_text(json.dumps({"sections": [
        {"title": "A", "content": "a"}, {"title": "B", "content": "b"}]}),
        encoding="utf-8")
    monkeypatch.setattr(R, "_call_llm",
                        lambda window, client=None, prev_ctx=None:
                        None if window[0]["title"] == "B" else list(window))
    monkeypatch.setattr(R, "OpenAI", None, raising=False)
    monkeypatch.setattr(R, "_make_splitter", lambda client: None)
    monkeypatch.setattr(R, "split_oversized", lambda sections, ask=None: sections)

    R.run_refine(doc, force=True)

    report = json.loads(
        (doc / "results" / "refinement_report.json").read_text(encoding="utf-8"))
    assert report["total_windows"] == 2
    assert [f["window"] for f in report["failed_windows"]] == [2]
    assert report["failed_windows"][0]["titles"] == ["B"]
    assert report["failed_windows"][0]["sections"] == [1]


def test_a_clean_run_records_an_empty_list_not_a_missing_file(doc, monkeypatch):
    """Empty list means 'checked, nothing failed'; a missing file means nobody
    looked. The old detector could not tell those apart."""
    monkeypatch.setattr(R, "refine_sections",
                        lambda sections, report=None: report.update(
                            {"total_windows": 1, "failed_windows": []}) or sections)

    R.run_refine(doc, force=True)

    report = json.loads(
        (doc / "results" / "refinement_report.json").read_text(encoding="utf-8"))
    assert report == {"total_windows": 1, "failed_windows": []}
