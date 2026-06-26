"""Step-2/4 DB: ingestion of page provenance + the Embeddings table."""
from scripts.chunkingandembedding import database as DB
from scripts.chunkingandembedding import config as C

_MERGED = {
    "sections": [
        {"title": "Bestandsanalyse", "content": "Absatz [p5_tbl0] Folge",
         "page_number": 5, "pages": [5, 6, 7],
         "segments": [{"page": 5, "kind": "text", "text": "Absatz"},
                      {"page": 6, "kind": "table", "ref": "p5_tbl0"},
                      {"page": 7, "kind": "text", "text": "Folge"}],
         "tables": [{"id": "p5_tbl0", "path": "images/p5_tbl0.png", "page_number": 6,
                     "caption": "Energieträger", "markdown": "| a |"}],
         "figures": []},
        {"title": "Potenziale", "content": "[p8_img0]", "page_number": 9, "pages": [9],
         "segments": [{"page": 9, "kind": "figure", "ref": "p8_img0"}],
         "tables": [],
         "figures": [{"id": "p8_img0", "path": "images/p8_img0.png", "page_number": 9,
                      "caption": "Karte", "description": "Eine Karte"}]},
    ]
}


def test_insert_sections_writes_pages_segments_sectionpages(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED, con)
    con.commit()

    assert con.execute("SELECT count(*) FROM Sections").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM Pages").fetchone()[0] == 4        # 5,6,7,9
    assert con.execute("SELECT count(*) FROM SectionPages").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM Segments").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM Tables").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM Images").fetchone()[0] == 1

    rows = con.execute(
        "SELECT sg.ordinal, sg.kind, p.page_number, sg.ref, sg.text "
        "FROM Segments sg JOIN Pages p ON sg.page = p.id "
        "JOIN Sections s ON sg.section = s.id WHERE s.section_number = 0 "
        "ORDER BY sg.ordinal"
    ).fetchall()
    assert rows == [(0, "text", 5, None, "Absatz"),
                    (1, "table", 6, "p5_tbl0", None),
                    (2, "text", 7, None, "Folge")]

    assert con.execute(
        "SELECT title, content, page_number FROM Sections WHERE section_number = 0"
    ).fetchone() == ("Bestandsanalyse", "Absatz [p5_tbl0] Folge", 5)


def test_embeddings_roundtrip_and_clear(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED, con)
    con.commit()

    DB.write_embedding_ids_batch(db, "doc", [
        (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 100),
        (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 101),
        (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0", 102),
    ])
    existing = DB.get_existing_embeddings(db, "doc")
    assert (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None) in existing
    assert (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0") in existing
    assert (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0") in existing

    old = DB.clear_embedding_ids(db, "doc")
    assert sorted(old) == [100, 101, 102]
    assert DB.get_existing_embeddings(db, "doc") == set()


def test_force_delete_cascades(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED, con)
    con.commit()
    DB._delete_document_content(1, con)
    con.commit()
    for t in ("Sections", "Pages", "SectionPages", "Segments", "Tables", "Images"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
