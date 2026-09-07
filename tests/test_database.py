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


class _CountingConnection:
    """Delegates to a real connection and counts the statements it is given."""

    def __init__(self, connection):
        self._connection = connection
        self.executes = 0
        self.executemanys = 0

    def execute(self, *args):
        self.executes += 1
        return self._connection.execute(*args)

    def executemany(self, *args):
        self.executemanys += 1
        return self._connection.executemany(*args)


def _big_section(n_children):
    return {"sections": [{
        "title": "T", "content": "c", "page_number": 1, "pages": [1],
        "segments": [{"page": 1, "kind": "text", "text": "t%d" % i}
                     for i in range(n_children)],
        "tables": [{"id": "tbl%d" % i, "path": "", "page_number": 1}
                   for i in range(n_children)],
        "figures": [{"id": "img%d" % i, "path": "", "page_number": 1}
                    for i in range(n_children)],
    }]}


def test_section_children_go_out_per_statement_not_per_row(kwp_db):
    """The corpus holds 134k sections and far more segments; one execute() per
    row is that many round trips into sqlite for nothing."""
    _, con = kwp_db
    counting = _CountingConnection(con)

    DB._insert_sections(1, _big_section(50), counting)
    con.commit()

    assert con.execute("SELECT count(*) FROM Segments").fetchone()[0] == 50
    assert con.execute("SELECT count(*) FROM Tables").fetchone()[0] == 50
    assert con.execute("SELECT count(*) FROM Images").fetchone()[0] == 50
    # The section row and the one page's get-or-create; the 150 children ride
    # along in four executemany calls.
    assert counting.executes <= 4, counting.executes
    assert counting.executemanys == 4


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


def test_one_writer_keeps_two_documents_block_ids_apart(kwp_db):
    """The writer caches each document's block ids for the whole chunk, and two
    plans share block ids as a matter of course ('p5_tbl0' is a position, not a
    name). A cache that leaked across documents would file one plan's table
    under the other's row."""
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (2, 'other.pdf', 9)")
    DB._insert_sections(1, _MERGED, con)
    DB._insert_sections(2, _MERGED, con)
    con.commit()

    with DB.EmbeddingWriter(db) as writer:
        writer.write("doc", [(C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 300)])
        writer.write("other", [(C.EMBEDDING_TYPE_TABLE_TEXT, 0, "p5_tbl0", 301)])

    owners = dict(con.execute(
        "SELECT e.faiss_id, s.document FROM Embeddings e "
        "JOIN Tables t ON e.owner_id = t.id JOIN Sections s ON t.section = s.id "
        "WHERE e.owner_kind = 'table'"))
    assert owners == {300: 1, 301: 2}


def test_a_prepare_worker_asks_both_questions_over_one_connection(kwp_db, monkeypatch):
    """document_id() and get_existing_embeddings() are called back to back per
    document from the prepare pool; a connection (plus PRAGMAs) each was most of
    what preparing a document cost."""
    db, con = kwp_db
    DB._insert_sections(1, _MERGED, con)
    con.commit()

    opened = []
    real_connect = DB.connect
    monkeypatch.setattr(DB, "connect",
                        lambda p: (opened.append(str(p)), real_connect(p))[1])

    for _ in range(3):
        doc_id = DB.document_id(db, "doc")
        assert DB.get_existing_embeddings(db, "doc", doc_id=doc_id) == set()

    assert len(opened) == 1, f"{len(opened)} connections for 6 lookups"


def test_existing_embeddings_resolves_document_without_pdf_suffix(kwp_db):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (2, 'bare', 3)")
    DB._insert_sections(2, _MERGED, con)
    con.commit()
    DB.write_embedding_ids_batch(db, "bare", [(C.EMBEDDING_TYPE_SECTION_TEXT, 0, None, 200)])

    # _resolve_document_id falls back to the bare name when '<name>.pdf' misses.
    assert DB.get_existing_embeddings(db, "bare") == {(C.EMBEDDING_TYPE_SECTION_TEXT, 0, None)}


def test_page_source_is_additive_and_says_which_plans_a_model_read(kwp_db,
                                                                   tmp_path):
    """Eleven plans of the corpus have no PDF text layer: a model transcribes
    their pages and everything downstream runs unchanged, so their section
    text is itself a model reading and so is every quote verified against it.
    The count already existed per document; it never reached the database,
    and nothing downstream could tell the two kinds of plan apart.
    """
    import json
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'scan.pdf', 40)")
    con.commit()
    root = tmp_path / "processed"
    for name, transcribed in (("doc.pdf", 0), ("scan.pdf", 40)):
        report = root / name / C.PAGE_TRANSCRIPTION_REPORT_JSON
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(
            {"pages_total": 40, "pages_missing_text": transcribed,
             "pages_transcribed": transcribed, "pages_empty": 0,
             "pages_failed": 0, "blocks_added": transcribed}), encoding="utf-8")

    stats = DB.enrich_page_source(db, root)
    assert stats == {"documents": 2, "transcribed": 1, "pages": 40}
    got = dict(con.execute("SELECT filename, page_text_transcribed "
                           "FROM Documents").fetchall())
    assert got == {"doc.pdf": 0, "scan.pdf": 40}

    # A second pass writes nothing: 0 is an answer, not a missing one, so a
    # plan with a text layer is not re-examined every run.
    assert DB.enrich_page_source(db, root)["documents"] == 0
    con.execute("UPDATE Documents SET num_pages = 41 WHERE id = 2")
    con.commit()
    assert DB.enrich_page_source(db, root, force=True)["documents"] == 2


