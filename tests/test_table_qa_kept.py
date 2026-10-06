"""Stage 5 keeps the check of every table, and the database keeps it too.

The promise, in one sentence: for every table the model answered in JSON,
stage 5 keeps the result of the check it ran (the attempt it kept, passing or
failing) in visuals.json AND the merge hands it on AND chunking stores it in
Tables.qa AND a database made before the column is migrated when a document
is inserted, AND a table with no check reads as not checked and never as
passed.

Each AND has its own tests below, and each has a case built to break it: a
retry that fixed the table, a frame with no text layer, a table the model gave
no object for, a table of an older run, a database without the column.
"""
import json
import sqlite3
import types

from docpipe.artifacts import DOCUMENT_JSON, SECTIONS_JSON
from docpipe.artifacts import SECTIONS_REFINED_JSON, VISUALS_JSON
from docpipe.chunking import database as DB
from docpipe.chunking import merge as MG
from docpipe.inference import db as inference_db
from docpipe.reading import Hole
from docpipe.visuals import config as C
from docpipe.visuals import pipeline as IP
from docpipe.visuals import process as P
from docpipe.visuals import qa
from docpipe.visuals.models import ProcessingStats

SOURCE = ("Energieträger Anteil Erdgas 45,2 Fernwärme 23,1 Wärmepumpe 12,8 "
          "Solar 5,0 Biomasse 9,1")
HEAD = "| Energieträger | Anteil |\n| --- | --- |"
ROWS = ["| Erdgas | 45,2 |", "| Fernwärme | 23,1 |", "| Wärmepumpe | 12,8 |",
        "| Solar | 5,0 |", "| Biomasse | 9,1 |"]
FULL = "\n".join([HEAD] + ROWS)
STUTTER = "| --- | --- |\n" + "\n".join(["| a | 1 |"] * 4)
KEYS = {"passed", "coverage", "coverage_assessed", "duplication", "has_rows"}


def _reply(markdown, caption="C"):
    return json.dumps({"markdown": markdown, "caption": caption})


def _process(tmp_path, make_client, seq_responder, replies, source=SOURCE):
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    return P.process_table(
        {"id": "p1_tbl0", "path": "images/t.png"}, {"title": "S"}, tmp_path,
        make_client(seq_responder(replies)), ProcessingStats(),
        source_text=source)


# ---------------------------------------------------------------------------
# AND 1: stage 5 keeps the result of the check for every table it checked
# ---------------------------------------------------------------------------

def test_a_table_that_passes_keeps_what_was_measured(tmp_path, make_client,
                                                     seq_responder):
    out = _process(tmp_path, make_client, seq_responder, [_reply(FULL)])
    assert out["qa"] == {"passed": True, "coverage": 1.0,
                         "coverage_assessed": True, "duplication": 0.0,
                         "has_rows": True}
    assert "qa_warning" not in out


def test_a_table_that_fails_keeps_what_was_measured_too(tmp_path, make_client,
                                                        seq_responder):
    out = _process(tmp_path, make_client, seq_responder,
                   [_reply(STUTTER), _reply(STUTTER)])
    assert out["qa"]["passed"] is False
    assert out["qa"]["duplication"] == 0.75
    # measured on what the model wrote: the stored text has its stutter
    # collapsed afterwards, which is what the schema says of the metrics
    assert out["markdown"].count("| a | 1 |") == 1
    # the old key stays and says the same, without the verdict
    assert out["qa_warning"] == {k: v for k, v in out["qa"].items()
                                 if k != "passed"}
    assert set(out["qa"]) == KEYS


def test_the_check_kept_is_the_one_of_the_attempt_that_was_kept(
        tmp_path, make_client, seq_responder):
    """The first answer misses rows and fails; the retry is complete. A check
    kept from the first attempt would say failed for a table that is fine."""
    truncated = "\n".join([HEAD, ROWS[0]])
    out = _process(tmp_path, make_client, seq_responder,
                   [_reply(truncated), _reply(FULL)])
    assert out["markdown"] == FULL
    assert out["qa"]["passed"] is True
    assert out["qa"]["coverage"] == 1.0
    assert "qa_warning" not in out


def test_when_both_attempts_fail_the_better_ones_check_is_kept(
        tmp_path, make_client, seq_responder):
    one = "\n".join([HEAD, ROWS[0]])
    two = "\n".join([HEAD, ROWS[0], "| Fernwärme | |"])
    first, second = qa.coverage(SOURCE, one), qa.coverage(SOURCE, two)
    assert first < second < 0.5            # both fail, the second is closer
    out = _process(tmp_path, make_client, seq_responder,
                   [_reply(one), _reply(two)])
    assert out["markdown"] == two
    assert out["qa"]["passed"] is False
    assert out["qa"]["coverage"] == round(second, 3)


