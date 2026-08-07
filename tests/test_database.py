"""Step-2/4 DB: ingestion of page provenance + the Embeddings table."""
from docpipe.chunking import database as DB
from docpipe.chunking import config as C

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


def test_next_faiss_id_advances_past_max(kwp_db):
    db, con = kwp_db
    assert DB.next_faiss_id(db) == 0          # empty Embeddings → start at 0
    DB._insert_sections(1, _MERGED, con)
    con.commit()
    DB.write_embedding_ids_batch(db, "doc", [
        (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 100),
        (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 101),
        (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0", 102),
    ])
    # Must be MAX+1 (not the live count) so a --force eviction never reuses a
    # live id and trips the faiss_id PRIMARY KEY.
    assert DB.next_faiss_id(db) == 103


def test_faiss_id_snapshot_survives_forced_content_delete(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _MERGED, con)
    con.commit()
    DB.write_embedding_ids_batch(db, "doc", [
        (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 100),
        (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 101),
    ])
    snapshot = DB.get_document_faiss_ids(db, "doc")
    assert sorted(snapshot) == [100, 101]

    # Step 2 --force deletes content + embeddings before Step 3 could read them.
    DB._delete_document_content(1, con)
    con.commit()

    # A post-delete read finds nothing (the orphan-vector trap), but the
    # pre-delete snapshot still holds the ids to evict from the index.
    assert DB.get_document_faiss_ids(db, "doc") == []
    assert sorted(snapshot) == [100, 101]


_PER_DOCUMENT_SQL = [
    (DB._EXISTING_SECTION_SQL, 1),
    (DB._EXISTING_TABLE_SQL, 1),
    (DB._EXISTING_FIGURE_SQL, 1),
    (DB._DOCUMENT_FAISS_IDS_SQL, 3),
]


def test_per_document_lookups_drive_from_sections(kwp_db):
    _, con = kwp_db
    for sql, n_params in _PER_DOCUMENT_SQL:
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, (1,) * n_params)]
        steps = [d for d in plan if d.startswith(("SEARCH", "SCAN"))]

        # Every one of these runs once per document. Reaching Embeddings on
        # owner_kind alone rescans that whole partition each time — 300x slower
        # over the corpus. The CROSS JOINs exist to stop the planner doing that.
        assert not any("(owner_kind=?)" in d for d in steps), plan
        assert all("owner_kind=? AND owner_id=?" in d
                   for d in steps if d.startswith("SEARCH e")), plan
        assert steps[0].startswith("SEARCH s "), plan


_ALL_TYPES = [
    (C.EMBEDDING_TYPE_SECTION_TEXT, 0, None),
    (C.EMBEDDING_TYPE_SECTION_TITLE, 0, None),
    (C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0"),
    (C.EMBEDDING_TYPE_TABLE_VL, 0, "p5_tbl0"),
    (C.EMBEDDING_TYPE_FIGURE_TEXT, 1, "p8_img0"),
    (C.EMBEDDING_TYPE_FIGURE_VL, 1, "p8_img0"),
]


def test_existing_embeddings_covers_all_types_of_one_document_only(kwp_db):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (2, 'other.pdf', 9)")
    DB._insert_sections(1, _MERGED, con)
    DB._insert_sections(2, _MERGED, con)
    con.commit()
    for name, base in (("doc", 100), ("other", 200)):
        DB.write_embedding_ids_batch(db, name, [
            (etype, sec, item, base + n) for n, (etype, sec, item) in enumerate(_ALL_TYPES)
        ])

    # All six types must round-trip, and a second document's rows must not leak
    # in — a lookup that loses a type re-embeds it, one that gains a foreign row
    # skips work that was never done.
    assert DB.get_existing_embeddings(db, "doc") == set(_ALL_TYPES)
    assert sorted(DB.get_document_faiss_ids(db, "doc")) == [100, 101, 102, 103, 104, 105]


def test_existing_embeddings_resolves_document_without_pdf_suffix(kwp_db):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (2, 'bare', 3)")
    DB._insert_sections(2, _MERGED, con)
    con.commit()
    DB.write_embedding_ids_batch(db, "bare", [(C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 200)])

    # _resolve_document_id falls back to the bare name when '<name>.pdf' misses.
    assert DB.get_existing_embeddings(db, "bare") == {(C.EMBEDDING_TYPE_SECTION_TEXT, 0, None)}
