"""The request log of the chat.

What is promised:

  * a request to one document is logged with that document AND a request to
    the whole corpus is logged with none;
  * a log made when every request named a document accepts a request to the
    whole corpus afterwards AND keeps every row it had under its own id AND
    numbers the next request after the last;
  * a chat turn over the whole corpus ends with its line in the log;
  * a turn logs how many statements the model made AND how many of them were
    dropped, in statements;
  * a log made before those columns existed opens, gains both AND keeps every
    row, and the oldest table (a document demanded) still migrates in the
    same open and keeps its ids and its timestamps.
"""
import sqlite3

import pytest

from docpipe.inference import answer, request_log

# The table as the log was made before the whole corpus could be asked.
BEFORE = """
CREATE TABLE requests (
    request_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    query_text      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    scopes          TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    latency_ms      REAL,
    n_hits          INTEGER,
    n_citations     INTEGER,
    answer_hash     TEXT,
    error_message   TEXT,
    cache_hit       BOOLEAN
);
"""


def rows(conn):
    return conn.execute("SELECT request_id, plan_id, query_text, n_hits "
                        "FROM requests ORDER BY request_id").fetchall()


def test_a_request_is_logged_with_its_document_or_with_none(tmp_path):
    conn = request_log.connect(tmp_path / "log" / "requests.db")
    first = request_log.log_request(conn, 7, "Wie hoch?", "text", ["text"],
                                    12.5, n_hits=3)
    second = request_log.log_request(conn, None, "Und überall?", "text",
                                     ["text"], 20.0, n_hits=9)
    assert rows(conn) == [(first, 7, "Wie hoch?", 3),
                          (second, None, "Und überall?", 9)]
    conn.close()
    # opened again, it is the same log
    again = request_log.connect(tmp_path / "log" / "requests.db")
    assert len(rows(again)) == 2
    again.close()


def test_a_log_made_before_accepts_the_whole_corpus_and_keeps_its_rows(
        tmp_path):
    path = tmp_path / "requests.db"
    old = sqlite3.connect(path)
    old.executescript(BEFORE)
    for request_id, document in ((1, 4), (5, 9)):
        old.execute("INSERT INTO requests (request_id, plan_id, query_text, "
                    "mode, scopes, n_hits) VALUES (?, ?, ?, 'text', '[]', 2)",
                    (request_id, document, f"q{request_id}"))
    old.commit()
    # this is the table that refused: the reason there is something to do
    with pytest.raises(sqlite3.IntegrityError):
        old.execute("INSERT INTO requests (plan_id, query_text, mode, "
                    "scopes) VALUES (NULL, 'q', 'text', '[]')")
    old.rollback()
    stamps = old.execute("SELECT timestamp FROM requests "
                         "ORDER BY request_id").fetchall()
    old.close()

    conn = request_log.connect(path)
    assert rows(conn) == [(1, 4, "q1", 2), (5, 9, "q5", 2)]
    assert conn.execute("SELECT timestamp FROM requests "
                        "ORDER BY request_id").fetchall() == stamps
    new = request_log.log_request(conn, None, "überall", "text", [], 1.0)
    assert new == 6                         # after the last, not over a row
    assert rows(conn)[-1] == (6, None, "überall", None)
    assert "requests_before" not in {name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master")}
    conn.close()
    # and a second opening has nothing left to do
    again = request_log.connect(path)
    assert len(rows(again)) == 3
    again.close()


def test_a_turn_over_the_whole_corpus_ends_with_its_line_in_the_log(
        tmp_path, monkeypatch):
    monkeypatch.setattr(answer.hybrid, "retrieve", lambda *a, **more: [])
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda task, **more: ("Bedarf", False))
    log = request_log.connect(tmp_path / "requests.db")
    corpus = answer.Corpus(conn=None, index=None, id_to_pos={},
                           embed=lambda item: ([0.0] * 4, False),
                           log_conn=log)
    for document in (None, 3):
        answer.answer_question("Wie hoch?", corpus, document,
                               [answer.config.SCOPE_TEXT])
    assert [(document, text) for _id, document, text, _hits in rows(log)] \
        == [(None, "Wie hoch?"), (3, "Wie hoch?")]
    log.close()


# The table as it was when the whole corpus could be asked and the statements
# were not yet counted: what `_allow_no_document` makes of the table above.
WITHOUT_COUNTS = BEFORE.replace("plan_id         INTEGER NOT NULL",
                                "plan_id         INTEGER")


