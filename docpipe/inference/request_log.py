"""
request_log.py: Request logging in a separate SQLite file.

One line per chat turn: which document was asked (none for a question to
the whole corpus), the question, the scopes, how long it took and how many
passages, citations and statements it had (`n_statements` is what the model
wrote, `n_dropped` how many of those did not stand their check).

Answers are deliberately NOT cached: follow-up queries ("schau noch einmal
nach") are context-dependent, and a cache keyed on the query text alone serves
an answer from a different conversation.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

# The columns every older table has: the ones `_allow_no_document` copies from
# a table it replaces. A column added later is NOT in this list (the old table
# has none to copy) and is added to an opened log by `_add_missing_columns`.
_CARRIED = ("request_id", "plan_id", "query_text", "mode", "scopes",
            "timestamp", "latency_ms", "n_hits", "n_citations",
            "answer_hash", "error_message", "cache_hit")
# Added after the first logs were written; a row made before has NULL, which
# says "not counted" and not "none".
_ADDED = (("n_statements", "INTEGER"), ("n_dropped", "INTEGER"))

# plan_id is the document a request asked. NULL: it asked the whole corpus.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER,
    query_text      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    scopes          TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    latency_ms      REAL,
    n_hits          INTEGER,
    n_citations     INTEGER,
    answer_hash     TEXT,
    error_message   TEXT,
    cache_hit       BOOLEAN,
    n_statements    INTEGER,
    n_dropped       INTEGER
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the request log database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    conn.commit()
    _allow_no_document(conn)
    _add_missing_columns(conn)
    return conn


def _allow_no_document(conn: sqlite3.Connection) -> None:
    """Bring a log forward that was made when every request named a
    document. Its table refuses a request to the whole corpus, and SQLite
    cannot lift that from a column: the table is made again and every row
    carried over under its own id."""
    demands = any(row[1] == "plan_id" and row[3] for row in
                  conn.execute("PRAGMA table_info(requests)"))
    if not demands:
        return
    names = ", ".join(_CARRIED)
    conn.executescript(
        "BEGIN;\n"
        "ALTER TABLE requests RENAME TO requests_before;\n"
        + _SCHEMA +
        f"INSERT INTO requests ({names}) SELECT {names} "
        f"FROM requests_before;\n"
        "DROP TABLE requests_before;\n"
        "COMMIT;\n")


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a log forward that was made before a column existed. The rows
    keep what they had and read NULL in the new column."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
    for name, kind in _ADDED:
        if name not in have:
            conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {kind}")
    conn.commit()


def log_request(
    conn: sqlite3.Connection,
    plan_id: Optional[int],
    query_text: str,
    mode: str,
    scopes: list[str],
    latency_ms: float,
    n_hits: Optional[int] = None,
    n_citations: Optional[int] = None,
    answer_hash: Optional[str] = None,
    error_message: Optional[str] = None,
    cache_hit: bool = False,
    n_statements: Optional[int] = None,
    n_dropped: Optional[int] = None,
) -> int:
    """Log a single request. Returns the request_id."""
    cur = conn.execute(
        """
        INSERT INTO requests
        (plan_id, query_text, mode, scopes, latency_ms, n_hits, n_citations,
         answer_hash, error_message, cache_hit, n_statements, n_dropped)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            query_text,
            mode,
            json.dumps(sorted(scopes or []), separators=(",", ":")),
            latency_ms,
            n_hits,
            n_citations,
            answer_hash,
            error_message,
            cache_hit,
            n_statements,
            n_dropped,
        ),
    )
    conn.commit()
    return cur.lastrowid
