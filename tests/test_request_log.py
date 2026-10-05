"""The request log of the chat.

What is promised:

  * a request to one document is logged with that document AND a request to
    the whole corpus is logged with none;
  * a log made when every request named a document accepts a request to the
    whole corpus afterwards AND keeps every row it had under its own id AND
    numbers the next request after the last;
  * a chat turn over the whole corpus ends with its line in the log.
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
