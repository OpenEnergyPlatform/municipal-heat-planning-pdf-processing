"""
Source-PDF geometry (bbox) threaded end-to-end: Stage 3 emits it, Stage 4
carries/reattaches it, image processing passes it through, the DB stores it, and
the additive `enrich_bbox` backfill lands it on an already-embedded corpus
without touching anything else.

bbox convention everywhere: a JSON list of one or more [x0, y0, x1, y1] rects in
PDF points (top-left origin). Text segment → one rect per constituent block;
table/figure → its single region rect.
"""
import json

from scripts.preprocessing.models import Block, PageData, TableRef, FigureRef
from scripts.preprocessing import stage3_structure as s3
from scripts.textrefinement import refine as s4
from scripts.chunkingandembedding import database as DB
from scripts.chunkingandembedding import config as C


def _page(n, blocks):
    pg = PageData(page_number=n, width_pt=595.0, height_pt=842.0)
    pg.blocks = blocks
    return pg


# ── Stage 3: emission ───────────────────────────────────────────────────────

def test_text_segment_carries_per_block_rects():
    # Two same-page text blocks merge into one segment but keep both rects, so a
    # coordinate highlight is per-block, not a coarse union.
    blocks = [Block(id="p0_t0", type="text", bbox=[10, 20, 100, 40], content="A"),
              Block(id="p0_t1", type="text", bbox=[10, 45, 100, 60], content="B")]
    seg = [s for s in s3.build_sections([_page(1, blocks)])[0].segments
           if s["kind"] == "text"][0]
    assert seg["text"] == "A B"
    assert seg["bbox"] == [[10, 20, 100, 40], [10, 45, 100, 60]]


def test_table_and_figure_segments_and_refs_carry_region_rect():
    p = [Block(id="p0_tbl0", type="table", bbox=[5, 5, 200, 120],
               path="images/p0_tbl0.png", caption="T"),
         Block(id="p0_img0", type="image", bbox=[5, 130, 200, 300],
               path="images/p0_img0.png", caption="F")]
    sec = s3.build_sections([_page(1, p)])[0]
    tbl_seg = [s for s in sec.segments if s["kind"] == "table"][0]
    fig_seg = [s for s in sec.segments if s["kind"] == "figure"][0]
    assert tbl_seg["bbox"] == [[5, 5, 200, 120]]
    assert fig_seg["bbox"] == [[5, 130, 200, 300]]
    # the refs (→ Tables/Images.bbox) use the same rect-list shape
    assert sec.tables[0].bbox == [[5, 5, 200, 120]]
    assert sec.figures[0].bbox == [[5, 130, 200, 300]]


def test_degenerate_or_missing_bbox_is_dropped():
    # zero-area rect → no bbox key (never store a malformed rectangle)
    blocks = [Block(id="p0_t0", type="text", bbox=[10, 20, 10, 20], content="A")]
    seg = [s for s in s3.build_sections([_page(1, blocks)])[0].segments
           if s["kind"] == "text"][0]
    assert "bbox" not in seg


# ── Stage-3-only rebuild from the pages cache (the HPC re-run mechanism) ─────

def test_rebuild_stage3_from_cache_propagates_bbox(tmp_path):
    from scripts.preprocessing import pipeline as pp
    docdir = tmp_path / "somedoc" / "results"
    docdir.mkdir(parents=True)
    pg = PageData(page_number=3, width_pt=595.0, height_pt=842.0)
    pg.blocks = [Block(id="p3_t0", type="text", bbox=[10, 20, 100, 40],
                       content="Hallo Welt")]
    # the Stage-1/2 cache already carries Block.bbox; only Stage 3 must re-run
    (docdir / "pages_extracted.json").write_text(json.dumps([pg.to_dict()]),
                                                 encoding="utf-8")

    assert pp.rebuild_stage3_from_cache(tmp_path) == 1
    out = json.loads((docdir / "structured_output.json").read_text(encoding="utf-8"))
    seg = [s for s in out["sections"][0]["segments"] if s["kind"] == "text"][0]
    assert seg["bbox"] == [[10, 20, 100, 40]]


# ── models: serialisation ───────────────────────────────────────────────────

def test_ref_to_dict_includes_or_omits_bbox():
    assert TableRef(id="a", path="b", bbox=[[1, 2, 3, 4]]).to_dict()["bbox"] == [[1, 2, 3, 4]]
    assert FigureRef(id="a", path="b", bbox=[[5, 6, 7, 8]]).to_dict()["bbox"] == [[5, 6, 7, 8]]
    assert "bbox" not in TableRef(id="a", path="b").to_dict()


