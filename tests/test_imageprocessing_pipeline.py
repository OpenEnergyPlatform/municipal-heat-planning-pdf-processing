"""End-to-end tests for the parallel imageprocessing pipeline."""
import json
import types

from docpipe.visuals import config as C
from docpipe.visuals import pipeline as IP


def _write_input(tmp_path, sections):
    (tmp_path / "results").mkdir()
    (tmp_path / "images").mkdir()
    (tmp_path / "results" / "structured_output.json").write_text(
        json.dumps({"sections": sections}), encoding="utf-8")
    return tmp_path


def _fake_vllm_client_factory(reply):
    """create_client replacement returning a client that always replies *reply*."""
    def factory(base_url=None, timeout=None):
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                create=lambda **k: types.SimpleNamespace(
                    choices=[types.SimpleNamespace(
                        message=types.SimpleNamespace(content=reply))]))),
            models=types.SimpleNamespace(list=lambda: types.SimpleNamespace(
                data=[types.SimpleNamespace(id=C.VLM_MODEL)])),
        )
    return factory


def test_load_source_texts(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "structured_output.json").write_text(json.dumps({"sections": [
        {"tables": [{"id": "p1_tbl0", "source_text": "abc"}, {"id": "p1_tbl1"}],
         "figures": []},
    ]}), encoding="utf-8")
    assert IP._load_source_texts(tmp_path) == {"p1_tbl0": "abc"}


def test_load_source_texts_missing_file(tmp_path):
    assert IP._load_source_texts(tmp_path) == {}


def test_resolve_input_prefers_final_output(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "structured_output.json").write_text("{}", encoding="utf-8")
    assert IP._resolve_input(tmp_path).name == "structured_output.json"
    (tmp_path / "results" / "structured_output_final.json").write_text("{}", encoding="utf-8")
    assert IP._resolve_input(tmp_path).name == "structured_output_final.json"


def test_run_single_enriches_all_items_concurrently(tmp_path, monkeypatch):
    reply = '{"markdown": "MD", "description": "DESC", "caption": "CAP"}'
    monkeypatch.setattr(IP, "create_client", _fake_vllm_client_factory(reply))

    sections = [
        {"title": "S1", "page_number": 1, "content": "[p1_tbl0] [p1_img0]",
         "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png", "page_number": 1}],
         "figures": [{"id": "p1_img0", "path": "images/p1_img0.png", "page_number": 1}]},
        {"title": "S2", "page_number": 2, "content": "[p2_tbl0]",
         "tables": [{"id": "p2_tbl0", "path": "images/p2_tbl0.png", "page_number": 2}],
         "figures": []},
    ]
    out_dir = _write_input(tmp_path, sections)
    for name in ("p1_tbl0", "p1_img0", "p2_tbl0"):
        (out_dir / "images" / f"{name}.png").write_bytes(b"x")

    res = IP.run_single(out_dir)
    assert res is not None
    secs = res["sections"]
    assert secs[0]["tables"][0]["markdown"] == "MD"
    assert secs[0]["tables"][0]["caption"] == "CAP"
    assert secs[0]["figures"][0]["description"] == "DESC"
    assert secs[1]["tables"][0]["markdown"] == "MD"
    assert (out_dir / "results" / "structured_output_images.json").exists()


def test_run_single_reuses_cache_on_second_run(tmp_path, monkeypatch):
    reply = '{"markdown": "MD", "description": "DESC", "caption": "CAP"}'
    monkeypatch.setattr(IP, "create_client", _fake_vllm_client_factory(reply))
    sections = [{"title": "S", "content": "[p1_tbl0]",
                 "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png"}],
                 "figures": []}]
    out_dir = _write_input(tmp_path, sections)
    (out_dir / "images" / "p1_tbl0.png").write_bytes(b"x")

    IP.run_single(out_dir)
    # Second run: item already has markdown in the cache → no client needed.
    monkeypatch.setattr(IP, "create_client",
                        lambda **k: (_ for _ in ()).throw(AssertionError("should not call vLLM")))
    res2 = IP.run_single(out_dir)
    assert res2["sections"][0]["tables"][0]["markdown"] == "MD"


def test_run_single_never_leaks_source_text_on_crash(tmp_path, monkeypatch):
    # Even if a table worker crashes (res = item fallback), the QA-only
    # source_text field must never reach the enriched output.
    sections = [{"title": "S", "content": "[t]",
                 "tables": [{"id": "t", "path": "images/t.png", "source_text": "secret 1 2"}],
                 "figures": []}]
    out = _write_input(tmp_path, sections)
    (out / "images" / "t.png").write_bytes(b"x")
    monkeypatch.setattr(IP, "create_client",
                        _fake_vllm_client_factory('{"markdown": "| a |\\n| --- |\\n| 1 |"}'))

    def boom(*a, **k):
        raise RuntimeError("worker crash")

    monkeypatch.setattr(IP, "process_table", boom)
    res = IP.run_single(out)
    assert "source_text" not in res["sections"][0]["tables"][0]


def test_run_single_dry_run_writes_nothing(tmp_path):
    sections = [{"title": "S", "content": "[t]",
                 "tables": [{"id": "t", "path": "images/t.png"}], "figures": []}]
    out_dir = _write_input(tmp_path, sections)
    res = IP.run_single(out_dir, dry_run=True)
    assert res is not None
    assert not (out_dir / "results" / "structured_output_images.json").exists()
