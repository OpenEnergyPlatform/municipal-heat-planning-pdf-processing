"""Tests for the preprocessing folder index (relative-path keying)."""
import json

from scripts.preprocessing import pipeline as pp


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
