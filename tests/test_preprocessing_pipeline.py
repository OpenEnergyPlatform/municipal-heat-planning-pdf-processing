"""Tests for the preprocessing folder index and CLI path resolution."""
import json

import pytest

from docpipe.preprocessing import pipeline as pp


def test_write_index_keys_by_relative_path_no_collision(tmp_path):
    results = {"a/report.pdf": {"sections": [1, 2]}, "b/report.pdf": None}
    dirs = {"a/report.pdf": str(tmp_path / "a" / "report"),
            "b/report.pdf": str(tmp_path / "b" / "report")}
    pp._write_index(results, tmp_path, dirs)

    idx = json.loads((tmp_path / "_index.json").read_text(encoding="utf-8"))
    assert set(idx) == {"a/report.pdf", "b/report.pdf"}        # same-name PDFs both kept
    assert idx["a/report.pdf"] == {
        "status": "ok",
        "output_dir": str(tmp_path / "a" / "report"), "sections": 2,
    }
    assert idx["b/report.pdf"]["status"] == "error"
    assert idx["b/report.pdf"]["output_dir"] == str(tmp_path / "b" / "report")


def test_write_index_flat_fallback(tmp_path):
    pp._write_index({"x.pdf": {"sections": []}}, tmp_path)
    idx = json.loads((tmp_path / "_index.json").read_text(encoding="utf-8"))
    assert idx["x.pdf"]["status"] == "ok"
    assert idx["x.pdf"]["output_dir"] == str(tmp_path / "x")


def test_a_lone_path_with_rebuild_stage3_is_the_processed_root(monkeypatch, tmp_path):
    """The rebuild takes no PDF input, so the single path anybody types is the
    root to rebuild — reading it as *input* silently rebuilt the profile's
    corpus instead of the named one (or died on a path that does not exist)."""
    seen = {}
    monkeypatch.setattr(pp, "run", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr("sys.argv",
                        ["prog", "--rebuild-stage3", str(tmp_path), "--profile", "kwp"])

    with pytest.raises(SystemExit) as exit_info:
        pp.main()

    assert exit_info.value.code == 0
    assert seen["output_dir"] == str(tmp_path)
    assert seen["input_path"] is None
    assert seen["rebuild_stage3"] is True


def test_two_paths_still_mean_input_then_output(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(pp, "run", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr("sys.argv",
                        ["prog", str(tmp_path / "in.pdf"), str(tmp_path / "out")])

    with pytest.raises(SystemExit):
        pp.main()

    assert seen["input_path"] == str(tmp_path / "in.pdf")
    assert seen["output_dir"] == str(tmp_path / "out")
