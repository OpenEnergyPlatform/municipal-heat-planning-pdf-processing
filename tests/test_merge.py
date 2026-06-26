"""Step 1 merge: page provenance must survive into output.json untouched."""
import json

from scripts.chunkingandembedding import merge as M
from scripts.chunkingandembedding.config import FINAL_JSON, IMAGES_JSON


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
    _write(tmp_path / FINAL_JSON, final)
    _write(tmp_path / IMAGES_JSON, images)

    merged = M.merge_single(tmp_path)
    sec = merged["sections"][0]

    # Provenance carried through the merge unchanged…
    assert sec["pages"] == [5, 6]
    assert sec["page_number"] == 5
    assert sec["segments"] == final["sections"][0]["segments"]
    # …while the table is enriched in place with its markdown.
    assert sec["tables"][0]["markdown"] == "| a |"