# ── Stage 4: media bbox reattach (LLM echo is not trusted) ───────────────────

def test_reattach_media_bbox_stamps_by_id_across_split():
    inputs = [{"tables": [{"id": "p1_tbl0", "bbox": [[1, 2, 3, 4]]}],
               "figures": [{"id": "p1_img0", "bbox": [[5, 6, 7, 8]]}]}]
    # the LLM dropped the bbox and re-homed the figure into a split child
    outputs = [{"tables": [{"id": "p1_tbl0"}]},
               {"figures": [{"id": "p1_img0"}]}]
    s4._reattach_media_bbox(inputs, outputs)
    assert outputs[0]["tables"][0]["bbox"] == [[1, 2, 3, 4]]
    assert outputs[1]["figures"][0]["bbox"] == [[5, 6, 7, 8]]


def test_reattach_media_bbox_noop_without_geometry():
    outputs = [{"tables": [{"id": "x"}]}]
    s4._reattach_media_bbox([{"tables": [{"id": "x"}]}], outputs)
    assert "bbox" not in outputs[0]["tables"][0]


# ── image processing: dict pass-through preserves bbox (no code change) ───────

def test_imageprocessing_passthrough_preserves_bbox(tmp_path):
    from scripts.imageprocessing.process import process_table, process_figure
    from scripts.imageprocessing.models import ProcessingStats
    stats = ProcessingStats()
    # missing image → early return, but the input dict's extra keys survive
    t = process_table({"id": "p1_tbl0", "path": "missing.png", "bbox": [[1, 2, 3, 4]]},
                      {"title": "S"}, tmp_path, client=None, stats=stats)
    f = process_figure({"id": "p1_img0", "path": "missing.png", "bbox": [[5, 6, 7, 8]]},
                       {"title": "S"}, tmp_path, client=None, stats=stats)
    assert t["bbox"] == [[1, 2, 3, 4]]
    assert f["bbox"] == [[5, 6, 7, 8]]


# ── DB insert writes bbox ────────────────────────────────────────────────────

_MERGED_BBOX = {
    "sections": [
        {"title": "S", "content": "Absatz [p5_tbl0]", "page_number": 5, "pages": [5, 6],
         "segments": [{"page": 5, "kind": "text", "text": "Absatz", "bbox": [[1, 2, 3, 4]]},
                      {"page": 6, "kind": "table", "ref": "p5_tbl0", "bbox": [[5, 6, 7, 8]]}],
         "tables": [{"id": "p5_tbl0", "path": "t.png", "page_number": 6,
                     "markdown": "| a |", "bbox": [[5, 6, 7, 8]]}],
         "figures": [{"id": "p5_img0", "path": "f.png", "page_number": 5,
                      "description": "d", "bbox": [[9, 10, 11, 12]]}]},
    ]
}


def test_insert_sections_writes_bbox(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED_BBOX, con)
    con.commit()
    assert json.loads(con.execute(
        "SELECT bbox FROM Segments WHERE kind='text'").fetchone()[0]) == [[1, 2, 3, 4]]
    assert json.loads(con.execute("SELECT bbox FROM Tables").fetchone()[0]) == [[5, 6, 7, 8]]
    assert json.loads(con.execute("SELECT bbox FROM Images").fetchone()[0]) == [[9, 10, 11, 12]]


def test_ensure_bbox_columns_adds_and_is_idempotent(kwp_db):
    db, con = kwp_db
    # simulate a pre-bbox Images table
    con.execute("DROP TABLE Images")
    con.execute('CREATE TABLE "Images" ("id" INTEGER PRIMARY KEY, "section" INTEGER, '
                '"block_id" TEXT, "path" TEXT, "page_number" INTEGER, "caption" TEXT, '
                '"description" TEXT)')
    con.commit()
    DB._ensure_bbox_columns(con)
    assert "bbox" in {r[1] for r in con.execute('PRAGMA table_info("Images")')}
    DB._ensure_bbox_columns(con)  # second call is a no-op, must not raise


# ── enrich_bbox: additive, non-destructive backfill ─────────────────────────

