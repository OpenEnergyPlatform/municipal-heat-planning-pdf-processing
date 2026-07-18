"""Building embedding inputs: VL inputs follow the crops that exist on disk."""
import pytest

from scripts.chunkingandembedding import chunking as CH
from scripts.chunkingandembedding import config as C

_MERGED = {
    "sections": [
        {"title": "Bestand", "content": "Absatz [p5_tbl0]",
         "tables": [{"id": "p5_tbl0", "path": "images/p5_tbl0.png", "caption": "T",
                     "markdown": "| a |"},
                    {"id": "p6_tbl0", "path": "images/p6_tbl0.png", "caption": "U",
                     "markdown": "| b |"}],
         "figures": [{"id": "p5_img0", "path": "images/p5_img0.png", "caption": "K",
                      "description": "Karte"}]},
        {"title": "Potenziale", "content": "[p8_img0]", "tables": [],
         "figures": [{"id": "p8_img0", "path": "images/p8_img0.png", "caption": "P",
                      "description": "Plan"}]},
    ]
}


def _crops(tmp_path, *names):
    (tmp_path / "images").mkdir(parents=True, exist_ok=True)
    for n in names:
        (tmp_path / "images" / n).write_bytes(b"png")
    return tmp_path


def _vl_ids(inputs):
    return sorted(i.item_id for i in inputs
                  if i.embedding_type in (C.EMBEDDING_TYPE_TABLE_VL,
                                          C.EMBEDDING_TYPE_FIGURE_VL))


def test_build_inputs_emits_vl_only_for_crops_on_disk(tmp_path):
    _crops(tmp_path, "p5_tbl0.png", "p8_img0.png")

    inputs = CH.build_embedding_inputs(_MERGED, "doc", tmp_path)

    # A crop Stage 2 never wrote must not become a VL input pointing at nothing.
    assert _vl_ids(inputs) == ["p5_tbl0", "p8_img0"]
    assert all(i.image is None for i in inputs if i.item_id == "p6_tbl0")


def test_build_inputs_reads_each_crop_directory_once(tmp_path, monkeypatch):
    _crops(tmp_path, "p5_tbl0.png", "p6_tbl0.png", "p5_img0.png", "p8_img0.png")
    calls = []
    real = CH.os.listdir
    monkeypatch.setattr(CH.os, "listdir", lambda p: (calls.append(p), real(p))[1])

    inputs = CH.build_embedding_inputs(_MERGED, "doc", tmp_path)

    assert _vl_ids(inputs) == ["p5_img0", "p5_tbl0", "p6_tbl0", "p8_img0"]
    # One listing per directory, not a stat() per crop: the corpus holds ~85k
    # crops and metadata calls dominate on a parallel filesystem.
    assert len(calls) == 1


def test_build_inputs_does_not_hide_an_unreadable_crop_directory(tmp_path, monkeypatch):
    _crops(tmp_path, "p5_tbl0.png")

    def _boom(_):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(CH.os, "listdir", _boom)

    # Reading an I/O error as "no crops" would drop every VL input of the
    # document, and nothing in the DB would record that they were ever missing.
    with pytest.raises(OSError):
        CH.build_embedding_inputs(_MERGED, "doc", tmp_path)


def test_build_inputs_survives_a_missing_crop_directory(tmp_path):
    inputs = CH.build_embedding_inputs(_MERGED, "doc", tmp_path)

    assert _vl_ids(inputs) == []
    assert {i.embedding_type for i in inputs} == {
        C.EMBEDDING_TYPE_SECTION_TEXT, C.EMBEDDING_TYPE_SECTION_TITLE,
        C.EMBEDDING_TYPE_TABLE_TEXT, C.EMBEDDING_TYPE_FIGURE_TEXT,
    }
