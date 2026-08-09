"""Tests for docpipe.preprocessing.config (unicode cleaning, atomic JSON, paths)."""
import json

from docpipe.preprocessing import config


def test_clean_unicode_removes_surrogates():
    assert config.clean_unicode("Wärme\udfffplan") == "Wärmeplan"


def test_clean_unicode_nfkc_and_unassigned():
    assert config.clean_unicode("ﬁ") == "fi"                    # NFKC ligature split
    assert config.clean_unicode("a" + chr(0x0378) + "b") == "ab"  # unassigned (Cn) dropped


def test_clean_data_recurses_into_collections():
    out = config.clean_data({"a": ["x\udfff", {"b": "y\udfff"}], "n": 1})
    assert out == {"a": ["x", {"b": "y"}], "n": 1}


def test_result_paths_use_dir_results_prefix():
    assert config.PAGES_JSON == "results/pages.json"
    assert config.SECTIONS_JSON == "results/sections.json"


def test_dump_json_atomic_writes_and_leaves_no_temp(tmp_path):
    p = tmp_path / "sub" / "out.json"
    config.dump_json_atomic({"sections": [{"t": "ä"}]}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["sections"][0]["t"] == "ä"
    assert [f.name for f in p.parent.iterdir()] == ["out.json"]


def test_dump_json_atomic_keeps_old_file_on_error(tmp_path, monkeypatch):
    p = tmp_path / "out.json"
    p.write_text("OLD", encoding="utf-8")

    def boom(*a, **k):
        raise ValueError("nope")

    monkeypatch.setattr(config.json, "dump", boom)
    try:
        config.dump_json_atomic({"x": 1}, p)
    except ValueError:
        pass
    assert p.read_text(encoding="utf-8") == "OLD"        # original untouched
    assert [f.name for f in tmp_path.iterdir()] == ["out.json"]  # no temp residue