# A corpus embedded before bbox existed: same shape as test_database._MERGED.
_MERGED_NO_BBOX = {
    "sections": [
        {"title": "S1", "content": "Absatz [p5_tbl0] Folge", "page_number": 5,
         "pages": [5, 6, 7],
         "segments": [{"page": 5, "kind": "text", "text": "Absatz"},
                      {"page": 6, "kind": "table", "ref": "p5_tbl0"},
                      {"page": 7, "kind": "text", "text": "Folge"}],
         "tables": [{"id": "p5_tbl0", "path": "t.png", "page_number": 6, "markdown": "| a |"}],
         "figures": []},
        {"title": "S2", "content": "[p8_img0]", "page_number": 9, "pages": [9],
         "segments": [{"page": 9, "kind": "figure", "ref": "p8_img0"}],
         "tables": [],
         "figures": [{"id": "p8_img0", "path": "f.png", "page_number": 9, "description": "d"}]},
    ]
}

# The re-run Stage-3 output (geometry-bearing) the backfill reads.
_STAGE3 = {
    "sections": [
        {"segments": [{"page": 5, "kind": "text", "text": "Absatz", "bbox": [[1, 2, 3, 4]]},
                      {"page": 6, "kind": "table", "ref": "p5_tbl0", "bbox": [[5, 6, 7, 8]]},
                      {"page": 7, "kind": "text", "text": "Folge", "bbox": [[9, 9, 19, 19]]}],
         "tables": [{"id": "p5_tbl0", "bbox": [[5, 6, 7, 8]]}], "figures": []},
        {"segments": [{"page": 9, "kind": "figure", "ref": "p8_img0", "bbox": [[2, 2, 8, 8]]}],
         "tables": [], "figures": [{"id": "p8_img0", "bbox": [[2, 2, 8, 8]]}]},
    ]
}


def _write_stage3(tmp_path):
    d = tmp_path / "doc" / "results"
    d.mkdir(parents=True)
    (d / "structured_output.json").write_text(json.dumps(_STAGE3), encoding="utf-8")


def test_enrich_bbox_backfills_without_touching_embeddings(kwp_db, tmp_path):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED_NO_BBOX, con)
    con.commit()
    DB.write_embedding_ids_batch(db, "doc", [
        (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 100),
        (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 101),
        (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0", 102),
    ])
    con.commit()
    assert con.execute("SELECT count(*) FROM Segments WHERE bbox IS NOT NULL").fetchone()[0] == 0

    _write_stage3(tmp_path)
    stats = DB.enrich_bbox(db, tmp_path)

    assert stats == {"documents": 1, "segments": 4, "tables": 1, "images": 1}

    r = DB.connect(db)
    # every segment now carries geometry, matched by (page, text) / block id
    by_kind = dict(r.execute(
        "SELECT sg.kind, sg.bbox FROM Segments sg JOIN Pages p ON sg.page = p.id "
        "JOIN Sections s ON sg.section = s.id WHERE p.page_number = 5").fetchall())
    assert json.loads(by_kind["text"]) == [[1, 2, 3, 4]]
    assert json.loads(r.execute("SELECT bbox FROM Tables").fetchone()[0]) == [[5, 6, 7, 8]]
    assert json.loads(r.execute("SELECT bbox FROM Images").fetchone()[0]) == [[2, 2, 8, 8]]
    assert r.execute("SELECT count(*) FROM Segments WHERE bbox IS NOT NULL").fetchone()[0] == 4

    # nothing else moved: embeddings, section content, FAISS-id rows all intact
    assert DB.get_existing_embeddings(db, "doc") == {
        (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None),
        (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0"),
        (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0"),
    }
    assert r.execute("SELECT content FROM Sections WHERE section_number = 0").fetchone()[0] \
        == "Absatz [p5_tbl0] Folge"


def test_enrich_bbox_default_skips_rows_already_set(kwp_db, tmp_path):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED_NO_BBOX, con)
    con.commit()
    # pre-seed one segment's bbox with a sentinel; default run must leave it.
    con.execute("UPDATE Tables SET bbox = ? WHERE block_id = 'p5_tbl0'", ('[[0,0,1,1]]',))
    con.commit()

    _write_stage3(tmp_path)
    DB.enrich_bbox(db, tmp_path)                       # default: bbox IS NULL only
    r = DB.connect(db)
    assert json.loads(r.execute("SELECT bbox FROM Tables").fetchone()[0]) == [[0, 0, 1, 1]]

    DB.enrich_bbox(db, tmp_path, force=True)           # force overwrites
    r = DB.connect(db)
    assert json.loads(r.execute("SELECT bbox FROM Tables").fetchone()[0]) == [[5, 6, 7, 8]]