def columns(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(requests)")]


def test_a_log_made_before_the_statement_columns_gains_them_and_keeps_its_rows(
        tmp_path):
    path = tmp_path / "requests.db"
    old = sqlite3.connect(path)
    old.executescript(WITHOUT_COUNTS)
    for request_id, document in ((1, 4), (2, None), (7, 9)):
        old.execute("INSERT INTO requests (request_id, plan_id, query_text, "
                    "mode, scopes, n_hits, n_citations, answer_hash, "
                    "error_message) VALUES (?, ?, ?, 'text', '[]', 2, 1, "
                    "'abc', 'e')", (request_id, document, f"q{request_id}"))
    old.commit()
    assert "n_statements" not in columns(old)
    before = old.execute("SELECT * FROM requests ORDER BY request_id")         .fetchall()
    old.close()

    conn = request_log.connect(path)
    assert {"n_statements", "n_dropped"} <= set(columns(conn))
    kept = conn.execute("SELECT request_id, plan_id, query_text, mode, "
                        "scopes, timestamp, latency_ms, n_hits, n_citations, "
                        "answer_hash, error_message, cache_hit "
                        "FROM requests ORDER BY request_id").fetchall()
    assert kept == before                       # every row, every value
    # a row made before counted nothing: NULL says that, and 0 would not
    assert conn.execute("SELECT n_statements, n_dropped FROM requests "
                        "WHERE request_id = 1").fetchone() == (None, None)
    new = request_log.log_request(conn, 3, "neu", "text", [], 1.0,
                                  n_statements=5, n_dropped=2)
    assert new == 8                             # after the last, not over one
    assert conn.execute("SELECT n_statements, n_dropped FROM requests "
                        "WHERE request_id = 8").fetchone() == (5, 2)
    conn.close()
    again = request_log.connect(path)           # a second open has no work
    assert len(rows(again)) == 4
    again.close()


def test_the_oldest_table_gets_both_migrations_in_one_open(tmp_path):
    """The order is the trap: the table that demanded a document is made again
    from the columns it has, and only then are the new ones added. Were the
    new columns in the list that is carried over, this open would fail on a
    column the old table lacks."""
    path = tmp_path / "requests.db"
    old = sqlite3.connect(path)
    old.executescript(BEFORE)
    for request_id, document in ((1, 4), (5, 9)):
        old.execute("INSERT INTO requests (request_id, plan_id, query_text, "
                    "mode, scopes, n_hits) VALUES (?, ?, ?, 'text', '[]', 2)",
                    (request_id, document, f"q{request_id}"))
    old.commit()
    stamps = old.execute("SELECT timestamp FROM requests "
                         "ORDER BY request_id").fetchall()
    old.close()

    conn = request_log.connect(path)
    assert rows(conn) == [(1, 4, "q1", 2), (5, 9, "q5", 2)]
    assert conn.execute("SELECT timestamp FROM requests "
                        "ORDER BY request_id").fetchall() == stamps
    assert {"n_statements", "n_dropped"} <= set(columns(conn))
    new = request_log.log_request(conn, None, "überall", "text", [], 1.0,
                                  n_statements=1, n_dropped=0)
    assert new == 6
    conn.close()


def test_what_is_carried_over_is_what_every_old_table_has():
    """The violating construction: a column of the carry list that the oldest
    table does not have breaks the migration of every old log."""
    old = sqlite3.connect(":memory:")
    old.executescript(BEFORE)
    assert set(request_log._CARRIED) == set(columns(old))
    assert not {"n_statements", "n_dropped"} & set(request_log._CARRIED)
    assert {name for name, _kind in request_log._ADDED}         == {"n_statements", "n_dropped"}


def test_a_new_log_has_the_columns_from_the_start(tmp_path):
    conn = request_log.connect(tmp_path / "requests.db")
    assert columns(conn)[-2:] == ["n_statements", "n_dropped"]
    first = request_log.log_request(conn, 1, "q", "text", [], 1.0)
    assert conn.execute("SELECT n_statements, n_dropped FROM requests "
                        "WHERE request_id = ?", (first,)).fetchone()         == (None, None)
    conn.close()


def test_a_turn_logs_how_many_statements_it_made_and_how_many_were_dropped(
        tmp_path, monkeypatch):
    quote = "Der Wärmebedarf betrug 100 GWh."
    hit = {"owner_kind": "section", "owner_id": 1, "content": quote,
           "text": quote, "title": "T", "document_id": 1, "page_number": 1,
           "image_path": None}
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                        lambda *a, **k: [hit])
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("Bedarf", False))
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)
    wrote = [{"statement": "a", "basis": "text", "index": 0, "quote": quote},
             {"statement": "b", "basis": "text", "index": 0,
              "quote": "Das steht in keinem Auszug."},
             {"statement": "c", "basis": "text", "index": 0,
              "quote": "Auch das steht dort nicht."}]
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        lambda task, items, **kw: {
                            "statements": wrote, "complete": True,
                            "compute": [], "attached_images": [],
                            "requested": [], "fault": None})
    log = request_log.connect(tmp_path / "requests.db")
    corpus = answer.Corpus(conn=None, index=None, id_to_pos={},
                           embed=lambda item: ([0.0] * 4, False),
                           log_conn=log)
    answer.answer_question("Wie hoch?", corpus, 1, [answer.config.SCOPE_TEXT])
    assert log.execute("SELECT n_hits, n_citations, n_statements, n_dropped "
                       "FROM requests").fetchall() == [(1, 1, 3, 2)]
    log.close()