def test_a_frame_without_a_text_layer_is_kept_as_unknown_not_as_perfect(
        tmp_path, make_client, seq_responder):
    out = _process(tmp_path, make_client, seq_responder, [_reply(FULL)],
                   source="")
    assert out["qa"]["coverage"] is None
    assert out["qa"]["coverage_assessed"] is False
    assert out["qa"]["passed"] is True        # nothing could fail it


def test_a_table_the_model_gave_no_object_for_has_no_check_and_no_content(
        monkeypatch, tmp_path):
    """Plain text is no longer an answer: the model's markdown without the
    envelope is a hole (`no_object`), and the table has nothing that could
    pass or fail a check."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: Hole("no_object"))
    out = P.process_table({"id": "p1_tbl0", "path": "images/t.png"},
                          {"title": "S"}, tmp_path, None, ProcessingStats(),
                          source_text=SOURCE)
    assert "markdown" not in out, "not read, not rescued"
    assert out["vlm_why"] == "no_object"
    assert "qa" not in out, "not checked is not the same as passed"


def test_a_table_the_model_never_answered_has_no_check(monkeypatch, tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: Hole("not_served"))
    out = P.process_table({"id": "p1_tbl0", "path": "images/t.png"},
                          {"title": "S"}, tmp_path, None, ProcessingStats(),
                          source_text=SOURCE)
    assert "markdown" not in out and "qa" not in out


def _fake_client(monkeypatch, reply):
    answer = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=reply))])
    monkeypatch.setattr(IP, "create_client", lambda base_url=None,
                        timeout=None: types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: answer)),
        models=types.SimpleNamespace(list=lambda: types.SimpleNamespace(
            data=[types.SimpleNamespace(id=C.VLM_MODEL)]))))


def _document(tmp_path, cached_without_qa=False):
    """Two tables of one section; t0 may already be done by an older run,
    whose visuals.json knows no qa."""
    (tmp_path / "results").mkdir()
    (tmp_path / "images").mkdir()
    tables = [{"id": f"p1_tbl{n}", "path": f"images/p1_tbl{n}.png",
               "page_number": 1, "source_text": SOURCE} for n in range(2)]
    (tmp_path / SECTIONS_JSON).write_text(json.dumps({"sections": [
        {"title": "S", "content": "[p1_tbl0] [p1_tbl1]", "tables": tables,
         "figures": []}]}), encoding="utf-8")
    for table in tables:
        (tmp_path / table["path"]).write_bytes(b"x")
    if cached_without_qa:
        done = {k: v for k, v in tables[0].items() if k != "source_text"}
        done["markdown"] = "| old |"
        (tmp_path / VISUALS_JSON).write_text(json.dumps({"sections": [
            {"title": "S", "tables": [done], "figures": []}]}),
            encoding="utf-8")
    return tmp_path


def test_every_table_the_stage_transcribed_has_its_check_in_visuals_json(
        tmp_path, monkeypatch):
    _fake_client(monkeypatch, _reply(FULL))
    directory = _document(tmp_path)
    IP.run_single(directory)
    written = json.loads((directory / VISUALS_JSON).read_text(
        encoding="utf-8"))
    tables = written["sections"][0]["tables"]
    assert len(tables) == 2
    assert all(set(t["qa"]) == KEYS and t["qa"]["passed"] for t in tables)


def test_a_table_of_an_older_run_is_not_given_a_check_it_never_had(
        tmp_path, monkeypatch):
    """Nothing is measured for a cached table, so nothing is written for it:
    its key stays missing, which reads as not checked. The table the run does
    transcribe gets its check beside it."""
    _fake_client(monkeypatch, _reply(FULL))
    directory = _document(tmp_path, cached_without_qa=True)
    IP.run_single(directory)
    tables = json.loads((directory / VISUALS_JSON).read_text(
        encoding="utf-8"))["sections"][0]["tables"]
    old, new = tables
    assert old["markdown"] == "| old |" and "qa" not in old
    assert new["qa"]["passed"] is True


# ---------------------------------------------------------------------------
# AND 2: the merge hands the check on
# ---------------------------------------------------------------------------

def _merge(tmp_path, visuals_table):
    (tmp_path / "results").mkdir()
    (tmp_path / SECTIONS_REFINED_JSON).write_text(json.dumps({"sections": [
        {"title": "S", "content": "[p1_tbl0]", "pages": [1], "segments": [],
         "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png"}],
         "figures": []}]}), encoding="utf-8")
    (tmp_path / VISUALS_JSON).write_text(json.dumps({"sections": [
        {"tables": [visuals_table], "figures": []}]}), encoding="utf-8")
    return MG.merge_single(tmp_path, force=True)["sections"][0]["tables"][0]


def test_the_merge_carries_the_check_into_document_json(tmp_path):
    check = {"passed": False, "coverage": 0.4, "coverage_assessed": True,
             "duplication": 0.0, "has_rows": True}
    table = _merge(tmp_path, {"id": "p1_tbl0", "markdown": "| a |",
                              "qa": check})
    assert table["qa"] == check
    on_disk = json.loads((tmp_path / DOCUMENT_JSON).read_text(
        encoding="utf-8"))
    assert on_disk["sections"][0]["tables"][0]["qa"] == check


def test_the_merge_does_not_make_one_up(tmp_path):
    table = _merge(tmp_path, {"id": "p1_tbl0", "markdown": "| a |"})
    assert "qa" not in table


# ---------------------------------------------------------------------------
# AND 3: chunking stores it
# ---------------------------------------------------------------------------

def _merged(**table):
    return {"sections": [{
        "title": "S", "content": "[p1_tbl0]", "page_number": 1, "pages": [1],
        "segments": [{"page": 1, "kind": "table", "ref": "p1_tbl0"}],
        "tables": [dict({"id": "p1_tbl0", "path": "t.png", "page_number": 1,
                         "markdown": "| a |"}, **table)],
        "figures": []}]}


def test_the_table_row_holds_the_check_as_json(kwp_db):
    db, con = kwp_db
    check = {"passed": True, "coverage": None, "coverage_assessed": False,
             "duplication": 0.0, "has_rows": True}
    DB._insert_sections(1, _merged(qa=check), con)
    con.commit()
    (stored,) = con.execute("SELECT qa FROM Tables").fetchone()
    assert json.loads(stored) == check


def test_a_table_without_a_check_reads_null_not_a_pass(kwp_db):
    db, con = kwp_db
    DB._insert_sections(1, _merged(), con)
    con.commit()
    assert con.execute("SELECT qa FROM Tables").fetchone() == (None,)
    assert DB._qa_json({"qa": {}}) is None
    assert DB._qa_json({"qa": None}) is None


# ---------------------------------------------------------------------------
# AND 4: an older database is migrated, and stays readable
# ---------------------------------------------------------------------------

def _database_before_the_column(kwp_db):
    """The database as an earlier version made it: Tables without qa, with a
    table of another document already in it."""
    db, con = kwp_db
    con.execute("DROP TABLE Tables")
    con.execute(
        'CREATE TABLE "Tables" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"section" INTEGER NOT NULL REFERENCES "Sections"("id") ON DELETE '
        'CASCADE, "block_id" TEXT, "path" TEXT NOT NULL, "page_number" '
        'INTEGER, "caption" TEXT, "markdown" TEXT, "bbox" TEXT, '
        '"caption_source" TEXT)')
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'old.pdf', 3)")
    con.execute("INSERT INTO Sections (id, document, section_number, title, "
                "content) VALUES (50, 2, 0, 'old', 'x')")
    con.execute("INSERT INTO Tables (id, section, block_id, path, "
                "page_number, markdown) VALUES (7, 50, 'p1_tbl0', 'a.png', "
                "1, '| old |')")
    con.commit()
    assert "qa" not in {r[1] for r in con.execute(
        'PRAGMA table_info("Tables")')}
    return db, con


def test_a_database_without_the_column_is_still_read_by_the_readers(kwp_db):
    db, con = _database_before_the_column(kwp_db)
    con.row_factory = sqlite3.Row
    got = inference_db.fetch_owner_content(con, "table", 7)
    assert got["text"] == "| old |" and got["document_id"] == 2


def test_the_column_is_added_once_and_the_old_rows_keep_their_content(kwp_db):
    db, con = _database_before_the_column(kwp_db)
    DB._ensure_table_qa_column(con)
    DB._ensure_table_qa_column(con)          # a second call changes nothing
    assert "qa" in {r[1] for r in con.execute('PRAGMA table_info("Tables")')}
    assert con.execute("SELECT markdown, qa FROM Tables WHERE id = 7"
                       ).fetchone() == ("| old |", None)


def test_inserting_a_document_migrates_the_database_and_fills_the_column(
        kwp_db, tmp_path):
    db, con = _database_before_the_column(kwp_db)
    check = {"passed": True, "coverage": 1.0, "coverage_assessed": True,
             "duplication": 0.0, "has_rows": True}
    folder = tmp_path / "corpus" / "doc" / "results"
    folder.mkdir(parents=True)
    (folder / "document.json").write_text(json.dumps(_merged(qa=check)),
                                          encoding="utf-8")

    DB.update_database(db, tmp_path / "corpus")

    rows = dict((block, qa_text) for block, qa_text in sqlite3.connect(
        db).execute("SELECT block_id, qa FROM Tables ORDER BY id"))
    assert json.loads(rows["p1_tbl0"]) == check
    # the table of the other document, written before the column, is intact
    # and reads as not checked
    row = sqlite3.connect(db).execute(
        "SELECT markdown, qa FROM Tables WHERE id = 7").fetchone()
    assert row == ("| old |", None)


def test_a_database_made_today_has_the_column_from_the_start(kwp_db):
    db, con = kwp_db
    assert "qa" in {r[1] for r in con.execute('PRAGMA table_info("Tables")')}
    assert "qa" not in {r[1] for r in con.execute(
        'PRAGMA table_info("Images")')}