# ---------------------------------------------------------------------------
# The title a table is stored under
# ---------------------------------------------------------------------------
_FOOTNOTE = "Hinweis: Wegen der Rundung kann es zu Abweichungen kommen."

_CAPTIONS = {
    "sections": [
        {"title": "Bestand", "page_number": 5, "pages": [5],
         "content": ("Tabelle 17: Endenergieverbrauch 2040 [p5_tbl0] "
                     "Abbildung 3: Waermedichte [p5_img0]"),
         "segments": [{"page": 5, "kind": "table", "ref": "p5_tbl0"},
                      {"page": 5, "kind": "figure", "ref": "p5_img0"}],
         "tables": [{"id": "p5_tbl0", "path": "i/p5_tbl0.png", "page_number": 5,
                     "caption": _FOOTNOTE, "markdown": "| a |"}],
         "figures": [{"id": "p5_img0", "path": "i/p5_img0.png", "page_number": 5,
                      "caption": "Quelle: eigene Darstellung",
                      "description": "Eine Karte"}]},
        {"title": "Ziel", "page_number": 6, "pages": [6],
         "content": "Tabelle 18: Zielszenario 2045 [p6_tbl0]",
         "segments": [{"page": 6, "kind": "table", "ref": "p6_tbl0"}],
         "tables": [{"id": "p6_tbl0", "path": "i/p6_tbl0.png", "page_number": 6,
                     "caption": "Tabelle 18: Zielszenario 2045",
                     "markdown": "| b |"}],
         "figures": []},
    ]
}


def test_enrich_caption_takes_the_title_from_the_section_text(kwp_db):
    """Stage 2 links a caption block by distance and links the rounding
    footnote instead: 15 of Kassel's 89 tables. The caption is the only line
    of a table a model can quote for the table's own year, so 240 of 379
    tuples from the twelve titled tables carried a foreign year. The corpus
    was built before Stage 3 settled this, and re-preprocessing 1.082 plans
    costs GPU days -- the rule is a pure function of the section text, so it
    runs over the finished database.
    """
    db, con = kwp_db
    DB._insert_sections(1, _CAPTIONS, con)
    con.commit()

    stats = DB.enrich_caption(db)
    assert stats == {"documents": 1, "tables": 2, "images": 1, "resolved": 2}
    got = dict(con.execute(
        "SELECT block_id, caption FROM Tables "
        "UNION ALL SELECT block_id, caption FROM Images").fetchall())
    assert got["p5_tbl0"] == "Tabelle 17: Endenergieverbrauch 2040"
    assert got["p5_img0"] == "Abbildung 3: Waermedichte"
    # A caption that already opens like one is left alone: Stage 2 saw the
    # two blocks on the page, and a link beats a guess.
    assert got["p6_tbl0"] == "Tabelle 18: Zielszenario 2045"
    sources = dict(con.execute(
        "SELECT block_id, caption_source FROM Tables "
        "UNION ALL SELECT block_id, caption_source FROM Images").fetchall())
    assert sources == {"p5_tbl0": "section_text", "p5_img0": "section_text",
                       "p6_tbl0": "stage"}


def test_enrich_caption_is_additive_and_never_runs_twice(kwp_db):
    """A backfill that redoes its work every run is a backfill nobody dares
    put in the db step. `caption_source` is the marker, and `force` is the
    only way past it."""
    db, con = kwp_db
    DB._insert_sections(1, _CAPTIONS, con)
    con.commit()
    assert DB.enrich_caption(db)["tables"] == 2

    second = DB.enrich_caption(db)
    assert second == {"documents": 0, "tables": 0, "images": 0, "resolved": 0}

    # And it never overwrites a title someone corrected by hand.
    con.execute("UPDATE Tables SET caption = ? WHERE block_id = ?",
                ("Tabelle 17: Von Hand berichtigt", "p5_tbl0"))
    con.commit()
    DB.enrich_caption(db)
    assert con.execute("SELECT caption FROM Tables WHERE block_id = ?",
                       ("p5_tbl0",)).fetchone()[0] == \
        "Tabelle 17: Von Hand berichtigt"

    assert DB.enrich_caption(db, force=True)["tables"] == 2


def test_enrich_caption_leaves_a_table_with_no_sentence_alone(kwp_db):
    """"Nothing to take it from" is the common case, not a failure: the row
    keeps the caption it has and is marked seen, or the pass would look at it
    again on every run."""
    db, con = kwp_db
    DB._insert_sections(1, {"sections": [
        {"title": "Anhang", "page_number": 7, "pages": [7],
         "content": "Der Verbrauch sinkt. [p7_tbl0]",
         "segments": [{"page": 7, "kind": "table", "ref": "p7_tbl0"}],
         "tables": [{"id": "p7_tbl0", "path": "i/p7_tbl0.png", "page_number": 7,
                     "caption": _FOOTNOTE, "markdown": "| c |"}],
         "figures": []}]}, con)
    con.commit()

    assert DB.enrich_caption(db)["resolved"] == 0
    row = con.execute("SELECT caption, caption_source FROM Tables").fetchone()
    assert row[0] == _FOOTNOTE and row[1] == "stage"
