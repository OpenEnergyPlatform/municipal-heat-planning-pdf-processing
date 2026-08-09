"""Step 1 merge: page provenance must survive into output.json untouched."""
import json
import os

from docpipe.chunking import merge as M
from docpipe.chunking.config import SECTIONS_REFINED_JSON, VISUALS_JSON, DOCUMENT_JSON


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_merge_preserves_segments_and_pages_and_enriches_media(tmp_path):
    final = {"sections": [{
        "title": "Bestand", "content": "Absatz [p5_tbl0]",
        "page_number": 5, "pages": [5, 6],
        "segments": [{"page": 5, "kind": "text", "text": "Absatz"},
                     {"page": 6, "kind": "table", "ref": "p5_tbl0"}],
        "tables": [{"id": "p5_tbl0", "path": "images/p5_tbl0.png", "page_number": 6, "caption": "T"}],
        "figures": [],
    }]}
    images = {"sections": [{
        "tables": [{"id": "p5_tbl0", "path": "images/p5_tbl0.png", "page_number": 6,
                    "caption": "T", "markdown": "| a |"}],
        "figures": [],
    }]}
    _write(tmp_path / SECTIONS_REFINED_JSON, final)
    _write(tmp_path / VISUALS_JSON, images)

    merged = M.merge_single(tmp_path)
    sec = merged["sections"][0]

    # Provenance carried through the merge unchanged…
    assert sec["pages"] == [5, 6]
    assert sec["page_number"] == 5
    assert sec["segments"] == final["sections"][0]["segments"]
    # …while the table is enriched in place with its markdown.
    assert sec["tables"][0]["markdown"] == "| a |"


_FINAL = {"sections": [{"title": "T", "content": "c", "tables": [], "figures": []}]}


def _doc(root, name, merged=None):
    """A PDF output dir with a final JSON and, optionally, a cached merged one."""
    d = root / name
    _write(d / SECTIONS_REFINED_JSON, _FINAL)
    if merged is not None:
        _write(d / DOCUMENT_JSON, merged)
    return d


def _count_loads(monkeypatch):
    calls = []
    real = json.load
    monkeypatch.setattr(M.json, "load", lambda f: (calls.append(1), real(f))[1])
    return calls


def test_merge_batch_skips_cached_dirs_without_parsing(tmp_path, monkeypatch):
    _doc(tmp_path, "cached", merged=_FINAL)
    _doc(tmp_path, "fresh")
    loads = _count_loads(monkeypatch)

    results = M.merge_batch(tmp_path)

    assert results == {"cached": True, "fresh": True}
    # Only the fresh dir may be read: re-parsing every cached output.json just to
    # return a dict merge_batch discards costs a full corpus re-read per run.
    assert len(loads) == 1


def test_merge_batch_force_remerges_cached_dir(tmp_path, monkeypatch):
    d = _doc(tmp_path, "cached", merged={"sections": [{"title": "STALE"}]})
    loads = _count_loads(monkeypatch)

    assert M.merge_batch(tmp_path, force=True) == {"cached": True}

    assert len(loads) == 1
    assert json.loads((d / DOCUMENT_JSON).read_text(encoding="utf-8")) == _FINAL


def _touch_newer(path, reference):
    stamp = reference.stat().st_mtime + 10
    os.utime(path, (stamp, stamp))


def test_merge_batch_remerges_when_final_json_is_newer(tmp_path):
    d = _doc(tmp_path, "cached", merged={"sections": [{"title": "STALE"}]})
    _touch_newer(d / SECTIONS_REFINED_JSON, d / DOCUMENT_JSON)

    M.merge_batch(tmp_path)

    # A re-run of Stage 4 must invalidate the cache, or its output never lands.
    assert json.loads((d / DOCUMENT_JSON).read_text(encoding="utf-8")) == _FINAL


def test_merge_batch_remerges_when_images_json_is_newer(tmp_path):
    d = _doc(tmp_path, "cached", merged={"sections": [{"title": "STALE"}]})
    _write(d / VISUALS_JSON, {"sections": []})
    _touch_newer(d / VISUALS_JSON, d / DOCUMENT_JSON)

    M.merge_batch(tmp_path)

    # Stage 5 rewrites its JSON on every run, including a fully cached one. Miss
    # that and its enrichment never reaches the merge — and the section_text
    # embedding built from the un-enriched content is never rebuilt either.
    assert json.loads((d / DOCUMENT_JSON).read_text(encoding="utf-8")) == _FINAL


def test_merge_batch_remerges_a_zero_byte_output(tmp_path):
    d = _doc(tmp_path, "cached", merged={"sections": [{"title": "STALE"}]})
    (d / DOCUMENT_JSON).write_bytes(b"")
    _touch_newer(d / DOCUMENT_JSON, d / SECTIONS_REFINED_JSON)

    M.merge_batch(tmp_path)

    # Newer than its inputs, so only the size guard can reject it.
    assert json.loads((d / DOCUMENT_JSON).read_text(encoding="utf-8")) == _FINAL


def test_merge_keeps_the_previous_output_when_the_write_fails(tmp_path, monkeypatch):
    stale = {"sections": [{"title": "STALE"}]}
    d = _doc(tmp_path, "cached", merged=stale)
    _touch_newer(d / SECTIONS_REFINED_JSON, d / DOCUMENT_JSON)

    def _boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(M.json, "dump", _boom)
    M.merge_batch(tmp_path)

    # A failed re-merge must leave the usable cache in place and no .part behind.
    assert json.loads((d / DOCUMENT_JSON).read_text(encoding="utf-8")) == stale
    assert not (d / (DOCUMENT_JSON + ".part")).exists()


def test_merge_batch_reports_failure_for_invalid_final_json(tmp_path):
    d = tmp_path / "broken"
    (d / SECTIONS_REFINED_JSON).parent.mkdir(parents=True, exist_ok=True)
    (d / SECTIONS_REFINED_JSON).write_text("{ not json", encoding="utf-8")

    # A single bad document must not abort the batch.
    assert M.merge_batch(tmp_path) == {"broken": False}
    assert not (d / DOCUMENT_JSON).exists()


def test_merge_batch_contains_an_unreadable_cache_entry(tmp_path, monkeypatch):
    _doc(tmp_path, "broken", merged=_FINAL)
    _doc(tmp_path, "ok")
    real = M.Path.stat

    def _stat(self, *a, **k):
        if self.name == "output.json" and "broken" in str(self):
            raise OSError(5, "I/O error")
        return real(self, *a, **k)

    monkeypatch.setattr(M.Path, "stat", _stat)

    # The cache probe runs outside merge_single's error handling, so an I/O error
    # there must not take the whole corpus down with it.
    assert set(M.merge_batch(tmp_path)) == {"broken", "ok"}
